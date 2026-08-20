# テスト

## 実行方法

```bash
pytest
```

Docker環境で実行する場合:

```bash
docker compose run --rm --no-deps app pytest -q
```

実機相当の確認手順は[デプロイと運用](deployment.md)を参照してください。外部端末からWin11またはDockerホストのLAN IP:5004へH.264 RTP/UDPを送信し、JPEG、SQLite、外部API通知を確認します。

## 追加したテスト

- SQLite DB が自動生成されること
- スナップショット保存時に絶対パスとタイムスタンプが記録されること
- アプリケーション起動時にSQLite DBがリセットされること
- JPEG 書き込み処理が呼ばれること

## 方針

OpenCV の実処理はモックし、保存ロジックと DB 登録の振る舞いを中心に検証します。