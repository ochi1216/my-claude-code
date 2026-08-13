# CHANGELOG — po_database_organizer

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

## [20260713_01] - 2026-07-13

**追加ファイル:** `po_database_organizer_20260713_01.py`, `config.example.json`, `requirements.txt`, `README.md`

- SharePoint上のPO（パーチャスオーダー）関連書類をスキャンし、「Project × Vendor × PO番号」でカタログ化（Excel/JSON出力）するツールの初版
- R19 Site Organizer（Graph API + MSAL Device Code Flow）の技術基盤を転用
- Phase 1: PO番号命名規則のみ自動認識し、無理な自動分類はしない方針
