# 使用方法

## インストール

```bash
pip install -r requirements.txt
```

## 実行

```bash
python src/stream_processor.py --config stream_processor.toml
```

`stream_processor.toml.example` をコピーして `stream_processor.toml` を作成できます。
CLI 引数を追加すると、その値が TOML 設定を上書きします。

## 主なオプション

- `--rtsp-url`: 受信する RTSP/RTP ストリーム URL
- `--snapshot-interval`: スナップショット保存周期（秒）
- `--save-dir`: 画像保存先ディレクトリ
- `--db-path`: SQLite DB ファイルパス
- `--config`: TOML 設定ファイルのパス
- `--capture-backend`: `auto` / `gstreamer` / `opencv`
- `--gstreamer-pipeline-template`: GStreamer パイプラインテンプレート
- `--jpeg-quality`: JPEG 品質 0-100
- `--reconnect-delay`: 再接続までの待機秒数

`auto` は GStreamer を優先し、失敗時に OpenCV へフォールバックします。

## DB テーブル

`snapshots` テーブルには、以下が記録されます。

| カラム名 | 内容 |
| --- | --- |
| `id` | 主キー |
| `file_path` | 保存された JPEG の絶対パス |
| `timestamp` | `YYYY-MM-DD HH:MM:SS.SSS` 形式の保存時刻 |