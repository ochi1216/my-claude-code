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
- `weekly_pdf_diff_20260729_01.py`: CLIエントリポイント。現状はWeekly区切り解析
  （`*_weekly_index.json` の出力）のみ行う。差分抽出・青太字描画はまだ実行できない。
- `run_weekly_pdf_diff.bat`: Windows用の起動バッチ（後述）。

## セットアップ

```bash
pip install -r requirements.txt
```

## 実行方法

### コマンドラインから直接

```bash
python weekly_pdf_diff_20260729_01.py <PDFファイル> [--output-dir output] [--expected-count 16]
```

### Windowsのバッチファイルから（推奨）

`run_weekly_pdf_diff.bat` をダブルクリックするか、PDFファイルをこのバッチファイルへ
ドラッグ&ドロップすると実行される。

```
run_weekly_pdf_diff.bat "C:\path\to\Hello_Ochi_San.pdf"
```

このバッチファイルは、同じフォルダ内にある `weekly_pdf_diff_yyyymmdd_NN.py` の中から
**ファイル名（日付・連番）が最も新しいもの**を自動的に選んで実行する。
今後バージョンアップしたファイル（例: `weekly_pdf_diff_20260805_01.py`）を
このフォルダに追加するだけで、バッチファイル自体は変更不要で最新版が起動される
（開発ルールの「旧バージョンを残したまま新バージョンを追加する」運用にそのまま対応）。

**文字化けについて**: `run_weekly_pdf_diff.bat` はShift_JIS(CP932)・BOMなしで
保存している。日本語版Windowsのコマンドプロンプトは既定でCP932のため、これで
文字化けしない。エディタで開いて保存し直す場合は、文字コードを「Shift-JIS」
（BOMなし）のまま保存すること。UTF-8で保存し直すと日本語部分が文字化けする。

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
