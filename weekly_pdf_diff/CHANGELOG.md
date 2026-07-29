# CHANGELOG

## 2026-07-29 (S01)

- IMPLEMENTATION_PLAN.md 作成（引継ぎ資料の構想を実PDF調査結果に基づき磨き直し）
- Phase 1プロトタイプ実装: `pdf_reader.py`（行抽出）, `weekly_splitter.py`
  （Weekly境界検出・日付解決）
- 合成PDFによる単体テスト3件を追加、全てパス
- 実PDF（89ページ）に対する検証で、`get_text("dict")`のブロック順が視覚的な
  Y順と一致しないケースを発見し、`pdf_reader.py`でのソート処理により対処
