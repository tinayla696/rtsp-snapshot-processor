# デプロイと運用

## 運用方針

本番環境は Windows 11 上のネイティブアプリとして運用します。Docker Compose は、テストAPIを含む結合テストと、本番相当のRTP受信経路を再現するための検証環境として使用します。

| 環境 | 実行方式 | API通知先 | RTP受信 |
| --- | --- | --- | --- |
| 本番 | Windows 11 + Python + Windows版FFmpeg | DB管理サーバーの外部API | Win11ホストのUDP `5004` |
| テスト | Docker Compose | Compose内の `test-api` または指定したテストAPI | appコンテナのUDP `5004` |

## 本番環境: Windows 11

### 必要なソフトウェア

- Windows 11
- Python 3.10以上
- Windows版FFmpeg。`ffmpeg.exe` をPATHへ追加
- 外部APIへ到達できるネットワーク
- RTP送信端末と同一LANへ接続できるネットワーク

確認コマンド:

```powershell
python --version
ffmpeg -version
```

### インストール

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 本番設定

`stream_processor.toml` を作成し、外部API URLとWindows上の保存先を設定します。

```toml
rtsp_url = ""
snapshot_interval_sec = 5.0
save_dir = "C:/rtsp-snapshot-processor/data/snapshots"
db_path = "C:/rtsp-snapshot-processor/data/snapshot_records.db"
capture_backend = "rtp"
jpeg_quality = 90
reconnect_delay_sec = 1.0
notification_url = "https://db.example.example/api/snapshots/notify"
rtp_port = 5004
rtp_payload_type = 96
rtp_clock_rate = 90000
rtp_width = 1280
rtp_height = 720
```

`notification_url` は、テスト用の `http://test-api:8000/notify` ではなく、DB管理サーバーが提供する外部API URLへ変更してください。

### Firewall

管理者権限のPowerShellで、RTP受信ポートを許可します。

```powershell
New-NetFirewallRule `
  -DisplayName "RTSP Snapshot RTP 5004" `
  -Direction Inbound `
  -Protocol UDP `
  -LocalPort 5004 `
  -Action Allow
```

外部端末の送信先は、Win11実機のLAN IPとUDP `5004` です。DockerのコンテナIPや `127.0.0.1` は指定しません。

```text
RTP送信端末 -- H.264 RTP/UDP --> Win11ホストのLAN IP:5004
Win11ホスト -- POST /notify --> DB管理サーバーAPI
```

### 起動と停止

```powershell
.\.venv\Scripts\Activate.ps1
python src\stream_processor.py --config stream_processor.toml
```

停止は `Ctrl+C` を使用します。本番で常時稼働させる場合は、WinSWやNSSMなどでWindowsサービスとして登録し、OS起動時の自動起動と異常終了時の再起動を設定してください。

### 起動時のSQLiteリセット

現在の実装では、アプリケーション起動時に `db_path` のSQLite本体とWAL/ジャーナル関連ファイルを削除し、空のDBを再作成します。前回起動分の履歴は保持されません。

本番でスナップショット履歴を保持する場合は、この仕様を変更してから運用を開始してください。DBファイルのバックアップやローテーションを行わずに再起動すると、履歴が失われます。

## テスト環境: Docker Compose

Dockerホストで実行します。

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

Composeの既定値は次の通りです。

- RTP受信: UDP `5004`
- テストAPI: `http://127.0.0.1:8000`
- 通知先: `http://test-api:8000/notify`
- 保存先: `docker-data/snapshots/`
- SQLite: `docker-data/snapshot_records.db`
- 通知ログ: `docker-data/test-api/notifications.log`

実機または合成RTP送信端末から送信する場合、送信先はDockerホストのLAN IP:5004です。

テスト終了:

```bash
docker compose down
```

テストデータも削除する場合:

```bash
docker compose down
rm -rf docker-data
```

## 外部API

スナップショット保存成功時に、次のJSONを `POST /notify` で送信します。

```json
{
  "file_path": "C:/rtsp-snapshot-processor/data/snapshots/snapshot_20260820_123456_789.jpg",
  "timestamp": "2026-08-20 12:34:56.789"
}
```

詳細な契約は [外部API仕様](api-spec.md) を参照してください。

現行実装では認証、通知失敗時の自動再送、重複排除IDは未実装です。本番APIへ接続する場合は、HTTPS、送信元制限、APIキー等の認証方式をDB管理サーバー担当者と合意してください。

## 本番開始前チェック

- [ ] Windows版FFmpegを `ffmpeg -version` で確認した
- [ ] Python仮想環境と依存関係を準備した
- [ ] Win11ホストのLAN IPをRTP送信端末へ設定した
- [ ] UDP `5004`をWindows Firewallで許可した
- [ ] `notification_url` を外部API URLへ変更した
- [ ] 外部APIの応答がHTTP `200 OK` になることを確認した
- [ ] SQLite起動時リセットの仕様を了承した、または履歴保持対応を実装した
- [ ] JPEG、SQLite、API通知の保存先と監視方法を決めた
- [ ] Windowsサービスの自動起動・再起動を設定した
