# Next Task

## Session Management

* Project Name: Outlook オーガナイザー開発
* Previous Session: S02 - アクションからR19の除外
* Next Session Number: S03
* Recommended Session Title: Outlook オーガナイザー開発 S03 - （ユーザー指示待ち）

## Objective

* ユーザーから次のタスク指示を受ける。

## Background

* 現在の状態: `outlook_total_organizer/`（ユーザー提供のベースライン`_20260713_03_01`＋S02で追加した`_20260716_01_01`、`CHANGELOG.md`）がリポジトリに存在する。アクションダッシュボードに「🧩 R19Proj」「🚫 R19Proj以外」の排他的フィルタボタンが実装済み。
* 前回までに完了した内容:
  * S01: 引継ぎ管理ファイル一式の新規作成
  * S02: ユーザー提供の既存ソース（`outlook_total_organizer`）をリポジトリに取り込み、アクションダッシュボードに「R19Proj以外」フィルタボタンを追加
* 未確認事項（S02の Open Items から持ち越し）:
  * `README.md`・`requirements.txt`の要否
  * 本ツールの起動方法・必要な環境変数・主な利用者
  * `claude/outlook-organizer-setup-nqzdo6`ブランチ（S01の成果物が存在する別ブランチ、未マージ）と本作業ブランチの関係整理

## Scope

### Files That May Be Changed

* 未確定（ユーザーからのタスク指示内容に応じて次セッションで決定する）
* 想定候補: `outlook_total_organizer/` 配下

### Files That Must Not Be Changed

* `po_database_organizer/` 配下一式
* `rtocs_organizer/` 配下一式
* `shareflex_dashboard/` 配下一式
* `youtube_summary_list_20260703_01.py`, `youtube_summary_list_20260711_01.py`, `HANDOVER_youtube_summary_list.md`
* `outlook_total_organizer/outlook_total_organizer_20260713_03_01.py`（旧バージョン、削除・上書き禁止）
* リポジトリ直下 `README.md`（Outlookオーガナイザーの記載を追加する場合を除き、無関係な変更は行わない）

## Task

1. ユーザーから次のタスク指示を受ける。
2. 必要であれば、S02のOpen Items（README/requirements.txtの要否、実機テストなど）について確認する。

## Completion Criteria

* 未確定（ユーザーから受けたタスク内容に応じて次セッションで定義する）

## Required Tests

* 未確定（次タスクの内容に応じて次セッションで定義する）

## Known Risks

* 注意事項: 本プロジェクトのコードはWindows専用（win32com依存）のため、本セッション実行環境（Linuxコンテナ）では実機起動テストができない。UIロジックの変更はHTML/JS部分を抽出したブラウザ検証で代替する運用とする。
* 未確認事項: 起動方法、必要な環境変数、外部サービス連携の詳細設定。

## Start Prompt

```
CLAUDE.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md を読み込んでください。
セッションタイトル: Outlook オーガナイザー開発 S03 - （ユーザー指示待ち）
今回実施したいタスク: （ここにユーザーが具体的なタスク内容を記入）
```
