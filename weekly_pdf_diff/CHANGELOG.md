# CHANGELOG

## 2026-07-29 (S01)

- IMPLEMENTATION_PLAN.md 作成（引継ぎ資料の構想を実PDF調査結果に基づき磨き直し）
- Phase 1プロトタイプ実装: `pdf_reader.py`（行抽出）, `weekly_splitter.py`
  （Weekly境界検出・日付解決）
- 合成PDFによる単体テスト3件を追加、全てパス
- 実PDF（89ページ）に対する検証で、`get_text("dict")`のブロック順が視覚的な
  Y順と一致しないケースを発見し、`pdf_reader.py`でのソート処理により対処
- `weekly_pdf_diff_20260729_01.py` (CLIエントリポイント, revision 01) を追加。
  現状はWeekly区切り解析（`*_weekly_index.json`出力）のみ実装
- `run_weekly_pdf_diff.bat` を追加（フォルダ内の最新の
  `weekly_pdf_diff_yyyymmdd_NN.py` を自動選択して起動。Shift_JIS(CP932)保存で
  日本語版Windowsでの文字化けを回避）
- `run_weekly_pdf_diff.bat` 修正: PDF未指定でダブルクリックした場合、使い方を
  表示した後もPythonを実行してargparseのエラーが二重に出ていた不具合を修正。
  使い方表示後は `pause` して終了するようにした
- `weekly_pdf_diff_20260729_02.py` (revision 02) を追加。`_01`は開発ルールにより
  保持したまま残す。PDFパスを省略した場合、tkinter標準ライブラリによる
  ファイル選択画面（Windowsのエクスプローラー風「開く」ダイアログ）を表示する
  ように変更。あわせて `--output-dir` の既定値を、選択したPDFと同じフォルダの
  `output/` に変更（従来はカレントディレクトリ基準の `output/` 固定だった）
- `run_weekly_pdf_diff.bat` 修正: PDF未指定時に処理を打ち切るのをやめ、
  「ファイル選択画面を開きます」と案内した上でそのままPythonを起動するように変更
  （GUI選択画面はPython側の`_02`で処理する）
- `tests/test_cli_entry.py` を追加。CLIエントリポイントはファイル名で最新版を
  動的に読み込んでテストする（バージョンアップのたびにテストを書き換えずに済む
  ようにするため）。GUI選択画面は実際には開かず、モックで代替してテスト
