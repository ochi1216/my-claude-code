# SharePoint Automation Manager

SharePoint上のExcel KPIシート（Caracalシート）を定期的に自動取得し、Outlook通知
まで自動化するプロジェクト。Microsoft Graph APIの `workbook/usedRange` を用いて
Excelアプリを開かずにセル値を直接取得し、GitHub Actionsのスケジュール実行
（cron）で駆動する構成を予定している。

## 現在の状態（2026-09-17時点）

- **Phase1（設計提案）改訂版：承認済み**
- **Phase0（ガバナンス確認：IT/セキュリティ部門への事前相談）：未実施
  ★最優先の未完了事項**
- Phase2（Architecture Audit）：進行中（6項目中4項目確定。残りはCaracalシート
  の実データ確認のみ）
- Phase3（実装）：**Phase0完了・越智さんの明示的承認まで着手しない**

このフォルダには現時点でコードは存在しない（設計・引継ぎ資料のみ）。

## ドキュメント

- [`CLAUDE.md`](CLAUDE.md) … このプロジェクト専用の開発ワークフロー規約（3フェーズ厳守）
- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) … 現状・未解決事項
- [`docs/NEXT_TASK.md`](docs/NEXT_TASK.md) … 次にやるべきタスクと受け入れ基準
- [`docs/SESSION_HISTORY.md`](docs/SESSION_HISTORY.md) … 意思決定履歴（ADR形式）

`CHANGELOG.md` / `requirements.txt` / `config.example.json` はPhase3（実装）
着手時に作成する。
