# rtsp-snapshot-processor

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![OpenCV](https://img.shields.io/badge/OpenCV-Image%20Processing-5C3EE8?logo=opencv&logoColor=white)](https://opencv.org/)
[![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![pytest](https://img.shields.io/badge/pytest-Test%20Suite-0A9EDC?logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![MkDocs](https://img.shields.io/badge/MkDocs-Documentation-526CFE?logo=materialformkdocs&logoColor=white)](https://www.mkdocs.org/)
[![GStreamer](https://img.shields.io/badge/GStreamer-Streaming-FF7F00?logo=gstreamer&logoColor=white)](https://gstreamer.freedesktop.org/)

RTP/RTSPビデオストリームを低遅延で受信し、指定した周期でスナップショット（JPEG）を保存し、ファイルパスとタイムスタンプをSQLiteへ記録するPythonアプリケーションです。

## 特徴
- **マルチスレッド設計**: 受信スレッドと保存処理を分離し、バッファ遅延を抑えます。
- **拡張しやすいクラス設計**: 将来的なGPUデコードやAI推論を載せやすい構成です。
- **自動初期化**: スナップショット保存先とSQLite DBは初回実行時に自動生成されます。
- **GStreamer 優先**: 受信バックエンドは GStreamer を優先し、利用できない場合は OpenCV へフォールバックします。

## 要件

- Python 3.10 以上
- OpenCV
- GStreamer 対応の OpenCV ビルドを推奨
- pytest

## セットアップ

```bash
pip install -r requirements.txt
```

## 設定ファイル

`stream_processor.toml.example` を `stream_processor.toml` にコピーして編集できます。
`stream_processor.toml` が存在する場合、起動時に自動で読み込まれます。

## 実行例

```bash
python src/stream_processor.py --config stream_processor.toml
```

CLI 引数は config ファイルの値を上書きします。

## 出力

- 画像は指定した保存先に JPEG 形式で保存されます。
- SQLite DB には保存先の絶対パスと `YYYY-MM-DD HH:MM:SS.SSS` 形式のタイムスタンプが記録されます。

## ドキュメント

- MkDocs: [docs/index.md](docs/index.md)
- 使用方法: [docs/usage.md](docs/usage.md)
- テスト: [docs/testing.md](docs/testing.md)

## ディレクトリ構成

```text
rtsp-snapshot-processor/
├── docs/
├── src/
│   └── stream_processor.py
├── tests/
├── requirements.txt
└── README.md
```

## 変更履歴の方針

- 実装の詳細は docs 配下に集約します。
- README はクイックスタートと参照先の案内に絞ります。
