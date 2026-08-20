"""RTSP/RTP stream receiver with periodic snapshot persistence and SQLite logging."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import signal
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ImportError:  # Python 3.10 fallback
    import tomli as tomllib

import cv2
import numpy as np


@dataclass(frozen=True)
class AppConfig:
    rtsp_url: str
    snapshot_interval_sec: float
    save_dir: Path
    db_path: Path
    config_path: Optional[Path] = None
    capture_backend: str = "auto"
    gstreamer_pipeline_template: Optional[str] = None
    jpeg_quality: int = 95
    reconnect_delay_sec: float = 1.0
    notification_url: Optional[str] = None
    rtp_port: int = 5004
    rtp_payload_type: int = 96
    rtp_clock_rate: int = 90000
    rtp_width: int = 1280
    rtp_height: int = 720


@dataclass(frozen=True)
class CaptureTarget:
    name: str
    source: str
    api_preference: Optional[int]


class SnapshotRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.resolve()
        self._lock = threading.Lock()
        self._connection: Optional[sqlite3.Connection] = None
        self._initialize()

    def _initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL;")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            """
        )
        self._ensure_status_column()
        self._connection.commit()

    def _ensure_status_column(self) -> None:
        if self._connection is None:
            raise RuntimeError("SQLite connection is not initialized.")

        columns = {
            row[1]
            for row in self._connection.execute("PRAGMA table_info(snapshots);").fetchall()
        }
        if "status" not in columns:
            self._connection.execute(
                "ALTER TABLE snapshots ADD COLUMN status INTEGER NOT NULL DEFAULT 1;"
            )

    def add_snapshot_record(self, file_path: Path, timestamp_text: str, status: bool) -> None:
        if self._connection is None:
            raise RuntimeError("SQLite connection is not initialized.")

        with self._lock:
            self._connection.execute(
                "INSERT INTO snapshots (file_path, timestamp, status) VALUES (?, ?, ?);",
                (str(file_path.resolve()), timestamp_text, int(status)),
            )
            self._connection.commit()

    def close(self) -> None:
        if self._connection is None:
            return
        with self._lock:
            self._connection.close()
            self._connection = None


class FrameReceiver:
    def __init__(
        self,
        stream_url: str,
        reconnect_delay_sec: float = 1.0,
        capture_backend: str = "auto",
        gstreamer_pipeline_template: Optional[str] = None,
        rtp_port: int = 5004,
        rtp_payload_type: int = 96,
        rtp_clock_rate: int = 90000,
        rtp_width: int = 1280,
        rtp_height: int = 720,
    ) -> None:
        self._stream_url = stream_url
        self._reconnect_delay_sec = reconnect_delay_sec
        self._capture_backend = capture_backend
        self._gstreamer_pipeline_template = (
            gstreamer_pipeline_template
            or 'uridecodebin uri="{url}" ! videoconvert ! appsink max-buffers=1 drop=true sync=false'
        )
        self._rtp_port = rtp_port
        self._rtp_payload_type = rtp_payload_type
        self._rtp_clock_rate = rtp_clock_rate
        self._rtp_width = rtp_width
        self._rtp_height = rtp_height
        self._latest_frame = None
        self._capture: Optional[cv2.VideoCapture] = None
        self._rtp_process: Optional[subprocess.Popen[bytes]] = None
        self._rtp_frame_size = rtp_width * rtp_height * 3
        self._active_backend_name = "unknown"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="frame-receiver", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._release_capture()
        self._release_rtp_process()
        self._thread.join(timeout=5.0)

    def get_latest_frame(self):
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def _open_capture(self) -> bool:
        self._release_capture()

        if self._capture_backend == "rtp":
            return self._open_rtp_capture()

        for target in self._build_capture_targets():
            if target.api_preference is None:
                capture = cv2.VideoCapture(target.source)
            else:
                capture = cv2.VideoCapture(target.source, target.api_preference)

            if not capture.isOpened():
                capture.release()
                logging.warning(
                    "Failed to open stream via %s backend: %s",
                    target.name,
                    self._stream_url,
                )
                continue

            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._capture = capture
            self._active_backend_name = target.name
            logging.info(
                "Stream connected via %s backend: %s",
                target.name,
                self._stream_url,
            )
            return True

        logging.warning("Failed to open stream: %s", self._stream_url)
        return False

    def _open_rtp_capture(self) -> bool:
        sdp = self._build_rtp_sdp()
        frame_size = self._rtp_width * self._rtp_height * 3
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file,pipe,udp,rtp",
            "-f",
            "sdp",
            "-i",
            "pipe:0",
            "-an",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-vf",
            f"scale={self._rtp_width}:{self._rtp_height}",
            "pipe:1",
        ]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if process.stdin is None or process.stdout is None:
                process.kill()
                return False
            process.stdin.write(sdp.encode("ascii"))
            process.stdin.close()
        except (OSError, subprocess.SubprocessError):
            logging.exception("Failed to start FFmpeg RTP receiver on UDP port %s", self._rtp_port)
            return False

        self._rtp_process = process
        self._rtp_frame_size = frame_size
        logging.info("RTP receiver listening on UDP port %s", self._rtp_port)
        return True

    def _build_rtp_sdp(self) -> str:
        return (
            "v=0\n"
            "o=- 0 0 IN IP4 127.0.0.1\n"
            "s=rtsp-snapshot-processor\n"
            "c=IN IP4 0.0.0.0\n"
            "t=0 0\n"
            f"m=video {self._rtp_port} RTP/AVP {self._rtp_payload_type}\n"
            f"a=rtpmap:{self._rtp_payload_type} H264/{self._rtp_clock_rate}\n"
            f"a=fmtp:{self._rtp_payload_type} packetization-mode=1\n"
            "a=recvonly\n"
        )

    def _build_capture_targets(self) -> list[CaptureTarget]:
        if self._capture_backend == "gstreamer":
            return [
                CaptureTarget(
                    name="gstreamer",
                    source=self._build_gstreamer_pipeline(self._stream_url),
                    api_preference=cv2.CAP_GSTREAMER,
                )
            ]

        if self._capture_backend == "opencv":
            return [
                CaptureTarget(
                    name="opencv",
                    source=self._stream_url,
                    api_preference=cv2.CAP_FFMPEG,
                )
            ]

        return [
            CaptureTarget(
                name="gstreamer",
                source=self._build_gstreamer_pipeline(self._stream_url),
                api_preference=cv2.CAP_GSTREAMER,
            ),
            CaptureTarget(
                name="opencv",
                source=self._stream_url,
                api_preference=cv2.CAP_FFMPEG,
            ),
        ]

    def _build_gstreamer_pipeline(self, stream_url: str) -> str:
        return self._gstreamer_pipeline_template.format(url=stream_url)

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _release_rtp_process(self) -> None:
        if self._rtp_process is None:
            return
        self._rtp_process.terminate()
        try:
            self._rtp_process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._rtp_process.kill()
            self._rtp_process.wait()
        self._rtp_process = None

    def _read_rtp_frame(self):
        if self._rtp_process is None or self._rtp_process.stdout is None:
            return None
        frame_bytes = self._rtp_process.stdout.read(self._rtp_frame_size)
        if len(frame_bytes) != self._rtp_frame_size:
            return None
        return np.frombuffer(frame_bytes, dtype=np.uint8).reshape(
            (self._rtp_height, self._rtp_width, 3)
        ).copy()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._capture is None and self._rtp_process is None and not self._open_capture():
                time.sleep(self._reconnect_delay_sec)
                continue

            if self._capture is None:
                if self._rtp_process is None:
                    continue
                frame = self._read_rtp_frame()
                if frame is None:
                    logging.warning("RTP frame receive failed. Restarting receiver...")
                    self._release_rtp_process()
                    time.sleep(self._reconnect_delay_sec)
                    continue
                with self._lock:
                    self._latest_frame = frame
                continue

            ok, frame = self._capture.read()
            if not ok or frame is None:
                logging.warning("Frame receive failed. Reconnecting stream...")
                self._release_capture()
                time.sleep(self._reconnect_delay_sec)
                continue

            with self._lock:
                self._latest_frame = frame


class ExternalNotifier:
    def __init__(self, notification_url: Optional[str]) -> None:
        self._notification_url = (
            notification_url.strip() if notification_url is not None and notification_url.strip() else None
        )

    def notify(self, file_path: Path, timestamp_text: str) -> None:
        if self._notification_url is None:
            return

        payload = {
            "file_path": str(file_path.resolve()),
            "timestamp": timestamp_text,
        }
        request = urllib.request.Request(
            self._notification_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if getattr(response, "status", 200) >= 400:
                    raise urllib.error.HTTPError(
                        request.full_url,
                        response.status,
                        response.reason,
                        response.headers,
                        fp=response
                    )
        except Exception:
            logging.exception(
                "Failed to notify external API at %s for snapshot %s (%s)",
                self._notification_url,
                file_path,
                timestamp_text,
            )


class SnapshotService:
    def __init__(
        self,
        receiver: FrameReceiver,
        repository: SnapshotRepository,
        save_dir: Path,
        snapshot_interval_sec: float,
        jpeg_quality: int = 95,
        notifier: Optional[ExternalNotifier] = None,
    ) -> None:
        self._receiver = receiver
        self._repository = repository
        self._save_dir = save_dir.resolve()
        self._snapshot_interval_sec = snapshot_interval_sec
        self._jpeg_quality = jpeg_quality
        self._notifier = notifier
        self._stop_event = threading.Event()

        self._save_dir.mkdir(parents=True, exist_ok=True)

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        next_tick = time.monotonic()
        while not self._stop_event.is_set():
            now_monotonic = time.monotonic()
            if now_monotonic < next_tick:
                time.sleep(min(0.1, next_tick - now_monotonic))
                continue

            frame = self._receiver.get_latest_frame()
            if frame is None:
                logging.debug("Snapshot skipped because frame is not ready.")
            else:
                try:
                    self._persist_snapshot(frame)
                except Exception:
                    logging.exception("Snapshot persistence failed; continuing execution.")

            next_tick += self._snapshot_interval_sec
            if next_tick < time.monotonic():
                next_tick = time.monotonic() + self._snapshot_interval_sec

    def _persist_snapshot(self, frame) -> None:
        captured_at = datetime.now()
        ts_for_db = captured_at.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        file_name = captured_at.strftime("snapshot_%Y%m%d_%H%M%S_%f")[:-3] + ".jpg"
        file_path = self._save_dir / file_name

        ok = cv2.imwrite(
            str(file_path),
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(self._jpeg_quality)],
        )
        if not ok:
            logging.error("Failed to write snapshot: %s", file_path)
            self._repository.add_snapshot_record(file_path, ts_for_db, False)
            return

        self._repository.add_snapshot_record(file_path, ts_for_db, True)
        if self._notifier is not None:
            self._notifier.notify(file_path, ts_for_db)
        logging.info("Snapshot saved: %s (%s)", file_path, ts_for_db)


class StreamProcessorApplication:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._repository = SnapshotRepository(config.db_path)
        self._receiver = FrameReceiver(
            stream_url=config.rtsp_url,
            reconnect_delay_sec=config.reconnect_delay_sec,
            capture_backend=config.capture_backend,
            gstreamer_pipeline_template=config.gstreamer_pipeline_template,
            rtp_port=config.rtp_port,
            rtp_payload_type=config.rtp_payload_type,
            rtp_clock_rate=config.rtp_clock_rate,
            rtp_width=config.rtp_width,
            rtp_height=config.rtp_height,
        )
        self._snapshot_service = SnapshotService(
            receiver=self._receiver,
            repository=self._repository,
            save_dir=config.save_dir,
            snapshot_interval_sec=config.snapshot_interval_sec,
            jpeg_quality=config.jpeg_quality,
            notifier=ExternalNotifier(config.notification_url),
        )
        self._shutdown_event = threading.Event()

    def run(self) -> None:
        self._install_signal_handlers()
        self._receiver.start()
        logging.info("Application started. Press Ctrl+C to stop.")
        try:
            self._snapshot_service.run()
        except KeyboardInterrupt:
            logging.info("Ctrl+C received. Stopping application...")
            self._shutdown_event.set()
        finally:
            self._shutdown()

    def _install_signal_handlers(self) -> None:
        def _handle_signal(signum, _frame) -> None:
            logging.info("Received signal %s. Stopping application...", signum)
            self._shutdown_event.set()
            self._snapshot_service.stop()

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

    def _shutdown(self) -> None:
        if self._shutdown_event.is_set():
            logging.info("Graceful shutdown is in progress.")
        self._snapshot_service.stop()
        self._receiver.stop()
        self._repository.close()
        logging.info("Application stopped.")


def parse_args() -> AppConfig:
    bootstrap_parser = argparse.ArgumentParser(add_help=False)
    bootstrap_parser.add_argument(
        "--config",
        default=None,
        help="TOML config file path. Defaults to ./stream_processor.toml when present.",
    )

    bootstrap_args, _unknown = bootstrap_parser.parse_known_args()
    config_path = _resolve_config_path(bootstrap_args.config)
    try:
        config_data = _load_toml_config(config_path) if config_path is not None else {}
    except (FileNotFoundError, tomllib.TOMLDecodeError, ValueError) as exc:
        bootstrap_parser.error(str(exc))
        raise AssertionError("unreachable") from exc

    parser = argparse.ArgumentParser(
        parents=[bootstrap_parser],
        description="Receive RTSP/RTP stream and store periodic JPEG snapshots with SQLite records."
    )
    parser.add_argument("--rtsp-url", default=config_data.get("rtsp_url", ""), help="RTSP stream URL")
    parser.add_argument(
        "--snapshot-interval",
        type=float,
        default=float(config_data.get("snapshot_interval_sec", 5.0)),
        help="Snapshot interval in seconds",
    )
    parser.add_argument(
        "--save-dir",
        default=str(config_data.get("save_dir", "./snapshots")),
        help="Directory where snapshots are saved",
    )
    parser.add_argument(
        "--db-path",
        default=str(config_data.get("db_path", "./snapshot_records.db")),
        help="SQLite file path for snapshot metadata",
    )
    parser.add_argument(
        "--capture-backend",
        default=str(config_data.get("capture_backend", "auto")),
        choices=["auto", "gstreamer", "opencv", "rtp"],
        help="Capture backend. auto prefers GStreamer, then OpenCV; rtp receives H.264 RTP/UDP via FFmpeg.",
    )
    parser.add_argument(
        "--gstreamer-pipeline-template",
        default=config_data.get("gstreamer_pipeline_template"),
        help='GStreamer pipeline template with {url} placeholder. Example: uridecodebin uri="{url}" ! videoconvert ! appsink max-buffers=1 drop=true sync=false',
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=int(config_data.get("jpeg_quality", 95)),
        help="JPEG quality from 0 to 100",
    )
    parser.add_argument(
        "--reconnect-delay",
        type=float,
        default=float(config_data.get("reconnect_delay_sec", 1.0)),
        help="Delay before reconnect attempt when stream is disconnected",
    )
    parser.add_argument(
        "--notification-url",
        default=config_data.get("notification_url"),
        help="Optional external HTTP endpoint receiving JSON payloads with file_path and timestamp when snapshots are saved.",
    )
    parser.add_argument(
        "--rtp-port",
        type=int,
        default=int(config_data.get("rtp_port", 5004)),
        help="UDP port for H.264 RTP input when --capture-backend=rtp",
    )
    parser.add_argument(
        "--rtp-payload-type",
        type=int,
        default=int(config_data.get("rtp_payload_type", 96)),
        help="RTP payload type for H.264 input",
    )
    parser.add_argument(
        "--rtp-clock-rate",
        type=int,
        default=int(config_data.get("rtp_clock_rate", 90000)),
        help="RTP clock rate for H.264 input",
    )
    parser.add_argument(
        "--rtp-width",
        type=int,
        default=int(config_data.get("rtp_width", 1280)),
        help="Decoded RTP frame width",
    )
    parser.add_argument(
        "--rtp-height",
        type=int,
        default=int(config_data.get("rtp_height", 720)),
        help="Decoded RTP frame height",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    if args.capture_backend != "rtp" and not args.rtsp_url:
        parser.error("--rtsp-url is required unless --capture-backend=rtp")
    if args.snapshot_interval <= 0:
        parser.error("--snapshot-interval must be > 0")
    if not (0 <= args.jpeg_quality <= 100):
        parser.error("--jpeg-quality must be between 0 and 100")
    if args.reconnect_delay <= 0:
        parser.error("--reconnect-delay must be > 0")
    if not (1 <= args.rtp_port <= 65535):
        parser.error("--rtp-port must be between 1 and 65535")
    if not (0 <= args.rtp_payload_type <= 127):
        parser.error("--rtp-payload-type must be between 0 and 127")
    if args.rtp_clock_rate <= 0:
        parser.error("--rtp-clock-rate must be > 0")
    if args.rtp_width <= 0 or args.rtp_height <= 0:
        parser.error("--rtp-width and --rtp-height must be > 0")

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
    )

    return AppConfig(
        rtsp_url=args.rtsp_url,
        snapshot_interval_sec=args.snapshot_interval,
        save_dir=Path(args.save_dir),
        db_path=Path(args.db_path),
        config_path=config_path,
        capture_backend=args.capture_backend,
        gstreamer_pipeline_template=args.gstreamer_pipeline_template,
        jpeg_quality=args.jpeg_quality,
        reconnect_delay_sec=args.reconnect_delay,
        notification_url=args.notification_url,
        rtp_port=args.rtp_port,
        rtp_payload_type=args.rtp_payload_type,
        rtp_clock_rate=args.rtp_clock_rate,
        rtp_width=args.rtp_width,
        rtp_height=args.rtp_height,
    )


def _resolve_config_path(config_arg: Optional[str]) -> Optional[Path]:
    if config_arg is not None:
        return Path(config_arg).expanduser().resolve()

    default_path = Path("stream_processor.toml")
    if default_path.exists():
        return default_path.resolve()

    return None


def _load_toml_config(config_path: Path) -> dict[str, object]:
    try:
        with config_path.open("rb") as file_handle:
            data = tomllib.load(file_handle)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Config file not found: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML config: {config_path}") from exc

    if not isinstance(data, dict):
        raise ValueError("Config file must contain a TOML table at the root.")

    return data


def main() -> None:
    config = parse_args()
    app = StreamProcessorApplication(config)
    app.run()


if __name__ == "__main__":
    main()
