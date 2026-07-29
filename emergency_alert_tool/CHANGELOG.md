# CHANGELOG — emergency_alert_tool

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

## [20260729_01] - 2026-07-29

**追加ファイル:** `emergency_alert_tool_20260729_01.py`, `config.example.json`, `requirements.txt`, `README.md`, `tests/test_emergency_alert_tool.py`

- 緊急地震速報（大分県・大阪府・東京都、震度5弱以上）を検知したら、緊急連絡網の
  スタッフ18名へ安否確認メールを自動送信するツールの初版。
- スタッフは「安否（無事/被災）」「場所（職場/自宅）」「出社可否（出社可能/出社不可能）」の
  3項目をクリックで回答するWebフォーム（`/respond/<token>`）を実装。
- 回答が送信されると、即座に上司3名へGraph API経由で通知する処理を実装。
- `/dashboard/<alert_id>` に、18名の回答状況を一覧できる簡易ダッシュボードを実装。
- Microsoft Graph API（app-only, client credentials フロー, MSAL）でのメール送信を実装
  （`po_database_organizer` のMSAL活用実績を踏襲）。
- 緊急地震速報フィードはP2P地震情報APIを想定したパーサ (`parse_p2pquake_eew`) を実装
  （実データスキーマは未検証、README参照）。
- pytestによる自動テスト16件を作成し、全件パスを確認（Graph API呼び出しはテスト用ダブルに置き換え）。
