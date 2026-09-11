# weekly_pdf_diff

Weekly Report PDF（OneNote由来、複数のWeeklyメールを集約したもの）を解析し、
各Weeklyを直前の日付のWeeklyと比較して、追加・修正された文言を青太字にした
別名PDFを生成するツール。

詳細な設計・調査結果は [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) を参照。

## 現在の状態（S01時点）

Phase 1〜5すべて実装済み。基準日以降の各Weeklyを直前のWeeklyと比較し、
追加・修正された文言を青太字化した別名PDF・差分レポート（CSV/HTML）・
Weekly一覧JSONを出力するフルパイプラインが動作する。実PDF（89ページ、
14 Weeklyペア）でのエンドツーエンド動作を確認済み（詳細は
[`CHANGELOG.md`](CHANGELOG.md) 参照。実PDF自体はリポジトリにコミットしていない）。

- `pdf_reader.py`: PyMuPDFの薄いラッパー。ページ内の行・単語を抽出する
  （視覚的なY順にソート済み。行の代表フォントサイズは文字数最多spanから採用）。
- `weekly_splitter.py`: Weekly境界を `(page, y座標)` で検出し、日付を優先順位
  （Sent:ヘッダー → OneNote印字日時）で解決する。
- `normalize.py` / `sectionize.py` / `diff_engine.py` / `render.py` / `report.py`:
  Phase 2〜5（正規化・セクション階層化・対応付けと単語差分・青太字描画・
  差分レポート出力）。詳細は [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) 参照。
- `weekly_pdf_diff_20260729_01.py` / `_02.py`: 旧バージョン（開発ルールにより
  削除せず保持。Phase 1のみ、GUI選択画面追加、の各段階のスナップショット）。
- `weekly_pdf_diff_20260729_03.py`: 現行版CLIエントリポイント。フルパイプライン。
  PDFパスを省略するとファイル選択画面（tkinter標準ライブラリ）が開く。
- `run_weekly_pdf_diff.bat`: Windows用の起動バッチ（後述）。

## セットアップ

```bash
pip install -r requirements.txt
```

## 実行方法

### Windowsのバッチファイルから（推奨）

`run_weekly_pdf_diff.bat` を**ダブルクリック**すると、Windowsのファイル選択画面
（エクスプローラー風の「開く」ダイアログ）が表示されるので、そこでPDFを選ぶ。
PDFファイルをこのバッチファイルへドラッグ&ドロップして起動することもできる。

```
run_weekly_pdf_diff.bat "C:\path\to\Hello_Ochi_San.pdf"
```

このバッチファイルは、同じフォルダ内にある `weekly_pdf_diff_yyyymmdd_NN.py` の中から
**ファイル名（日付・連番）が最も新しいもの**を自動的に選んで実行する。
今後バージョンアップしたファイル（例: `weekly_pdf_diff_20260805_01.py`）を
このフォルダに追加するだけで、バッチファイル自体は変更不要で最新版が起動される
（開発ルールの「旧バージョンを残したまま新バージョンを追加する」運用にそのまま対応）。

出力先フォルダは、選んだPDFと同じフォルダの `output/` サブフォルダになる
（`--output-dir` で変更可能）。

### コマンドラインから直接

```bash
python weekly_pdf_diff_20260729_03.py [PDFファイル] [--output-dir DIR] \
    [--expected-count 16] [--baseline 2026-04-17]
```

PDFファイルを省略した場合も同様にファイル選択画面が開く。`--baseline` の週は
変更されない（それより後の各週が直前の週と比較される）。

### 出力ファイル

- `<PDF名>_diff_blue_bold.pdf`: 追加・修正箇所を青太字化した別名PDF（元PDFは変更しない）
- `<PDF名>_diff_report.csv` / `.html`: 差分レポート（current_week/previous_week/
  project/section/change_type/previous_text/current_text/changed_words/page/confidence）
- `<PDF名>_weekly_index.json`: 検出したWeeklyの日付・ページ一覧

**注意**: ファイル選択画面はPython標準のtkinterを使用している。python.orgの
公式Windowsインストーラには標準で含まれるが、一部の簡易インストール（Microsoft
Storeアプリ版など）では含まれない場合がある。その場合はエラーメッセージが表示
されるので、ドラッグ&ドロップまたはコマンドライン引数でPDFパスを渡すこと。

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

## 既知の未確定事項・限界

- 基準日（`baseline_date`）を2026-04-17固定とするか、実データの最古Weekly
  （2026-04-10）を含めるかは越智さんの最終確認待ち（`docs/NEXT_TASK.md`参照）。
- STR/Reliability/Others配下にある罫線なしの複数列レイアウト（進捗ステータス表
  等）は、行・列として正確に再構成できていない（セル単位の断片として扱われる）。
  誤って別の断片同士を混同しないよう安全側には倒しているが、この領域の差分
  精度は本文の箇条書き・番号付き項目より低い（詳細はIMPLEMENTATION_PLAN.md 1章）。
- 太字化の際、実データにある非常に狭い単語間隔（2〜3pt程度）を考慮して隙間を
  確保しているが、極端に長い単語や極端に狭い間隔ではフォントサイズの縮小上限
  （既定10%）内で完全な回避を保証できない場合がある。
