# 使用方法

## 1. インストール

```bash
pip install -r requirements.txt
```

## 2. 設定ファイルを作る

`stream_processor.toml.example` をコピーして `stream_processor.toml` を作成します。

```bash
cp stream_processor.toml.example stream_processor.toml
```

### 設定項目

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `rtsp_url` | RTSP利用時は必須 | 受信対象の RTSP URL。`capture_backend=rtp` の場合は空欄で構いません。 |
| `snapshot_interval_sec` | `5.0` | スナップショット保存周期（秒）。 |
| `save_dir` | `./snapshots` | JPEG の保存先ディレクトリ。初回実行時に自動生成されます。 |
| `db_path` | `./snapshot_records.db` | SQLite DB の保存先。初回実行時に自動生成されます。 |
| `capture_backend` | `auto` | `auto` / `gstreamer` / `opencv` / `rtp`。`rtp` は FFmpegでH.264 RTP/UDPを受信します。 |
| `gstreamer_pipeline_template` | `uridecodebin uri="{url}" ! videoconvert ! appsink max-buffers=1 drop=true sync=false` | OpenCV の GStreamer 経由で使うパイプラインテンプレート。`{url}` を設定値に置換します。 |
| `jpeg_quality` | `95` | JPEG 品質。0-100。 |
| `reconnect_delay_sec` | `1.0` | ストリーム切断時の再接続待機秒数。 |
| `notification_url` | なし | JPEG 保存成功時に `file_path` と `timestamp` を POST する外部 API の URL。 |
| `rtp_port` | `5004` | `capture_backend=rtp` で待ち受けるUDPポート。 |
| `rtp_payload_type` | `96` | H.264 RTPのpayload type。 |
| `rtp_clock_rate` | `90000` | H.264 RTPのclock rate。 |
| `rtp_width` | `1280` | FFmpegから受け取るフレーム幅。 |
| `rtp_height` | `720` | FFmpegから受け取るフレーム高さ。 |

アプリケーション起動時に、`db_path` の既存SQLiteファイルとWAL/ジャーナル関連ファイルを削除し、空の `snapshots` テーブルを再作成します。前回起動分のスナップショット履歴は保持されません。

外部端末から生 RTP/UDP を受信する場合、配信先はDockerコンテナ名ではなく、Dockerを実行するホストのLAN IPとUDPポートです。現在のComposeは受信ホストのUDP `5004` をアプリコンテナへ公開しています。

```text
外部端末 -- RTP/UDP:5004 --> Docker実行ホストのLAN IP:5004 --> appコンテナ:5004
```

`capture_backend=rtp` を指定すると、`FrameReceiver` がFFmpegを使ってH.264 RTP/UDPを受信・デコードします。RTSP入力は `capture_backend=auto`、`gstreamer`、または `opencv` を使用し、従来どおり `cv2.VideoCapture()` で処理します。

## 3. 実行

```bash
python src/stream_processor.py --config stream_processor.toml
```

CLI 引数は TOML の設定を上書きします。`--help` で全引数を確認できます。

### CLI 引数一覧

| 引数 | 対応 TOML キー | 説明 |
| --- | --- | --- |
| `--config` | — | TOML 設定ファイルパス。省略時は `./stream_processor.toml` を自動検索 |
| `--rtsp-url` | `rtsp_url` | RTSP ストリーム URL（`capture_backend=rtp` 時は不要） |
| `--snapshot-interval` | `snapshot_interval_sec` | スナップショット保存周期（秒） |
| `--save-dir` | `save_dir` | JPEG 保存先ディレクトリ |
| `--db-path` | `db_path` | SQLite DB ファイルパス |
| `--capture-backend` | `capture_backend` | `auto` / `gstreamer` / `opencv` / `rtp` |
| `--gstreamer-pipeline-template` | `gstreamer_pipeline_template` | GStreamer パイプラインテンプレート（`{url}` プレースホルダー） |
| `--jpeg-quality` | `jpeg_quality` | JPEG 品質（0–100） |
| `--reconnect-delay` | `reconnect_delay_sec` | 切断時の再接続待機秒数 |
| `--notification-url` | `notification_url` | スナップショット保存成功時の通知先 URL |
| `--rtp-port` | `rtp_port` | H.264 RTP/UDP 受信 UDP ポート |
| `--rtp-payload-type` | `rtp_payload_type` | RTP payload type |
| `--rtp-clock-rate` | `rtp_clock_rate` | RTP clock rate |
| `--rtp-width` | `rtp_width` | デコード後のフレーム幅（px） |
| `--rtp-height` | `rtp_height` | デコード後のフレーム高さ（px） |
| `--log-level` | — | ログレベル `DEBUG` / `INFO` / `WARNING` / `ERROR`（既定: `INFO`） |

## 4. 同一LAN上の実機RTPを受信する

Dockerを実行するホストのLAN IPを、RTP配信端末の送信先に設定します。ComposeはUDP `5004`をアプリコンテナへ公開します。

```text
RTP配信端末 -- H.264 RTP/UDP --> DockerホストのLAN IP:5004 --> app:5004
```

実機配信が `192.168.1.100:5004` へ送信する場合の起動例:

```bash
RTP_PORT=5004 \
CAPTURE_BACKEND=rtp \
RTP_WIDTH=1280 \
RTP_HEIGHT=720 \
docker compose up --build
```

受信ホストではUDP `5004`をFirewallで許可してください。テストAPIの受信ログ、JPEG、SQLiteは `docker-data/` 以下に保存されます。

## 5. ローカル開発環境で RTSP テストストリームを配信する

WSL2 上で GStreamer と MediaMTX を使ってテストするときは、GStreamer の動画テストソース `videotestsrc` を使うのが簡単です。
ここでは MediaMTX を RTSP サーバーとして立て、GStreamer から test video を publish します。

### 5-1. MediaMTX を起動する

```bash
mediamtx
```

MediaMTX の既定 RTSP ポートは `8554` です。
以下では `teststream` というパスに公開します。

### 5-2. GStreamer で test video を publish する

`videotestsrc` は GStreamer の標準的なテスト映像ソースです。
以下のコマンドで、H.264 にエンコードして MediaMTX へ publish します。

```text
前提: `gst-inspect-1.0 rtspclientsink` で要素が見えること。
見えない場合は、使用している GStreamer パッケージセットに RTSP publish 用のプラグインを追加してください。
```

```bash
gst-launch-1.0 \
	videotestsrc is-live=true pattern=smpte ! \
	video/x-raw,format=I420,framerate=30/1 ! \
	videoconvert ! \
	x264enc tune=zerolatency speed-preset=ultrafast byte-stream=true key-int-max=30 bitrate=1000 ! \
	rtspclientsink location=rtsp://127.0.0.1:8554/teststream
```

### 5-3. 本アプリを接続する

`stream_processor.toml` には、次のように設定します。

```toml
rtsp_url = "rtsp://127.0.0.1:8554/teststream"
capture_backend = "gstreamer"
gstreamer_pipeline_template = 'uridecodebin uri="{url}" ! videoconvert ! appsink max-buffers=1 drop=true sync=false'
```

起動は次の通りです。

```bash
python src/stream_processor.py --config stream_processor.toml
```

## 6. DB テーブル

`snapshots` テーブルには以下が保存されます。

| カラム名 | 内容 |
| --- | --- |
| `id` | 主キー |
| `file_path` | 保存された JPEG の絶対パス |
| `timestamp` | `YYYY-MM-DD HH:MM:SS.SSS` 形式の保存時刻 |
| `status` | 保存成功なら `1`、失敗なら `0` |

外部 API の通知形式は [外部API仕様](api-spec.md) を参照してください。

## 7. 補足

- `auto` は GStreamer を優先し、失敗時は OpenCV にフォールバックします。
- `capture_backend=gstreamer` を使う場合、OpenCV 側が GStreamer 対応ビルドである必要があります。
- スナップショット保存先と DB は、指定のパスが無ければ自動生成されます。