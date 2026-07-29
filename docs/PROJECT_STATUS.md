# PROJECT_STATUS.md

対象プロジェクト: **PDF メール解析ツール開発**（`weekly_pdf_diff/`）
最終更新: S01（2026-07-29）

## Project Overview

Weekly Report メール（Nexperia社内、単一送信者からの継続的な週次報告）をOneNoteに
集約してエクスポートしたPDFを解析し、各Weeklyを**直前の日付のWeekly**と比較して、
今週追加・修正された文言のみを**青太字**に変更した別名PDFを生成するツール。

基準日（2026-04-17）以降の各Weeklyについて、直前週からの差分を可視化することが目的。
元PDFは変更せず、常に別名で出力する。OCRは使用しない（PDFは文字情報を保持している）。

## Repository Structure

このリポジトリ（`my-claude-code`）は越智さん個人の複数独立ツールのモノレポ。
本プロジェクトは新規フォルダ `weekly_pdf_diff/` として追加する（既存の
`rtocs_organizer/` 等と同じ、自己完結フォルダ構成の慣習に従う）。

```
my-claude-code/
├── CLAUDE.md                      # 本プロジェクトのセッション管理ルール
├── docs/
│   ├── PROJECT_STATUS.md          # 本ファイル
│   ├── SESSION_HISTORY.md
│   └── NEXT_TASK.md
├── weekly_pdf_diff/                # 本プロジェクト（新規）
│   ├── IMPLEMENTATION_PLAN.md
│   ├── README.md
│   ├── CHANGELOG.md
│   ├── requirements.txt
│   ├── weekly_pdf_diff_YYYYMMDD_NN.py   # CLIエントリポイント（既存リポジトリ命名規則）
│   ├── pdf_reader.py
│   ├── weekly_splitter.py
│   ├── text_normalizer.py
│   ├── diff_engine.py
│   ├── pdf_renderer.py
│   ├── report_writer.py
│   └── tests/
├── rtocs_organizer/ 他             # 既存の無関係な他プロジェクト（変更対象外）
```

## Current Functions

未実装（S01は調査・設計フェーズ）。S01で実施したのはPDF構造調査とPhase 1
（Weekly境界検出）の実現性検証のみ。

## Confirmed Specifications（S01でPDF実データから確認した事実）

- 対象PDFは89ページ、全て文字情報を保持するテキストレイヤー（OCR不要）。
- Weeklyメールは同一送信者からの継続シリーズで、`Subject: Weekly Report Najib ww15`
  〜 `ww29` の15件がメールヘッダー（From/Sent/Subject）付きで検出できた。
  さらにPDF先頭（1ページ目）にヘッダーなしの最新Weekly（2026-07-29相当）が1件あり、
  **実データ全体では16件のWeeklyブロックが存在する**。
- 最古のヘッダー付きWeekly（ww15）の送信日は **2026-04-10** であり、引継ぎ資料が
  述べる「最古Weekly=2026-04-17」より1件古い。基準日2026-04-17（ww16）を採用する
  場合、ww15（2026-04-10）はWeekly分割の境界検出には使うが、比較・差分処理の
  スコープには含めない、という解釈で件数（基準込み15件、差分対象14件）と整合する。
  → 詳細は `weekly_pdf_diff/IMPLEMENTATION_PLAN.md` 参照。
- **Weekly境界はページ途中（Y座標）で発生する実例を確認済み**（例: ページ6は
  上部が前Weeklyの署名、Y≈542から次Weeklyの `From:` ヘッダーが開始）。
  ページ単位の固定範囲では分割できない。
- ページ末尾に OneNote由来のフッター（例: `2026_07 - 6 ページ`）が全89ページに1行ずつ
  存在し、除外対象メタデータの安定した目印になる（フォント: `YuGothic-Regular`,
  色: 灰色 `#767676` 系）。
- OneNoteの印字日時（例: `2026年7月29日 / 13:58`）は文書全体で**1箇所のみ**（1ページ目）
  にしか出現しない。引継ぎ資料が想定する「ページ上部の日時」は全ページ共通の目印ではなく、
  ヘッダーを持たない最新Weeklyの日付推定に使える単発の手がかりとして扱う。
- 本文は Arial 11pt（通常）/ Arial,Bold 11pt（見出し）が主体。日本語のOneNote由来
  メタ文字列のみ YuGothic。
- **既存のハイパーリンクは文字色 `#0066CC`** で本文中に埋め込まれている
  （`page.get_links()` で4件確認、色コード26316=0x0066CCと一致）。引継ぎ資料が
  提案する差分色 `#0057B8` は非常に近い青であり、リンクと紛れやすい。差分は
  **太字**で必ず区別し、必要であれば差分色をもう少し離す（例: `#0033A0`寄り）ことを
  IMPLEMENTATION_PLAN.mdでリスクとして明記。
- **PyMuPDFの `find_tables()` では、罫線付きの本格的なグリッド表はほぼ検出されない**
  （1ページ目で1行×2列の小さな表が1件のみ）。実体は「Project Name: / Milestone: /
  ゲート予定 / STR / Reliability / Others」といった見出し＋番号付きリスト／
  ラベル:値行で構成された疑似構造化テキストであり、罫線ベースの表ではない。
  → 引継ぎ資料が前提とする「表・セル単位比較（table_parser.py等）」は過剰設計であり、
  「セクション階層＋行（段落・箇条書き・ラベル行）単位の比較」で十分という結論に至った。
  詳細はIMPLEMENTATION_PLAN.mdの設計判断を参照。

## Current Status

S01完了分: `weekly_pdf_diff/IMPLEMENTATION_PLAN.md` 作成済み。Phase 1
（`pdf_reader.py` / `weekly_splitter.py`）を実装し、合成PDFでの単体テスト3件
（すべてPASS）に加え、実PDF（89ページ）に対する一時実行でも16件のWeekly境界と
日付を全て正しく検出できることを確認済み。Phase 2以降（セクション階層化・
差分抽出・青太字描画・レポート出力）は未着手。

## Known Issues

- 引継ぎ資料の「Weekly数15件」と実データの「16ブロック」の差異（上記参照）。
  暫定的にww15（2026-04-10）をスコープ外として扱う方針だが、越智さんの最終確認が
  望ましい。
- 実PDFは社内機密情報（個人名・メールアドレス・電話番号・プロジェクトコード名）を
  含むため、テスト・開発では合成PDFを用いる方針（CLAUDE.md参照）。
- `page.get_text("dict")` のブロック順が視覚的なY座標順と一致しない実例を発見
  （1ページ目のOneNote日時スタンプ）。`pdf_reader.py`で `(page, y0)` ソートにより
  対処済みだが、他ページでも同様の非直感的な順序が起こり得る前提で設計する必要がある。

## Test and Execution

```bash
cd weekly_pdf_diff
pip install -r requirements.txt
python -m pytest tests/ -v
```

S01時点: `tests/test_weekly_splitter.py` の3件全てPASS（合成PDFのみ使用）。
実PDFでの検証はセッション内の一時実行として実施し、結果はIMPLEMENTATION_PLAN.md
1章に記録。実PDF自体・全文抽出テキストはリポジトリにコミットしていない。

## Important Restrictions

- 元PDF (`Hello_Ochi_San.pdf` 等) はリポジトリにコミットしない。
- テストは実データでなく合成PDFを使用する。
- 元PDFを上書きせず、常に別名で出力する。
- OCRは使用しない。外部AI API・クラウドサービスは使用しない（ローカル完結）。
