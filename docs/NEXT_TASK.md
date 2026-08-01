# Next Task

## Session Management

- Project Name: Youtube Manager 統合開発環境
- Previous Session: S02（youtube_summary_list Glasp自動起動の信頼性改善）
- Next Session Number: S03
- Recommended Session Title: Youtube Manager 統合開発環境 S03 - Glaspバッチ処理の2フェーズ化実装

## Objective

- `youtube_summary_list_20260801_03.py`の`_batch_send_ctrl_x`/`_send_ctrl_x_with_retry`を、ADR 0001の設計に沿って「トリガーラウンド→検出/リトライラウンド」の2フェーズ構成に改修する

## Background

- 前回までに完了した内容・現状の課題の詳細: `docs/PROJECT_STATUS.md`の「5. Current Status」「6. Known Issues」を参照
- 設計判断の根拠・不採用案: `docs/decisions/0001-glasp-batch-trigger-detect-redesign.md`を参照
- 越智さんのローカル環境で、`youtube_summary_list_20260801_03.py`の「Glasp起動方式: 本物クリック(CDPマウス)」の実地検証結果がまだ報告されていない場合は、先にその結果を確認してから本タスクに着手すること

## Scope

### Files That May Be Changed

- `youtube_summary_list_YYYYMMDD_NN.py`の新規バージョンファイル（`youtube_summary_list_20260801_03.py`をベースに新規追加。既存バージョンファイルは上書きしない）

### Files That Must Not Be Changed

- `youtube_summary_list_20260801_03.py`以前の既存バージョンファイル（新規ファイルとして追加すること）
- `consolidated_html_summary_manager_*.py`（本タスクとは無関係）

## Task

1. ADR 0001の設計（トリガーラウンド／検出＆リトライラウンド）に基づき、越智さんと3フェーズワークフロー（Design Proposal→Architecture Audit→Implementation Patch）で実装内容を確定する
2. `_send_ctrl_x_with_retry`のクリック処理部分と検出処理部分を関数分離する
3. `_batch_send_ctrl_x`をラウンド構成に組み替える（キャンセル/スキップ操作、`browser_mode==3`のタブ再利用・後片付けとの整合性を含む）
4. 新バージョンファイルとして追加し、構文検証（`ast.parse`）とdiffレビューを実施する

## Completion Criteria

- 新バージョンファイルの構文検証に合格していること
- 変更が意図した箇所（バッチ処理のラウンド構成）のみであることをdiffで確認済みであること
- 越智さんのローカル環境での実行結果（成功率の変化）が報告され、`docs/PROJECT_STATUS.md`に反映されていること（本セッション内で反映できなければ「未確認」として次回に申し送り）

## Required Tests

- `ast.parse`による構文検証
- 変更前後のdiffレビュー
- 実際のGlasp自動起動・成功率の確認は越智さんのローカル環境に依存する（本リポジトリのクラウド環境では検証不可）

## Known Risks

- 文字起こし生成の完了タイミングはGlasp/YouTube側のバックエンド挙動に依存するため、2フェーズ化しても完全解決するとは限らない
- YouTube側の文字起こしパネルのUIパターンが複数存在することが確認されており（S02時点）、DOM検出ロジックに影響する可能性がある

## Start Prompt

```text
セッションタイトル：
Youtube Manager 統合開発環境 S03 - Glaspバッチ処理の2フェーズ化実装

対象：
- Repository: ochi1216/my-claude-code
- Branch: claude/apply-patch-commits-uriik0
- Previous commit: a1dd1fc

作業開始前に、git status／現在のブランチ／リモートとの差分を確認してください。
問題がなければ git fetch 後、git pull --ff-only を実行してください。

最初に以下を読んでください。
- docs/PROJECT_STATUS.md
- docs/NEXT_TASK.md
- docs/decisions/0001-glasp-batch-trigger-detect-redesign.md
- youtube_summary_list_20260801_03.py（対象関数のみ。ファイル全体の精査は不要）

今回のタスク：
ADR 0001の設計に基づき、youtube_summary_listのGlaspバッチ処理を
「トリガーラウンド→検出/リトライラウンド」の2フェーズ構成に改修する。

対象ファイル：
youtube_summary_list_20260801_03.py をベースにした新規バージョンファイル

変更禁止：
既存バージョンファイルの上書き、consolidated_html_summary_manager系への変更

完了条件：
構文検証・diffレビュー合格、越智さんのローカル環境での実行結果確認
```
