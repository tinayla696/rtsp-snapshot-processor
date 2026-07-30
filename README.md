# [App Name] Application Repository

App単体運用の場合は、.github/workflows/notify_portal.yml を削除してください。

## 🛠 開発ルール (Docs as Code)

### ブランチ命名規則

| Prefix | 用途 | SemVer影響 | 例 |
| :--- | :--- | :--- | :--- |
| `main` | メインブランチ | なし | `main` |
| `develop` | ステージングブランチ | なし | `develop` |
| `feature/` | 新機能追加 | Minor | `feature/add-login-function` |
| `bugfix/` | バグ修正 | Patch | `bugfix/fix-crash-on-startup` |
| `hotfix/` | 緊急修正 | Patch | `hotfix/fix-security-vulnerability` |
| `release/` | リリース準備 | Patch/Minor | `release/v1.2.0-prep` |
| `docs/` | ドキュメント更新のみ | Patch | `docs/update-api-docs` |
| `chore/` | その他メンテナンス | Patch | `chore/update-dependencies` |

### コミットメッセージ規約

- `type(scope): subject` 例: `feat(api): add login`
- type例: feat, fix, docs, chore, refactor, test, ci
- scopeは任意、subjectは簡潔に

### 運用のポイント

- **Docs as Code**: コード修正時はdocs/も必ず更新
- **main直Push禁止**: PR経由でマージ
- **CI/CD必須**: GitHub Actions等で自動テスト・デプロイ
- **README.md整備**: QuickStart・開発手順・依存関係を明記
- **テンプレート活用**: PRテンプレート・Issueテンプレートを用意
