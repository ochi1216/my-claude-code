# Next Task

## Session Management

* Project Name: Outlook オーガナイザー開発
* Previous Session: S01 - 引継ぎ管理の初期設定
* Next Session Number: S02
* Recommended Session Title: Outlook オーガナイザー開発 S02 - （ユーザー指示待ち）

## Objective

* ユーザーから次のタスク指示を受ける。

## Background

* 現在の状態: 引継ぎ管理ファイル（`CLAUDE.md`, `docs/PROJECT_STATUS.md`, `docs/SESSION_HISTORY.md`, `docs/NEXT_TASK.md`）の初期セットアップが完了した段階。Outlook オーガナイザー本体のコードはまだ存在しない。
* 前回までに完了した内容:
  * S01: 引継ぎ管理ファイル一式の新規作成

## Scope

### Files That May Be Changed

* 未確定（ユーザーからのタスク指示内容に応じて次セッションで決定する）

### Files That Must Not Be Changed

* `po_database_organizer/` 配下一式
* `rtocs_organizer/` 配下一式
* `shareflex_dashboard/` 配下一式
* `youtube_summary_list_20260703_01.py`, `youtube_summary_list_20260711_01.py`, `HANDOVER_youtube_summary_list.md`
* リポジトリ直下 `README.md`（Outlookオーガナイザーの記載を追加する場合を除き、無関係な変更は行わない）

## Task

1. ユーザーからOutlookオーガナイザーの目的・要件（対象ユーザー、実行環境、外部サービス連携の有無など）についてヒアリングする。
2. ヒアリング結果を `docs/PROJECT_STATUS.md` の該当セクション（Project Overview 等）に反映する。
3. ヒアリング結果を踏まえ、最初の実装タスクを具体化し、以降のセッションで着手する。

## Completion Criteria

* 未確定（ユーザーから受けたタスク内容に応じて次セッションで定義する）

## Required Tests

* 未確定（次タスクの内容に応じて次セッションで定義する）

## Known Risks

* 注意事項: 本プロジェクトはまだ要件が確定していないため、推測で実装を進めない。
* 未確認事項: プロジェクトの目的、利用者、実行環境、外部サービス連携（Outlook/Microsoft Graph API等の利用有無を含む）。

## Start Prompt

```
CLAUDE.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md を読み込んでください。
セッションタイトル: Outlook オーガナイザー開発 S02 - （ユーザー指示待ち）
今回実施したいタスク: （ここにユーザーが具体的なタスク内容を記入）
```
