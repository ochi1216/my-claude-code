# Next Task

## Session Management

* Project Name: Outlook オーガナイザー開発
* Previous Session: S05 - 統括コックピットv2刷新・四半期振り返りタブ新設
* Next Session Number: S06
* Recommended Session Title: Outlook オーガナイザー開発 S06 - 振り返りタブ手動追加日付バグ修正の完了と後続対応

## Objective

* 最優先: S05の最後に着手し未完了のまま終了した「振り返りタブの手動追加項目が月別タイムラインで日付を無視する不具合」の修正（`outlook_total_organizer_20260730_06.py`）を完了させる。
* その後は未確定（ユーザーから次のタスク指示を受ける）。

## Background

* 現在の状態: `outlook_total_organizer/`の最新コミット済みリビジョンは`outlook_total_organizer_20260730_05.py`（コミット`dc04c76`）。
* S05で新規構築・大幅改修した内容の詳細は`docs/PROJECT_STATUS.md`の3節・4節、および`docs/SESSION_HISTORY.md`のS05セクションを参照。要点:
  * 統括コックピットv2を全面刷新（異常種類5分類、生体信号の畳み込み、スレッド重複解消、sticky見出し、確認済みボタン統一）。
  * 四半期振り返りタブを新規構築。オンラインアーカイブ＋手動アーカイブフォルダ横断のメール取得、AIによる実績統合、4段階ランク(S/A/B/🔵進行中)判定、スタッフ（部下）成果の反映、月別チェックボックスによる選択的再生成（`force_refresh`で確実に更新）。
* **未完了タスク**: `outlook_total_organizer_20260730_06.py`が作業ディレクトリに存在する（`ast.parse`構文チェックのみ実施、コンパイルは通る）。内容は、`apply_review_manual_overrides`内で手動追加項目の`year_month_label`を、完了日(`completed_date`)から`"YYYY年M月"`形式で算出するよう修正するもの（従来は常に固定文字列「手動追加」になっており、月別タイムラインでいつの項目か分からなかった）。
  * **このファイルはまだdiff確認・スタンドアロンテスト・Playwright検証・ユーザーへの納品（SendUserFile）・コミットのいずれも行っていない。**
  * `_20260730_05.py`との差分は、`apply_review_manual_overrides`内の`item["year_month_label"] = "手動追加"`の行を、`completed_date`をパースして`"{年}年{月}月"`を組み立て、パース失敗時のみ`"手動追加"`にフォールバックするロジックに置き換えた1箇所のみ（作業中に確認済みだが、次セッションで改めてdiffを取り直して確認すること）。

## Scope

### Files That May Be Changed

* `outlook_total_organizer/` 配下（新バージョンファイルとして追加。既存ファイルは上書きしない）
* `outlook_total_organizer/CHANGELOG.md`（新バージョンのエントリ追加）

### Files That Must Not Be Changed

* `po_database_organizer/` 配下一式
* `rtocs_organizer/` 配下一式
* `shareflex_dashboard/` 配下一式
* `youtube_summary_list_20260703_01.py`, `youtube_summary_list_20260711_01.py`, `HANDOVER_youtube_summary_list.md`
* `outlook_total_organizer/`配下の既存の全リビジョンファイル（`_20260713_03_01.py`〜`_20260730_05.py`）は削除・上書き禁止
* `outlook_total_organizer/outlook_total_organizer_20260730_06.py`（S05で作成済みの未完了ファイル）は、内容を破棄せず、まずこのファイルに対してテスト・検証を行うこと（作り直す場合も、まず既存の変更内容を確認してから判断する）
* リポジトリ直下 `README.md`（Outlookオーガナイザーの記載を追加する場合を除き、無関係な変更は行わない）

## Task

1. **最優先**: `outlook_total_organizer_20260730_06.py`について、`_20260730_05.py`とのdiffを取り直して変更範囲を確認し、Outlook非依存の`apply_review_manual_overrides`ロジックをスタンドアロンハーネスで検証する（完了日あり/なし/不正な日付形式、の3パターンで`year_month_label`が正しく算出されることを確認）。検証後、CHANGELOGエントリを追加し、ユーザーへ納品（SendUserFile）する。
2. ユーザーの確認・承認を得てから、明示的な指示があった場合のみコミット・Push（本セッションの慣例）。
3. 以降は未確定（ユーザーからの次のタスク指示を受ける）。

## Completion Criteria

* `outlook_total_organizer_20260730_06.py`が、diff確認・スタンドアロンテスト・（該当すれば）Playwright検証を経てユーザーへ納品され、CHANGELOG.mdに対応エントリが追加されていること。
* その後の作業は、ユーザーから受けたタスク内容に応じて次セッションで定義する。

## Required Tests

* `outlook_total_organizer_20260730_06.py`: `ast.parse`構文チェック（実施済み、再確認推奨）、`_20260730_05.py`との`diff`による変更範囲確認、`apply_review_manual_overrides`の`year_month_label`算出ロジックをOutlook非依存のスタンドアロンハーネスで検証。
* それ以外は未確定（次タスクの内容に応じて次セッションで定義する）。

## Known Risks

* 本プロジェクトのコードはWindows専用（`win32com`依存）のため、本セッション実行環境（Linuxコンテナ）では実機起動テストができない。実機での動作確認は毎回ユーザーに依頼する運用が定着している。
* 振り返りタブの`analysis_cache/review_monthly/*.json`のうち、S05の各修正（アーカイブ検出・エラー処理・スタッフ成果annotate）より前に生成されたキャッシュは、該当月をチェックボックスで選んで再生成しない限り最新のロジックが反映されない。ユーザーへの案内が必要な場合がある。
* スタッフ名簿(`project_knowledge["staffs"]`)の登録名と、実際のOutlook送信者表示名の表記ゆれは未確認。

## Start Prompt

```
CLAUDE.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md を読み込んでください。

対象リポジトリ: ochi1216/my-claude-code
対象ブランチ: claude/outlook-r19-filtering-ee1h81
前回セッション（S05）の最終コミット: dc04c769722229e1feb12ecec99cf0906cca5878（短縮: dc04c76）（Outlookオーガナイザー: 振り返りタブでチェックした月を確実に強制更新するよう修正（20260730_05））
※作業開始前に、必ず対象ブランチの最新状態をGitHubから取得（fetch/pull）してから作業を始めてください。

現在の状態:
- outlook_total_organizer/outlook_total_organizer_20260730_05.py が最新のコミット済みリビジョン
- outlook_total_organizer/outlook_total_organizer_20260730_06.py が作業ディレクトリに存在（前回セッションで作成、未コミット・未検証・未納品）。振り返りタブの手動追加項目が月別タイムラインで完了日を無視し常に「手動追加」にまとめられる不具合の修正版。

セッションタイトル: Outlook オーガナイザー開発 S06 - 振り返りタブ手動追加日付バグ修正の完了と後続対応

次に行う作業（優先順位順）:
1. outlook_total_organizer_20260730_06.py の内容を確認し、_20260730_05.py とのdiffを取り直して変更範囲を確認する。
2. apply_review_manual_overrides の year_month_label 算出ロジック（completed_date から "YYYY年M月" を組み立てるよう変更した箇所）を、Outlook非依存のスタンドアロンハーネスで検証する（完了日あり/なし/不正形式の3パターン）。
3. CHANGELOG.md に対応するVERSIONエントリを追加する。
4. ユーザーへ .py と CHANGELOG.md を納品する（SendUserFile）。
5. ユーザーの明示的な指示があった場合のみコミット・Push する。
6. 以降はユーザーから次のタスク指示を受ける。

変更してよい範囲: outlook_total_organizer/ 配下（新バージョンファイルとして追加。既存ファイルは上書き禁止）。
変更してはいけない範囲: po_database_organizer/, rtocs_organizer/, shareflex_dashboard/, youtube_summary_list_*.py, HANDOVER_youtube_summary_list.md、outlook_total_organizer配下の既存の全リビジョンファイル、リポジトリ直下README.md（無関係な変更をしない）。

完了条件: outlook_total_organizer_20260730_06.py（または必要なら作り直した新バージョン）が検証済みでユーザーへ納品され、CHANGELOG.mdが更新されていること。

必要なテスト: ast.parse構文チェック、直前リビジョンとのdiff確認、Outlook非依存ロジックのスタンドアロンPythonハーネスでの検証（該当すればPlaywrightでのHTML検証）。
```
