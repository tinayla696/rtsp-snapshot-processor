from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import stream_processor as sp


class DummyRepository:
    def __init__(self) -> None:
        self.records: list[tuple[Path, str, bool]] = []

    def add_snapshot_record(self, file_path: Path, timestamp_text: str, status: bool) -> None:
        self.records.append((file_path, timestamp_text, status))


class FixedDatetime(datetime):
    @classmethod
    def now(cls):
        return cls(2026, 7, 30, 12, 34, 56, 789123)


class FakeCapture:
    calls: list[tuple[str, object | None]] = []

    def __init__(self, source, api_preference=None):
        self.source = source
        self.api_preference = api_preference
        self.opened = api_preference == sp.cv2.CAP_GSTREAMER
        FakeCapture.calls.append((source, api_preference))

    def isOpened(self):
        return self.opened

    def release(self):
        pass

    def set(self, *_args, **_kwargs):
        pass


def test_snapshot_repository_creates_db_and_persists_absolute_path(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "snapshot_records.db"
    repository = sp.SnapshotRepository(db_path)

    image_path = tmp_path / "snapshot.jpg"
    image_path.write_bytes(b"dummy")

    repository.add_snapshot_record(image_path, "2026-07-30 12:34:56.789", True)
    repository.close()

    assert db_path.exists()

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT file_path, timestamp, status FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert row == (str(image_path.resolve()), "2026-07-30 12:34:56.789", 1)


def test_snapshot_repository_resets_database_on_startup(tmp_path: Path) -> None:
    db_path = tmp_path / "snapshot_records.db"
    first_repository = sp.SnapshotRepository(db_path)
    first_repository.add_snapshot_record(
        tmp_path / "old-snapshot.jpg",
        "2026-07-30 12:34:56.789",
        True,
    )
    first_repository.close()

    second_repository = sp.SnapshotRepository(db_path)

    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()

    second_repository.close()

    assert row == (0,)


def test_snapshot_service_writes_jpeg_and_registers_record(monkeypatch, tmp_path: Path) -> None:
    repository = DummyRepository()
    receiver = object()
    service = sp.SnapshotService(
        receiver=receiver,
        repository=repository,
        save_dir=tmp_path,
        snapshot_interval_sec=5.0,
        jpeg_quality=90,
    )

    calls: list[tuple[str, object, list[int]]] = []

    def fake_imwrite(path: str, frame, params):
        calls.append((path, frame, params))
        return True

    monkeypatch.setattr(sp.cv2, "imwrite", fake_imwrite)
    monkeypatch.setattr(sp, "datetime", FixedDatetime)

    service._persist_snapshot("frame-bytes")

    assert len(calls) == 1
    saved_path = Path(calls[0][0])
    assert saved_path.is_absolute()
    assert saved_path.suffix == ".jpg"
    assert repository.records == [
        (saved_path, "2026-07-30 12:34:56.789", True)
    ]


def test_snapshot_service_registers_false_status_when_write_fails(monkeypatch, tmp_path: Path) -> None:
    repository = DummyRepository()
    receiver = object()
    service = sp.SnapshotService(
        receiver=receiver,
        repository=repository,
        save_dir=tmp_path,
        snapshot_interval_sec=5.0,
        jpeg_quality=90,
    )

    def fake_imwrite(path: str, frame, params):
        return False

    monkeypatch.setattr(sp.cv2, "imwrite", fake_imwrite)
    monkeypatch.setattr(sp, "datetime", FixedDatetime)

    service._persist_snapshot("frame-bytes")

    assert len(repository.records) == 1
    file_path, timestamp_text, status = repository.records[0]
    assert file_path.is_absolute()
    assert timestamp_text == "2026-07-30 12:34:56.789"
    assert status is False


def test_snapshot_service_notifies_external_api_after_success(monkeypatch, tmp_path: Path) -> None:
    repository = DummyRepository()
    receiver = object()
    notifications: list[tuple[Path, str]] = []

    class StubNotifier:
        def notify(self, file_path: Path, timestamp_text: str) -> None:
            notifications.append((file_path, timestamp_text))

    service = sp.SnapshotService(
        receiver=receiver,
        repository=repository,
        save_dir=tmp_path,
        snapshot_interval_sec=5.0,
        jpeg_quality=90,
        notifier=StubNotifier(),
    )

    monkeypatch.setattr(sp.cv2, "imwrite", lambda *args, **kwargs: True)
    monkeypatch.setattr(sp, "datetime", FixedDatetime)

    service._persist_snapshot("frame-bytes")

    assert len(repository.records) == 1
    assert len(notifications) == 1
    file_path, timestamp_text = notifications[0]
    assert file_path == repository.records[0][0]
    assert timestamp_text == "2026-07-30 12:34:56.789"


def test_parse_args_maps_cli_to_config(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stream_processor.py",
            "--rtsp-url",
            "rtsp://example/stream",
            "--snapshot-interval",
            "7.5",
            "--save-dir",
            "./shots",
            "--db-path",
            "./records.db",
            "--jpeg-quality",
            "88",
            "--reconnect-delay",
            "1.5",
            "--notification-url",
            "https://example.test/notify",
            "--log-level",
            "DEBUG",
        ],
    )

    config = sp.parse_args()

    assert config.rtsp_url == "rtsp://example/stream"
    assert config.snapshot_interval_sec == 7.5
    assert config.save_dir == Path("./shots")
    assert config.db_path == Path("./records.db")
    assert config.capture_backend == "auto"
    assert config.jpeg_quality == 88
    assert config.reconnect_delay_sec == 1.5
    assert config.notification_url == "https://example.test/notify"


def test_parse_args_supports_rtp_without_rtsp_url(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stream_processor.py",
            "--capture-backend",
            "rtp",
            "--rtp-port",
            "5004",
            "--rtp-width",
            "1280",
            "--rtp-height",
            "720",
        ],
    )

    config = sp.parse_args()

    assert config.capture_backend == "rtp"
    assert config.rtsp_url == ""
    assert config.rtp_port == 5004
    assert config.rtp_width == 1280
    assert config.rtp_height == 720


def test_frame_receiver_builds_h264_rtp_sdp() -> None:
    receiver = sp.FrameReceiver(
        stream_url="",
        capture_backend="rtp",
        rtp_port=5004,
        rtp_payload_type=96,
        rtp_clock_rate=90000,
    )

    sdp = receiver._build_rtp_sdp()

    assert "m=video 5004 RTP/AVP 96" in sdp
    assert "a=rtpmap:96 H264/90000" in sdp
    assert "a=fmtp:96 packetization-mode=1" in sdp


def test_frame_receiver_uses_low_latency_corrupt_packet_options() -> None:
    receiver = sp.FrameReceiver(stream_url="", capture_backend="rtp")

    command = receiver._build_rtp_command()

    assert ["-fflags", "+nobuffer+discardcorrupt"] == command[command.index("-fflags"):command.index("-fflags") + 2]
    assert ["-probesize", "32"] == command[command.index("-probesize"):command.index("-probesize") + 2]
    assert ["-analyzeduration", "0"] == command[command.index("-analyzeduration"):command.index("-analyzeduration") + 2]
    assert ["-reorder_queue_size", "0"] == command[command.index("-reorder_queue_size"):command.index("-reorder_queue_size") + 2]
    assert "-vsync" not in command


def test_rtp_run_loop_does_not_respawn_ffmpeg_process_on_every_iteration(monkeypatch) -> None:
    receiver = sp.FrameReceiver(
        stream_url="",
        capture_backend="rtp",
        reconnect_delay_sec=0.001,
    )
    receiver._rtp_process = object()
    open_calls = 0

    def fail_if_reopened() -> bool:
        nonlocal open_calls
        open_calls += 1
        return False

    monkeypatch.setattr(receiver, "_open_capture", fail_if_reopened)
    monkeypatch.setattr(receiver, "_read_rtp_frame", lambda: None)

    def stop_after_one_release() -> None:
        receiver._rtp_process = None
        receiver._stop_event.set()

    monkeypatch.setattr(receiver, "_release_rtp_process", stop_after_one_release)
    receiver._run()

    assert open_calls == 0


def test_parse_args_loads_values_from_toml_config(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "stream_processor.toml"
    config_path.write_text(
        """
rtsp_url = "rtsp://config/stream"
snapshot_interval_sec = 3.0
save_dir = "./config-shots"
db_path = "./config.db"
capture_backend = "gstreamer"
gstreamer_pipeline_template = 'pipeline uri="{url}"'
jpeg_quality = 80
reconnect_delay_sec = 2.5
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["stream_processor.py", "--config", str(config_path)],
    )

    config = sp.parse_args()

    assert config.config_path == config_path.resolve()
    assert config.rtsp_url == "rtsp://config/stream"
    assert config.snapshot_interval_sec == 3.0
    assert config.save_dir == Path("./config-shots")
    assert config.db_path == Path("./config.db")
    assert config.capture_backend == "gstreamer"
    assert config.gstreamer_pipeline_template == 'pipeline uri="{url}"'
    assert config.jpeg_quality == 80
    assert config.reconnect_delay_sec == 2.5


def test_cli_arguments_override_toml_config(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "stream_processor.toml"
    config_path.write_text(
        """
rtsp_url = "rtsp://config/stream"
snapshot_interval_sec = 3.0
save_dir = "./config-shots"
db_path = "./config.db"
capture_backend = "gstreamer"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stream_processor.py",
            "--config",
            str(config_path),
            "--rtsp-url",
            "rtsp://cli/stream",
            "--snapshot-interval",
            "10",
            "--capture-backend",
            "opencv",
        ],
    )

    config = sp.parse_args()

    assert config.rtsp_url == "rtsp://cli/stream"
    assert config.snapshot_interval_sec == 10.0
    assert config.capture_backend == "opencv"


def test_gstreamer_pipeline_template_is_expanded() -> None:
    receiver = sp.FrameReceiver(
        stream_url="rtsp://example/stream",
        capture_backend="gstreamer",
        gstreamer_pipeline_template='uridecodebin uri="{url}" ! videoconvert ! appsink',
    )

    assert receiver._build_gstreamer_pipeline("rtsp://example/stream") == (
        'uridecodebin uri="rtsp://example/stream" ! videoconvert ! appsink'
    )


def test_auto_backend_prefers_gstreamer_then_opencv(monkeypatch) -> None:
    FakeCapture.calls = []
    monkeypatch.setattr(sp.cv2, "VideoCapture", FakeCapture)

    receiver = sp.FrameReceiver(
        stream_url="rtsp://example/stream",
        capture_backend="auto",
        gstreamer_pipeline_template='pipeline uri="{url}"',
    )

    assert receiver._open_capture() is True
    assert FakeCapture.calls == [
        ('pipeline uri="rtsp://example/stream"', sp.cv2.CAP_GSTREAMER)
    ]


def test_auto_backend_falls_back_to_opencv_when_gstreamer_fails(monkeypatch) -> None:
    class FailingThenOpenCapture(FakeCapture):
        def __init__(self, source, api_preference=None):
            self.source = source
            self.api_preference = api_preference
            self.opened = api_preference != sp.cv2.CAP_GSTREAMER
            FakeCapture.calls.append((source, api_preference))

    FakeCapture.calls = []
    monkeypatch.setattr(sp.cv2, "VideoCapture", FailingThenOpenCapture)

    receiver = sp.FrameReceiver(
        stream_url="rtsp://example/stream",
        capture_backend="auto",
        gstreamer_pipeline_template='pipeline uri="{url}"',
    )

    assert receiver._open_capture() is True
    assert FakeCapture.calls == [
        ('pipeline uri="rtsp://example/stream"', sp.cv2.CAP_GSTREAMER),
        ("rtsp://example/stream", sp.cv2.CAP_FFMPEG),
    ]