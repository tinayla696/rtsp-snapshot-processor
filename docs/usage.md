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
| `rtsp_url` | 必須 | 受信対象の RTSP URL。MediaMTX で公開した test stream も指定できます。 |
| `snapshot_interval_sec` | `5.0` | スナップショット保存周期（秒）。 |
| `save_dir` | `./snapshots` | JPEG の保存先ディレクトリ。初回実行時に自動生成されます。 |
| `db_path` | `./snapshot_records.db` | SQLite DB の保存先。初回実行時に自動生成されます。 |
| `capture_backend` | `auto` | `auto` / `gstreamer` / `opencv`。`auto` は GStreamer を優先します。 |
| `gstreamer_pipeline_template` | `uridecodebin uri="{url}" ! videoconvert ! appsink max-buffers=1 drop=true sync=false` | OpenCV の GStreamer 経由で使うパイプラインテンプレート。`{url}` を設定値に置換します。 |
| `jpeg_quality` | `95` | JPEG 品質。0-100。 |
| `reconnect_delay_sec` | `1.0` | ストリーム切断時の再接続待機秒数。 |

## 3. 実行

```bash
python src/stream_processor.py --config stream_processor.toml
```

CLI 引数は TOML の設定を上書きします。

## 4. ローカル開発環境で RTSP テストストリームを配信する

WSL2 上で GStreamer と MediaMTX を使ってテストするときは、GStreamer の動画テストソース `videotestsrc` を使うのが簡単です。
ここでは MediaMTX を RTSP サーバーとして立て、GStreamer から test video を publish します。

### 4-1. MediaMTX を起動する

```bash
mediamtx
```

MediaMTX の既定 RTSP ポートは `8554` です。
以下では `teststream` というパスに公開します。

### 4-2. GStreamer で test video を publish する

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

### 4-3. 本アプリを接続する

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

## 5. DB テーブル

`snapshots` テーブルには以下が保存されます。

| カラム名 | 内容 |
| --- | --- |
| `id` | 主キー |
| `file_path` | 保存された JPEG の絶対パス |
| `timestamp` | `YYYY-MM-DD HH:MM:SS.SSS` 形式の保存時刻 |
| `status` | 保存成功なら `1`、失敗なら `0` |

## 6. 補足

- `auto` は GStreamer を優先し、失敗時は OpenCV にフォールバックします。
- `capture_backend=gstreamer` を使う場合、OpenCV 側が GStreamer 対応ビルドである必要があります。
- スナップショット保存先と DB は、指定のパスが無ければ自動生成されます。