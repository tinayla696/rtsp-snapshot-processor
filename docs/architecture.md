# アーキテクチャ

## 対象とする実行環境

本システムは、Windows 11 上の高性能エッジ端末での長期稼働を前提に設計しています。
特に、Intel Core Ultra 9 と NVIDIA GeForce RTX 5080 のような余力の大きい環境では、
CPU/GPU の将来拡張を阻害しないように、受信処理と保存処理の責務を分離しています。

本番はWindows 11上でPythonアプリとWindows版FFmpegを直接実行します。Linux ネイティブおよび Docker Compose はテスト・検証環境として同じ RTP 受信・スナップショット・API 通知経路を再現します。

重要なのは「単純に高速であること」ではなく、「ストリーム断・ディスク障害・設定ミスが起きても
処理全体を落とさずに復旧しやすいこと」です。

## 設計方針

- 受信と保存を分離し、映像受信の詰まりが保存系に波及しにくい構成にする。
- SQLite の失敗をアプリ全体のクラッシュ要因にしない。
- 将来の GPU デコードや AI 推論を追加しても、既存の責務境界を壊さない。
- Python 3.10 互換性を維持し、実運用環境の差分を吸収しやすくする。

## クラス構成

```mermaid
classDiagram
    class AppConfig {
        +rtsp_url: str
        +snapshot_interval_sec: float
        +save_dir: Path
        +db_path: Path
        +capture_backend: str
        +gstreamer_pipeline_template: str
        +jpeg_quality: int
        +reconnect_delay_sec: float
        +notification_url: str
        +rtp_port: int
        +rtp_width: int
        +rtp_height: int
    }
    class FrameReceiver {
        -_latest_frame
        -_lock: Lock
        -_stop_event: Event
        -_thread: Thread
        +start()
        +stop()
        +get_latest_frame()
        -_run()
        -_open_capture() bool
        -_open_rtp_capture() bool
        -_build_capture_targets() list
    }
    class SnapshotRepository {
        -_db_path: Path
        -_connection: Connection
        -_lock: Lock
        +add_snapshot_record()
        +close()
        -_initialize()
        -_reset_database()
        -_ensure_status_column()
    }
    class SnapshotService {
        -_receiver: FrameReceiver
        -_repository: SnapshotRepository
        -_config: AppConfig
        +run()
        -_save_snapshot() bool
        -_notify()
    }
    class StreamProcessorApplication {
        -_config: AppConfig
        -_stop_event: Event
        +run()
        -_setup_signal_handlers()
        -_shutdown()
    }

    StreamProcessorApplication --> AppConfig
    StreamProcessorApplication --> FrameReceiver
    StreamProcessorApplication --> SnapshotRepository
    StreamProcessorApplication --> SnapshotService
    SnapshotService --> FrameReceiver
    SnapshotService --> SnapshotRepository
    SnapshotService --> AppConfig
```

### `AppConfig`

起動設定をまとめる不変データクラス（`frozen=True`）です。`rtsp_url`、保存先、DB パス、スナップショット周期、`capture_backend`、GStreamer パイプラインテンプレートなど、実行時の制約を1か所に集約します。TOML ファイルと CLI 引数からビルドされ、以降は読み取り専用として扱います。

### `SnapshotRepository`

SQLite の接続と `snapshots` テーブルの作成・更新を担当します。`status` 列を含めた記録を保存し、初回起動時に DB ファイルと親ディレクトリを自動生成します。アプリケーション起動時には既存のDB本体とWAL/ジャーナル関連ファイルを削除して、DBを空の状態から初期化します。DB 接続にはロックを掛け、書き込みとクローズの競合を防ぎます。

### `FrameReceiver`

映像受信専用のスレッドを持ち、最新フレームだけをメモリ上に保持します。受信バックエンドの選択ロジックに従い、FFmpeg subprocess / GStreamer / OpenCV を使い分けます。ここでフレームを溜め込まないのは、遅延増大を防ぐためです。

### `SnapshotService`

メイン側の周期処理として、最新フレームを JPEG に保存し、その結果を SQLite に書き込みます。保存失敗時は `status=False` として DB に残し、成功時は `status=True` を記録します。この設計により、「画像は失敗したが、失敗ログは残る」という運用が可能になります。保存成功時のみ外部 API へ通知します。

### `StreamProcessorApplication`

起動、シグナル処理、停止、後始末を束ねるオーケストレータです。`Ctrl+C` と `SIGTERM` を受けて停止イベントを立て、受信スレッドと DB 接続を順に解放します。

## 処理フロー

```mermaid
flowchart TD
    START([起動]) --> CFG[AppConfig 構築\nTOML + CLI 引数]
    CFG --> REPO[SnapshotRepository 初期化\nDB リセット・テーブル作成]
    REPO --> RECV[FrameReceiver.start\n受信スレッド開始]
    RECV --> LOOP{停止イベント?}
    LOOP -->|No| FRAME[FrameReceiver\n最新フレーム取得]
    FRAME --> SAVE[cv2.imwrite JPEG]
    SAVE -->|成功| DBOK[DB: status=1\nINSERT]
    SAVE -->|失敗| DBNG[DB: status=0\nINSERT]
    DBOK --> NOTIFY[POST /notify]
    NOTIFY --> WAIT[snapshot_interval_sec 待機]
    DBNG --> WAIT
    WAIT --> LOOP
    LOOP -->|Yes| STOP[FrameReceiver.stop\nDB.close]
    STOP --> END([終了])

    subgraph "受信スレッド（並列）"
        RT1[キャプチャ開始] --> RT2{フレーム取得}
        RT2 -->|成功| RT3[最新フレームを上書き]
        RT3 --> RT2
        RT2 -->|失敗/切断| RT4[reconnect_delay_sec 待機]
        RT4 --> RT1
    end
```

## 受信バックエンド選択ロジック

`capture_backend` 設定値により、以下の順序でバックエンドが選択されます。

```mermaid
flowchart TD
    B[capture_backend 設定値] --> BV{値は?}
    BV -->|rtp| RTP["FFmpeg subprocess\nH.264 RTP/UDP → raw BGR24\nUDP ポート直接受信"]
    BV -->|gstreamer| GS["cv2.VideoCapture + CAP_GSTREAMER\nGStreamer パイプライン"]
    BV -->|opencv| OCV["cv2.VideoCapture + CAP_FFMPEG\nOpenCV FFmpeg バックエンド"]
    BV -->|auto| AUTO{GStreamer 試行}
    AUTO -->|成功| GS
    AUTO -->|失敗| OCV
```

| バックエンド | 用途 | 前提 |
| --- | --- | --- |
| `rtp` | H.264 RTP/UDP 直接受信（本番推奨） | FFmpeg が PATH に存在すること |
| `gstreamer` | GStreamer パイプライン使用 | GStreamer 対応 OpenCV ビルド |
| `opencv` | OpenCV FFmpeg バックエンド | OpenCV FFmpeg サポート |
| `auto` | GStreamer 優先・OpenCV フォールバック | — |

## マルチスレッド構成の目的

- 受信側の遅延を保存側から切り離す。
- 保存失敗や DB ロックで受信スレッドを止めない。
- 最新フレームだけを採用し、古いフレームの滞留を防ぐ。

スレッド間共有状態の保護:

| 共有データ | 保護手段 |
| --- | --- |
| `FrameReceiver._latest_frame` | `threading.Lock` |
| `SnapshotRepository._connection` | `threading.Lock` |
| 停止フラグ | `threading.Event` |

## 耐障害性

- `SnapshotService.run()` は保存処理を `try-except` で囲み、例外が起きても次周期へ進みます。
- `SnapshotRepository` はロック付きで書き込み、同時クローズの競合を抑えます。
- 設定読み込み失敗は明確なエラーメッセージに変換し、原因を追跡しやすくします。
- `FrameReceiver` はストリーム切断時に `reconnect_delay_sec` 待機後に再接続を試みます。

## 将来の拡張ポイント

| 拡張 | 方法 |
| --- | --- |
| GPU デコード | `FrameReceiver._open_rtp_capture()` の FFmpeg コマンドに `-hwaccel cuda` 等を追加 |
| AI 推論 | `SnapshotService._save_snapshot()` で JPEG 保存前にフレームを処理 |
| 複数ストリーム | `FrameReceiver` と `SnapshotService` をペアで複数インスタンス化 |
| DB 履歴保持 | `SnapshotRepository._reset_database()` の削除処理を除去・ローテーション追加 |

## 制約

- `tomllib` は Python 3.11 以降ですが、このリポジトリは `tomli` フォールバックで Python 3.10 を支えます。
- GStreamer は環境依存です。OpenCV のビルドに GStreamer サポートが無ければ、`capture_backend=gstreamer` は使えません。Linux では distro 版の `python3-opencv` を使う必要があります。
- SQLite は高頻度の並列書き込み向きではありません。ここでは単一接続・単一書き込み経路に寄せています。
- 起動時に DB がリセットされるため、前回起動分のスナップショット履歴は保持されません。