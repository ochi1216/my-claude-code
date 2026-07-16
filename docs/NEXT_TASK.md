# Next Task

## Session Management

* Project Name: Outlook オーガナイザー開発
* Previous Session: S04 - アクションカードにフラグマークを追加
* Next Session Number: S05
* Recommended Session Title: Outlook オーガナイザー開発 S05 - （ユーザー指示待ち）

## Objective

* ユーザーから次のタスク指示を受ける。

## Background

* 現在の状態: `outlook_total_organizer/`（ユーザー提供のベースライン`_20260713_03_01`＋S02で追加した`_20260716_01_01`＋S03で追加した`_20260716_02`＋S04で追加した`_20260716_03`、`CHANGELOG.md`）がリポジトリに存在する。
  * アクションダッシュボードに「🧩 R19Proj」「🚫 R19Proj以外」の排他的フィルタボタンが実装済み（S02）。
  * アクションタブの「対象期間」プルダウンに「3週間」「1ヶ月」を追加済み（S03、選択肢は「24H」「今日」「3日間」「1週間」「2週間」「3週間」「1ヶ月」の7択）。
  * アクションカードに🚩マーク（テキストなし、アイコンのみ）を追加済み（S04）: スレッド内いずれかのメールがOutlookでアクティブ設定（`FlagStatus == 2`）されていれば、R19Projバッジの右・タイトルの左に表示。完了済みフラグ（`FlagStatus == 1`）は対象外。絞り込みフィルタは未実装（表示のみ）。バッジ背景は薄いピンク＋淡い赤枠（視認性のためユーザー指摘により調整済み）。
  * バージョンファイル命名規則: S03（`_20260716_02.py`）以降は`outlook_total_organizer_yyyymmdd_NN.py`（末尾`_01`なし）に統一済み。
* 前回までに完了した内容:
  * S01: 引継ぎ管理ファイル一式の新規作成
  * S02: ユーザー提供の既存ソース（`outlook_total_organizer`）をリポジトリに取り込み、アクションダッシュボードに「R19Proj以外」フィルタボタンを追加
  * S03: アクションタブの対象期間プルダウンに「3週間」「1ヶ月」を追加。バージョンファイル命名規則を変更
  * S04: アクションカードに🚩マーク（アイコンのみ）を追加
* 未確認事項（S02〜S04の Open Items から持ち越し）:
  * `README.md`・`requirements.txt`の要否
  * 本ツールの起動方法・必要な環境変数・主な利用者
  * `claude/outlook-organizer-setup-nqzdo6`ブランチ（S01の成果物が存在する別ブランチ、未マージ）と本作業ブランチ（`claude/outlook-r19-filtering-ee1h81`）の関係整理
  * `claude/outlook-date-range-expansion-k5zoeb`ブランチ（S03セッション開始時、システム設定上の作業ブランチとして指定されていたが、S01/S02の成果物が存在しなかったため使用しなかった）を今後どう扱うか
  * S02・S03・S04の変更（R19Projフィルタ、対象期間「3週間」「1ヶ月」、フラグマーク）の実機（Windows＋Outlookインストール環境）での動作確認
  * フラグマークに絞り込みフィルタ（R19Projボタンのような）が必要かどうか（S04では表示のみ実装、ユーザーから明示要求なし）

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
* `outlook_total_organizer/outlook_total_organizer_20260716_01_01.py`（旧バージョン、削除・上書き禁止）
* `outlook_total_organizer/outlook_total_organizer_20260716_02.py`（旧バージョン、削除・上書き禁止）
* `outlook_total_organizer/outlook_total_organizer_20260716_03.py`（前セッションS04の成果物。上書き禁止。変更する場合は新バージョンファイル`outlook_total_organizer_yyyymmdd_NN.py`（`_01`なし）として追加すること）
* リポジトリ直下 `README.md`（Outlookオーガナイザーの記載を追加する場合を除き、無関係な変更は行わない）

## Task

1. ユーザーから次のタスク指示を受ける。
2. 必要であれば、S02〜S04のOpen Items（README/requirements.txtの要否、実機テスト、フラグ絞り込みフィルタの要否など）について確認する。
3. 新バージョンファイルを作成する場合は、`outlook_total_organizer_yyyymmdd_NN.py`（末尾`_01`なし）の命名規則に従うこと（S03でユーザー指示により変更、以降統一）。

## Completion Criteria

* 未確定（ユーザーから受けたタスク内容に応じて次セッションで定義する）

## Required Tests

* 未確定（次タスクの内容に応じて次セッションで定義する）

## Known Risks

* 注意事項: 本プロジェクトのコードはWindows専用（win32com依存）のため、本セッション実行環境（Linuxコンテナ）では実機起動テストができない。HTML/CSS/JSを含む変更はHTML断片を抽出したブラウザ検証で代替できるが、tkinterネイティブGUIのみの変更（S03など）は`ast.parse`による構文チェックと目視でのdiff確認のみとなる。
* 未確認事項: 起動方法、必要な環境変数、外部サービス連携の詳細設定。

## Start Prompt

```
CLAUDE.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md を読み込んでください。
セッションタイトル: Outlook オーガナイザー開発 S05 - （ユーザー指示待ち）
今回実施したいタスク: （ここにユーザーが具体的なタスク内容を記入）
```
