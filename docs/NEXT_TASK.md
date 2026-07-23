# NEXT_TASK.md

## Project Name

Project Cost developer開発

## Current Session

S02（未開始）

## Current Session Title

Project Cost developer開発 S02 - KOB1分析ツールの継続改善（次タスク未定）

## Current Objective

未定。ユーザーから次のタスク指示を受ける。

## Background

S01で`project_cost_analyzer/`フォルダにKOB1コスト分析用Streamlitダッシュボードを
新規開発した（最新版: `project_cost_analyzer_20260722_13.py`）。3タブ構成
（事業部俯瞰／プロジェクト深掘り／ファンクション横断）に加え、Function/Func.Category/
B4P category/FSI Descriptionの4軸で深掘りできる「コスト種別深掘り」機能、フィルタ・
並び替え付き明細テーブル、明細の可視化グラフ、設定の永続化などを実装済み。
詳細は`docs/PROJECT_STATUS.md`・`docs/SESSION_HISTORY.md`のS01記録を参照。

## Scope

未定。ユーザーの次回指示に従う。

参考: S01時点で保留・未着手のまま残っている既知の候補（指示があった場合の対応候補であり、
ユーザーの指示なしに着手しないこと）:

- 予算(Budget/Committed)との対比分析（`Project cost against BC`シート等との突き合わせ）
- Cost Elementの独自グルーピング（提案時の案D、未採用）
- 自動テストスイート（pytest等）の整備
- ユーザーのWindows実機での`run_dashboard.bat`経由の動作確認結果のフィードバック反映

## Files That May Be Changed

- `project_cost_analyzer/` 配下のファイル一式（新しい変更は次バージョン`_14`以降として
  旧版を残したまま追加する）
- リポジトリ直下 `README.md`（必要な場合のみ）
- `docs/PROJECT_STATUS.md` / `docs/SESSION_HISTORY.md` / `docs/NEXT_TASK.md`
  （セッション終了時）

## Files That Must Not Be Changed

- `po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/`,
  `youtube_summary_list_*.py`, `HANDOVER_*.md` など、本プロジェクトと無関係な既存ツール

## Task

ユーザーから次のタスク指示を受ける。

## Completion Criteria

未定（次回タスク指示に応じて設定する）。

## Required Tests

未定。ただしS01の慣行に倣い、実データでのコアロジック検証とStreamlit実起動＋
Playwrightでの実機確認を継続することが望ましい。

## Known Risks

- Streamlitのselectboxで`session_state`経由の値復元を行う際、プルダウンの表示ラベルが
  更新されない癖がある（`_06`で対処済みのパターンを新規箇所にも踏襲すること）
- Plotly円グラフは既定で反時計回りのため、新規に円グラフを追加する際は
  `sort=False`+`direction="clockwise"`の指定を忘れないこと
- `st.dataframe`標準の列非表示機能はアプリ独自の「表示する列」と連動しない
  （Streamlit側の制約のため回避不可、注記で対応済み）
