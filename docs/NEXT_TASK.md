# Next Task

## Session Management

- Project Name: SE Strategy オーガナイザー
- Previous Session: S01 - 引継ぎ管理の初期設定
- Next Session Number: S02
- Recommended Session Title: SE Strategy オーガナイザー S02 - （ユーザー指示に基づき設定）

## Objective

- ユーザーから次のタスク指示を受ける

## Background

- S01にて、Claude Code Webのセッション間引継ぎ管理ファイル一式（`CLAUDE.md`、`docs/PROJECT_STATUS.md`、`docs/SESSION_HISTORY.md`、`docs/NEXT_TASK.md`）を新規作成した。
- リポジトリには以下のツール群が存在する（詳細は `docs/PROJECT_STATUS.md` を参照）。
  - `rtocs_organizer/`（RTOCS動画要約・傾向分析・企業戦略策定ダッシュボード、開発が最も進んでいる）
  - `po_database_organizer/`（SharePoint PO書類カタログ化、Phase 1完了・Phase 2未着手）
  - `shareflex_dashboard/`（Nexus品質文書の集計ダッシュボード）
  - `youtube_summary_list_*.py`（YouTubeプレイリスト要約ツール、3フェーズ厳格ワークフロー運用）
  - `HANDOVER_analog_ic_scout.md`（TIアナログ製品分析ツールの構想、実装未着手）
- S01ではコード本体の機能変更は一切行っていない。

## Scope

### Files That May Be Changed

- 未確定（次セッションのユーザー指示に基づき決定する）。

### Files That Must Not Be Changed

- 未確定（次セッションのユーザー指示に基づき決定する。ただし `CLAUDE.md` に記載のGit運用ルール・バージョン管理規約は継続して尊重する）。

## Task

1. （未確定 — ユーザーからの次回指示を受けて記載する）
2.
3.

## Completion Criteria

- 未確定（次セッションのユーザー指示に基づき決定する）。

## Required Tests

- 未確定（次セッションのタスク内容に応じて決定する）。

## Known Risks

- `rtocs_organizer` の一部ステージが開発終了宣言済みの `google-generativeai` に依存しており、将来的な移行対応が必要になる可能性がある（`docs/PROJECT_STATUS.md` Known Issues参照）。
- `youtube_summary_list` は3フェーズ厳格ワークフロー（Design Proposal→Architecture Audit→Implementation Patch）の運用ルールがあり、明示的承認なしにコード生成しないこと（`HANDOVER_youtube_summary_list.md`参照）。
- 各ツールの自動テストの有無、`youtube_summary_list` の必要環境変数は未確認。

## Start Prompt

SE Strategy オーガナイザー S02を開始します。CLAUDE.md、docs/PROJECT_STATUS.md、docs/SESSION_HISTORY.md、docs/NEXT_TASK.mdを読み込んだ上で、今回の目的を伝えます。（ここに今回のタスク内容を記載してください）
