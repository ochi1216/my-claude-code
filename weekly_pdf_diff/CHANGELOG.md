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

### Phase 2〜5実装（差分抽出・青太字描画・レポート出力・パイプライン統合）

- `models.py`（TextUnit/DiffResult）, `normalize.py`（比較用テキスト正規化）,
  `sectionize.py`（セクション階層化）, `diff_engine.py`（対応付け・単語単位差分）,
  `render.py`（青太字描画）, `report.py`（CSV/HTML差分レポート）を追加
- `weekly_pdf_diff_20260729_03.py` (revision 03) を追加。基準日以降の各Weeklyを
  直前のWeeklyと比較し、青太字化した別名PDF・差分レポート・Weekly一覧JSONを
  出力するフルパイプライン。`_01`/`_02`は開発ルールにより保持
- 単体テスト22件を追加（`test_sectionize.py`の列crossing修正含む,
  `test_diff_engine.py`, `test_render.py`, `test_report.py`,
  `test_pdf_reader.py`, `test_weekly_line_range.py`）、統合テスト
  `test_end_to_end.py`（合成3Weekly PDFでパイプライン全体を検証）を追加
- **実PDFでのエンドツーエンド検証により、以下3件の重大な不具合を発見・修正**
  （合成テストだけでは検出できず、実データでの動作確認が必須だったもの）:
  1. `sectionize.py`: 罫線のない別列（狭い列に折り返された見出し）のテキストが
     Y座標だけの継続行判定でSTR項目等に誤って混入する不具合。
     `pdf_reader.Line`に`x0`を追加し、継続行はX座標が近い場合のみ結合するよう修正
  2. `weekly_pdf_diff_20260729_03.py`の`_weekly_line_range()`: PDFは新しい
     Weeklyから順に綴じられている（ページ番号が大きいほど古い週）ため、日付昇順
     リストで「次の要素」を終端に使うとページ範囲が逆転し、比較対象の行が
     常に空になっていた（結果として全ての差分が"added"としてしか検出されず、
     "unchanged"/"modified"/"deleted"が一切出ない状態になっていた）。
     終端には「1つ古い要素」を使うよう修正
  3. `pdf_reader.py`の`font_size`抽出: 自動採番（"1."等）がYuGothic-Regular・
     12ptで、本文がArial・11.04ptで描画されている実データがあり、行の先頭span
     のサイズをそのまま使うと本文のフォントサイズを誤取得していた。太字化で
     単語の幅が大きく崩れ、実データのような狭い単語間隔（2〜3pt）を完全に
     食いつぶして隣の単語と接触して見える不具合につながった。行内で最も
     文字数の多いspanのサイズを採用するよう修正し、あわせて太字描画時に
     次の単語との間へ最低限の隙間（`WORD_GAP_MARGIN`）を残すよう`render.py`
     を修正
- 上記3件の修正後、実PDF（89ページ、14 Weeklyペア）に対してエンドツーエンドで
  実行し、正常終了・89ページ維持・change_type内訳（moved/added/deleted/modified
  が妥当な比率で分布）・複数ページの目視確認（PNG書き出し）で問題ないことを確認
  （実PDF自体・出力結果はリポジトリにコミットしていない）
