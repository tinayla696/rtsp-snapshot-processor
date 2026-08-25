# テスト

## 実行方法

```bash
# ローカル（仮想環境をアクティベート済みの状態）
pytest

# 詳細出力
pytest -v

# Docker 環境で実行（依存サービスなし）
docker compose run --rm --no-deps app pytest -q
```

実機相当の確認手順は[デプロイと運用](deployment.md)を参照してください。外部端末からWin11またはDockerホストのLAN IP:5004へH.264 RTP/UDPを送信し、JPEG、SQLite、外部API通知を確認します。

## テスト構造

```text
tests/
└── test_stream_processor.py
```

### テストカテゴリ

| テスト名 | 検証内容 |
| --- | --- |
| `test_snapshot_repository_creates_db_and_persists_absolute_path` | DB が自動生成され、絶対パスとタイムスタンプが正しく保存される |
| `test_snapshot_repository_resets_database_on_startup` | 2回目の起動時に DB がリセットされ、レコードが空になる |
| `test_snapshot_service_writes_jpeg_and_registers_record` | JPEG 書き込みが呼ばれ、`status=True` で DB に登録される |
| `test_snapshot_service_registers_false_status_when_write_fails` | `cv2.imwrite` が `False` を返したとき `status=False` で DB に登録される |
| `test_snapshot_service_notifies_external_api_after_success` | 保存成功時に外部 API へ通知が送られる |

## モック戦略

OpenCV の実処理（`cv2.imwrite`）と `datetime.now()` は `monkeypatch` でモックし、
保存ロジックと DB 登録の振る舞いのみを検証します。

```python
monkeypatch.setattr(sp.cv2, "imwrite", fake_imwrite)
monkeypatch.setattr(sp, "datetime", FixedDatetime)
```

`FrameReceiver` の実際のストリーム受信は結合テストの対象であり、ユニットテストでは `object()` または `DummyRepository` を注入して分離します。

## テスト用ヘルパークラス

| クラス | 役割 |
| --- | --- |
| `DummyRepository` | `SnapshotRepository` のスタブ。記録をリストに保持 |
| `FixedDatetime` | `datetime.now()` を固定値に差し替えるクラス |
| `FakeCapture` | `cv2.VideoCapture` の呼び出しを記録するスタブ |

## カバレッジ方針

- `SnapshotRepository`: DB 自動生成、リセット、レコード登録（成功・失敗）
- `SnapshotService`: JPEG 保存、DB 登録（成功・失敗）、API 通知
- `FrameReceiver` / `StreamProcessorApplication`: 実ストリームを要するため、Docker Compose 結合テストで確認

## CI

GitHub Actions での自動テストを推奨します。`main` / `develop` への push・PR 時に以下を実行します。

```yaml
- name: Run tests
  run: |
    pip install -r requirements.txt
    pytest -q
```

GStreamer の有無に関わらず、`capture_backend=rtp`（FFmpeg）でテストが通ることを確認してください。