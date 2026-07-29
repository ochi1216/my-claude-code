# weekly_pdf_diff

Weekly Report PDF（OneNote由来、複数のWeeklyメールを集約したもの）を解析し、
各Weeklyを直前の日付のWeeklyと比較して、追加・修正された文言を青太字にした
別名PDFを生成するツール。

詳細な設計・調査結果は [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) を参照。

## 現在の状態（S01時点）

Phase 1（PDF読み込み・Weekly境界検出）のみ実装済み。差分抽出・青太字描画・
レポート出力（Phase 2〜5）は未実装。

- `pdf_reader.py`: PyMuPDFの薄いラッパー。ページ内の行を `(page, y0, y1, text, bold)`
  として抽出する（視覚的なY順にソート済み）。
- `weekly_splitter.py`: `From:`/`Sent:`/`Subject: Weekly Report` の並びからWeekly境界を
  `(page, y座標)` で検出し、日付を優先順位（Sent:ヘッダー → OneNote印字日時）で解決する。

## セットアップ

```bash
pip install -r requirements.txt
```

## テスト

```bash
cd weekly_pdf_diff
python -m pytest tests/ -v
```

テストは全て合成（人工生成）PDFを使用する。実データPDFは機密情報を含むため
リポジトリには含めない。

## 既知の未確定事項

- 基準日（`baseline_date`）を2026-04-17固定とするか、実データの最古Weekly
  （2026-04-10）を含めるかは越智さんの最終確認待ち（`docs/NEXT_TASK.md`参照）。
