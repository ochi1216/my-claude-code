# NEXT_TASK.md

## Project Name

Project Cost developer開発

## Current Session

S01

## Current Session Title

Project Cost developer開発 S01 - KOB1の分析ツール

## Current Objective

Project CostのKOB1シート（SAPのプロジェクトコスト実績明細）から、該当プロジェクトの
コスト分析を行うツールを開発する。

## Background

- ユーザーより、KOB1シートを含むExcelファイル（`BG ICS Project cost summary_20260722.xlsm`、
  KOB1シート83,318行・30列）が提供された。
- 当初はSupabaseへのデータ登録を検討したが、社内の機密性の高いコストデータを外部サービスへ
  一括送信する操作がClaude Code Webの自動判定（安全分類器）によりブロックされたため、
  ローカル環境で完結する構成（Excel直接読み込み→ローカル集計→Streamlitダッシュボード）に
  方針転換した。
- ユーザーは分析対象ファイルを、実運用時に読み込むローカルパスとして
  `C:\Users\nx023836\Documents\PythonScripts\PM_organizer\ProjectCost\BG ICS Project cost summary_20260722.xlsm`
  に配置した。

## Scope

- KOB1シートの読み込み・型整備
- プロジェクト単位でのコスト集計・可視化（Streamlitダッシュボード）
- 予算(Budget/Committed)との対比分析（`Project cost against BC`シート等との突き合わせ）は
  今回のスコープ外（未着手）

## Files That May Be Changed

- `project_cost_analyzer/` 配下のファイル一式
- リポジトリ直下 `README.md`（新ツールへのリンク追記）
- `docs/PROJECT_STATUS.md` / `docs/SESSION_HISTORY.md` / `docs/NEXT_TASK.md`（セッション終了時）

## Files That Must Not Be Changed

- `po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/`,
  `youtube_summary_list_*.py`, `HANDOVER_*.md` など、本プロジェクトと無関係な既存ツール

## Task

1. KOB1シートを読み込み、プロジェクト別・期間別・コスト要素別等でコストを集計する
   Streamlitダッシュボードを作成する（完了）。
2. 実データで集計値の整合性を検証する（完了）。
3. 実際にダッシュボードを起動し、ブラウザで表示・フィルタ動作を確認する（完了）。
4. 追加の分析軸（予算対比など）が必要か、ユーザーの指示を確認する（対応待ち）。

## Completion Criteria

- KOB1シートのデータを読み込み、プロジェクト単位でコスト集計・可視化できること（達成）
- 集計値（プロジェクト別合計・期間別合計）が全体合計と一致すること（達成、テスト済み）
- 既存の他ツールに意図しない影響がないこと（達成、他フォルダは無変更）
- 必要なテストを実施すること（達成、下記「Required Tests」参照）

## Required Tests

- 実データ（KOB1シート83,318行）でのコアロジック検証: プロジェクト別集計・期間別集計の
  合計値が全体合計と一致することを確認済み
- Streamlitアプリを実際に起動し、Playwright経由でブラウザから実データを読み込ませ、
  サマリーカード・プロジェクト別内訳・期間別コスト推移グラフの表示、および
  プロジェクト名フィルタの動作を確認済み

## Known Risks

- Streamlitのmultiselectウィジェットに対する自動操作（Playwright）でのテストは、
  キー入力のタイミングにより意図しない複数選択が発生することがあった（アプリ本体の
  不具合ではなく自動操作側の癖と判断）。実際のユーザー操作（クリックでの単一選択）では
  問題にならない想定だが、次回セッションで手動確認できるとより確実。
- 予算対比分析など、KOB1以外のシート（`Project cost against BC`等）を使う機能は未着手。
