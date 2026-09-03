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

# Document Search Manager 開発

## Session Management

* Project Name: Document Search Manager 開発
* Previous Session: S01 - Phase 1 SharePoint全社検索の実装と開発資産の整備
* Next Session Number: S02
* Recommended Session Title: Document Search Manager 開発 S02 - Phase 2 Nexus検索の追加

## Objective

* **Nexus（Shareflex / SF_QualityDocumentsProd）検索を実装し、`2. Nexus` と
  `0. All` から利用できるようにする。**
* あわせて、SharePoint全社検索とNexusで同じ文書が二重表示される問題を解消する。

## Background

* Phase 1（SharePoint全社検索）は完了し、会社PCで実動作を確認済み。
  最新リビジョンは `document_search_manager/document_search_manager_20260903_08.py`
  （コミット `c8e4de4`）。
* **着手前に必ず `document_search_manager/DESIGN_NOTES.md` を読むこと。**
  調査で判明した事実・設計判断の理由・既知の罠が集約されている。
  スキル `document-search-tool-dev` も参照する（開発手順・報告の作法）。
* **Nexus実装の設計は既に確定している**（`DESIGN_NOTES.md` 3-1）:
  * Nexusの「Full text search」は SharePoint標準の `RenderListDataAsStream` ＋
    **`InplaceSearchQuery`** で実装されており、**SharePoint検索インデックス**を参照している。
    → Graph Search で等価な結果を取得できる見込みが高い。
  * 実装は `POST /search/query` に、検索範囲をNexusに限定したKQLを渡す:
    ```
    <キーワード> path:"https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd/Documents"
    ```
  * **使用スコープは `Sites.Read.All` のままで、新規のEntra ID権限申請は不要。**
  * SharePoint REST の直接呼び出しは、MCASのセッション認証（`McasUserAuth`）の再現が
    必要かつ権限追加を伴うため**採用しない**。
* 関連する設定値は `config.json` に用意済み:
  `nexus_site_url` / `nexus_folder_path` / `nexus_list_id` /
  `dedupe_nexus_from_sharepoint`。

## Scope

### Files That May Be Changed

* `document_search_manager/` 配下（新バージョンファイル
  `document_search_manager_20260904_NN.py` として追加。既存版は `old/` へ移動）
* `document_search_manager/CHANGELOG.md`（新バージョンのエントリ追加）
* `document_search_manager/README.md` / `DESIGN_NOTES.md`（仕様変更に応じて更新）
* `document_search_manager/config.example.json`（設定項目の追加時）
* `document_search_manager/tests/`（Nexus用の検証を追加）
* `document_search_manager/run_document_search_manager.bat`（呼び出し先の更新）

### Files That Must Not Be Changed

* `outlook_total_organizer/` 配下一式
* `onenote_report_generator/` 配下一式
* `po_database_organizer/` 配下一式（`config.json` は**読み取りのみ**。書き換え禁止）
* `rtocs_organizer/` / `shareflex_dashboard/` / `rss_organizer/` 配下一式
* 各種 `*_translator` / `excel_translation` 配下一式
* `document_search_manager/old/` 配下の全リビジョン（削除・上書き禁止）

## Task

1. `DESIGN_NOTES.md` とスキル `document-search-tool-dev` を読む。
2. `NexusProvider` を実装する（`SearchProvider` を継承し `probe()` / `search()` のみ）。
   * `SharePointProvider` の Graph 呼び出し・パーサを再利用する形が望ましい。
   * Shareflexの列（Document Number / Department / Top Level Process /
     Document Status / Expiry Date 等）が `fields` から取得できるかを確認する。
     取得できる場合、Nexus固有のメタデータをどう表示するかは越智さんに確認する
     （現在 Document Number 列は非表示にしている）。
3. `dedupe_nexus_from_sharepoint` を `true` にし、SharePoint全社検索側から
   Nexusサイト配下の文書を除外する（除外件数は画面に明示する）。
4. 検証ハーネスにNexus用の項目を追加し、`python tests/run_tests.py` を全項目通す。
5. CHANGELOG・README・DESIGN_NOTES を更新し、越智さんへ納品する。
6. **受入テスト（実機・越智さんに依頼）**: キーワード `validation` で、
   Nexus画面とツールの**件数・上位ヒットを突き合わせる**。
   一致しない場合は保険案（`&q=` のディープリンク生成方式）へ切り替える。
7. コミット・Pushは越智さんの明示的な指示があった場合のみ。

## Completion Criteria

* `2. Nexus` 単独と `0. All` の両方でNexus文書が検索でき、画面に表示されること。
* SharePoint全社検索との重複が除外され、除外件数が画面に明示されること。
* `python tests/run_tests.py` が全項目合格すること。
* CHANGELOG に新バージョンのエントリが追加されていること。
* 越智さんの実機で、キーワード `validation` での突き合わせが完了していること。

## Required Tests

* `python -m py_compile document_search_manager/document_search_manager_YYYYMMDD_NN.py`
* `python tests/run_tests.py`（既存268項目＋Nexus用の追加項目）
* `python tests/ui_check.py`（画面を変更した場合）
* 実機: 疎通診断でNexusが 🟢 になること、`validation` での件数突き合わせ

## Known Risks

* **Shareflexの全文検索とGraph Searchで結果が一致しない可能性。**
  参照インデックスは同一と判明しているが、ランキングや対象範囲（ビューのフィルタ等）
  の違いで件数がずれることはあり得る。突き合わせは必須。
* Nexusサイトは `.mcas.ms` プロキシ配下にあるため、結果リンクがブラウザで
  開けない可能性がある（`rewrite_host_to_mcas` で対処）。
* Phase 1 で未確認のまま残っている2件（フォルダリンクの到達性、一括ダウンロードの
  成否）は、Nexusでも同様に影響する。S02の実機確認時にあわせて確認するとよい。

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
