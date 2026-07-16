# Next Task

## Session Management

- Project Name: Youtube Manager 統合開発環境
- Previous Session: S01（引継ぎ管理の初期設定）
- Next Session Number: S02
- Recommended Session Title: Youtube Manager 統合開発環境 S02 - （ユーザー指示待ち）

## Objective

- ユーザーから次のタスク指示を受ける

## Background

- 現在の状態: `claude/apply-patch-commits-uriik0`ブランチにて、PR #1（mainへのマージ待ち）が作成済み。セッション管理用ドキュメント一式（`CLAUDE.md`・`docs/`）のセットアップが完了した状態
- 前回までに完了した内容:
  - `youtube_summary_list`: ベースライン取り込み、お気に入りチャンネル動画のHTML先頭配置（VERSION 20260711_01）
  - `consolidated_html_summary_manager`: ベースライン取り込み、スキップモード手動固定機能（VERSION 20260711_02）、mode4新設・mode2見出しのみ読み上げ化・自動判定優先順位変更（VERSION 20260716_01）
  - 詳細は`docs/SESSION_HISTORY.md`のS01を参照

## Scope

### Files That May Be Changed

- 未定（次のタスク指示後に確定。指示内容に応じて`youtube_summary_list_*.py`または`consolidated_html_summary_manager_*.py`の新バージョンファイル、あるいは`docs/`配下の管理ファイルが対象になる見込み）

### Files That Must Not Be Changed

- 未定（次のタスク指示後に確定。ただし`CLAUDE.md`に定めるルールにより、既存バージョンファイルの上書き・関係のないファイルの変更は常に禁止）

## Task

1. （未定。ユーザーからの指示を受けてから記載する）
2.
3.

## Completion Criteria

- 未定（次のタスク指示後に確定）

## Required Tests

- 未定（次のタスク指示後に確定。ただし本リポジトリでは構文検証（`ast.parse`）とdiffレビューまでが実施可能範囲であり、実ブラウザ・Selenium動作確認は越智さんのローカル環境に依存する点は共通）

## Known Risks

- PR #1が本セッション終了時点でまだmainへマージされていない
- 本リポジトリのクラウド環境では、Selenium・Chrome・音声読み上げを伴う実動作確認ができない

## Start Prompt

```
Youtube Manager 統合開発環境 S02を開始します。
CLAUDE.md・docs/PROJECT_STATUS.md・docs/SESSION_HISTORY.md・docs/NEXT_TASK.mdを読み込んだ上で、
現在のブランチとGitの状態を確認してください。
今回の目的は「（ここに今回の目的を記載）」です。
```
