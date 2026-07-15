# CHANGELOG — shareflex_dashboard

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

## [20260713_01] - 2026-07-13

**追加ファイル:** `shareflex_dashboard_20260713_01.py`, `requirements.txt`, `README.md`

- Nexus Document Management System（SharePoint / Shareflex）からエクスポートしたドキュメント一覧(Excel)を読み込み、組織軸・業務プロセス軸で集計した静的HTMLダッシュボードを生成するツールの初版
- Graph API等の自動取得が社内ポリシーでブロックされる可能性があるため、手動エクスポート→ローカル集計のオフライン構成
