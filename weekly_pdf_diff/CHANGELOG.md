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
