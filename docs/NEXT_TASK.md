# NEXT_TASK.md

## Project Name

PDF メール解析ツール開発（`weekly_pdf_diff/`）

## Current Session

S01

## Current Session Title

PDF メール解析ツール開発 S01 - 前週差分表示（構想の磨き直し・IMPLEMENTATION_PLAN作成）

## Current Objective

ChatGPT作成の引継ぎ資料（構想）を、実PDFの構造調査結果に基づいて磨き直し、
`weekly_pdf_diff/IMPLEMENTATION_PLAN.md` を作成する。あわせてPhase 1
（Weekly境界検出）の実現性を最小コードで検証する。**この段階ではフル実装
（差分エンジン・PDF描画）には着手しない。**

## Background

対象PDFは、Weekly ReportメールをOneNoteに集約してエクスポートしたもの（89ページ、
Weekly15〜16件、2026-04-10〜2026-07-29）。各Weeklyを直前のWeeklyと比較し、
追加・修正された文言を青太字化した別名PDFを作る、という要件。詳細は
`weekly_pdf_diff/IMPLEMENTATION_PLAN.md` を参照。

## Scope

- IMPLEMENTATION_PLAN.md の作成（10項目: 構造調査結果／区切り判定／差分抽出／
  比較方法／青太字反映方法／モジュール構成／テスト計画／リスクと代替案／
  実装手順／完了判定基準）
- Phase 1（PDF読み込み・Weekly境界検出）の最小プロトタイプと、合成PDFによる
  単体テスト

## Files That May Be Changed

- `CLAUDE.md`, `docs/PROJECT_STATUS.md`, `docs/SESSION_HISTORY.md`,
  `docs/NEXT_TASK.md`（本ファイル）
- `weekly_pdf_diff/` 配下の新規ファイル一式

## Files That Must Not Be Changed

- 他の既存プロジェクト（`rtocs_organizer/`, `po_database_organizer/`,
  `shareflex_dashboard/`, `youtube_summary_list_*.py` 等）
- 元PDF（リポジトリにコミットしない）

## Task

1. 実PDFをPyMuPDFで解析し、構造・フォント・色・リンク・Weekly境界を確認する（実施済み）
2. `weekly_pdf_diff/IMPLEMENTATION_PLAN.md` を作成する
3. Phase 1（Weekly分割・日付抽出）の最小プロトタイプコードを作成する
4. 合成PDFで単体テストを実施する
5. 完了条件と既知のリスクを整理し報告する

## Completion Criteria

- IMPLEMENTATION_PLAN.md が引継ぎ資料の10項目を満たし、実データ調査結果を反映している
- Phase 1プロトタイプが合成PDFに対して単体テストをパスする
- 既存の他プロジェクトに影響がない
- 実データ（PDF本体・全文抽出テキスト）をリポジトリにコミットしない

## Required Tests

- Weekly境界検出（ページ番号＋Y座標）の単体テスト（合成PDF）
- 日付抽出優先順位ロジックの単体テスト

## Known Risks

- 実データの「Weekly16ブロック／基準日以前の1件」という食い違い（要越智さん確認）
- 差分色 `#0057B8` と既存ハイパーリンク色 `#0066CC` が近似している
- PyMuPDFの罫線表検出が実質使えないため、表比較は「セクション＋行」ベースに設計変更
