# Next Task

> このリポジトリは複数プロジェクトを1つのリポジトリで管理しているため、
> プロジェクトごとに節を分けて記載する。

---

# Outlook オーガナイザー開発

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

---

# OneNote オーガナイザー開発

## Project Name

Onenote オーガナイザー開発

## Current Session

S01

## Current Session Title

Outlook オーガナイザー開発 S01 - 新規比較差分追加機能
（実体はOneNote Report Generatorの複数サーバー対応検討。プロジェクト名・
セッションタイトルの表記ゆれはユーザー提示のテンプレートをそのまま使用）

## Current Objective

あらたなサーバー上のOneNoteも取り込んで、内容をプロジェクトベースで比較検討する。
引継ぎ資料（`HANDOVER_onenote_report_generator.md`）6章の「次期タスク」と同一の依頼。

## Background

- 現行の認証（MSAL）・`_token`・`_extractor` はグローバル変数で、単一
  Microsoft 365 テナント・単一アカウントを前提とした設計（コード確認済み）。
- 一方、同一テナント内の複数SharePointサイトへの対応は `config.json` の
  `sites` 配列と `/api/sites` エンドポイントで既に実装済み（コード確認済み、
  VERSION 20260512_03_01）。
- 「別のOneNoteサーバー」が何を指すかは、引継ぎ資料で以下3パターンが
  想定されており、越智さんへの確認が必須とされている（推測で進めない原則）。
  1. 同一テナント内の別サイト/別ノートブック（→ 既に対応済みの可能性）
  2. 別のMicrosoft 365テナント（他社・他組織）のOneNote（→ マルチテナント
     認証が必要な大規模設計変更）
  3. 個人アカウント（Microsoftアカウント）のOneNote（→ 別認証フローが必要）

## Scope

- Phase 1（設計提案）：上記1〜3のどれに該当するかを越智さんに確認し、
  該当パターンに応じた設計案を提示する。**この段階ではコード生成を行わない。**
- Phase 2（監査）以降は、越智さんの「●３．承認します」の発言後に着手する。

## Files That May Be Changed

Phase 1では変更なし（設計提案のみ）。Phase 3着手後の想定範囲：

- `onenote_report_generator/onenote_report_generator_20260706_01.py`
  （認証・`_token`・`_extractor` 関連、必要に応じて `/api/sites` 等）
- `onenote_report_generator/templates/index.html`（テナント/サーバー切替UI等、必要な場合）
- `onenote_report_generator/config.example.json`
- `onenote_report_generator/CHANGELOG.md`

## Files That Must Not Be Changed

- 上記以外の全ファイル・全フォルダ（`po_database_organizer/` 等、他ツール一式）
- 依頼範囲外のメソッド・エンドポイント（「ついでに直す」禁止）

## Task

1. AskUserQuestion等で、越智さんに上記1〜3のどれに該当するかを確認する
2. 該当パターンに応じた設計案（A/B/C等）をPhase 1として提示する
3. 越智さんの案選択・承認を待つ（Phase 2監査を経てから実装）

## Completion Criteria

- 上記1〜3のどれに該当するか確定していること
- Phase 1設計提案が越智さんに提示されていること
- 既存機能に意図しない影響がないこと（Phase 3実装時）
- 必要なテストが実施されていること（Phase 3実装時）

## Required Tests

- Phase 3実装時：Python構文チェック、既存エンドポイントの回帰確認
- 越智さんの実機（Windows/Chrome）でのGraph API認証・複数サイト/複数テナント
  切替の実地確認（本リモートセッションでは実施不可）

## Known Risks

- グローバル変数 `_token` / `_extractor` は複数テナント・複数ユーザーの
  同時アクセスに対して競合リスクがある（Phase 2監査で必須の論点）
- `bookmarks.json` は現状「単一サイトのID」を前提としたデータ構造。複数
  サーバー対応時はサーバー識別子/テナント識別子フィールドの追加要否と
  後方互換性の設計判断が必要
