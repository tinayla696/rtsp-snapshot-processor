# rtsp-snapshot-processor

RTP/RTSP 配信を受信して、一定周期で最新フレームを JPEG として保存し、保存履歴を SQLite に記録するアプリケーションです。

## できること

- 低遅延を意識した受信スレッド分離
- GStreamer 優先の受信バックエンドと OpenCV フォールバック
- 周期スナップショット保存
- SQLite への絶対パスとタイムスタンプ登録
- 初回実行時の保存先ディレクトリと DB の自動生成
- TOML 設定ファイルによる起動設定

## 参照ページ

- [アーキテクチャ](architecture.md)
- [外部API仕様](api-spec.md)
- [AI ガイドライン](ai_guidelines.md)
- [使用方法](usage.md)
- [テスト](testing.md)

## 最小構成

```text
src/stream_processor.py
requirements.txt
tests/
```