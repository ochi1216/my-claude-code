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
* Previous Session: S02 - Phase 2 Nexus検索の追加と系統別タブ化
* Next Session Number: S03
* Recommended Session Title: Document Search Manager 開発 S03 - Phase 3 Enovia検索の追加

## Objective

* **Enovia（3DEXPERIENCE / ENOVIA 2017年版）のドキュメント検索を実装し、
  `3. Enovia` タブと `0. All` から使えるようにする。**
* 検索対象は**ドキュメントのみ**でよい（越智さん確認済み）。

## Background

* Phase 1（SharePoint）と Phase 2 / 2.5（Nexus）は完了し、会社PCで実動作を確認済み。
  最新リビジョンは `document_search_manager/document_search_manager_20260903_16.py`
  （コミット `5cd128f`、ブランチ `claude/document-search-manager-phase2-nexus-d0tg0m`）。
* **着手前に必ず `document_search_manager/DESIGN_NOTES.md` を読むこと。**
  特に 3-3（Enoviaの未確認事項）と、S02で追記した教訓（3-1d〜3-1j）。
  スキル `document-search-tool-dev` も参照する（開発手順・報告の作法）。

### ★Enoviaは「推測で実装しない」★

`DESIGN_NOTES.md` 3-3 のとおり、**Enoviaだけは実装方式が確定していない。**

* URLの `emxNavigator.jsp` は **ENOVIA クラシック（V6系）Navigator UI**。
  社内は2017年版＋社内カスタマイズのため、**公開ドキュメントは当てにならない。**
* URL末尾の `ticket=ST-...` は **CASのService Ticket＝ワンタイム**で再利用不可。
* **IT責任者不在のため承認は不要**（越智さん確認済み）。
* Enoviaプロバイダは独立したアダプタなので、**実装できなくても①②は無傷。**

### S02で得た「効いた進め方」（Enoviaでも同じ手を使う）

* **推測で直さず、実際に投げて実測する。** Nexusの件数不一致は、5通りのKQLを
  投げて件数を並べる診断を作ったことで、1クリック・数秒で原因が確定した。
  仮説を順に試すより速く、証拠も残る。
* **返ってきているデータを全部見る。** 「取れないはずだ」と決める前に、
  全項目を一覧に出す診断を作る。Nexusでは、これで `qmEditor`（氏名）が
  最初から返っていたことに気づいた。
* **URLやパラメータの仕様は、実際に開いて確かめるまで確定としない。**
  リクエストのパラメータ名が、画面遷移URLのパラメータ名と同じとは限らない。

## Scope

### Phase 1（調査・設計提案）— まずここから

1. **越智さんにF12キャプチャを依頼する**（所要10分程度）。
   Enoviaで検索を1回実行し、F12 → Network → Fetch/XHR で以下を共有いただく:
   * リクエストURL・メソッド
   * リクエストヘッダー（Cookie名だけでよい。値は不要）
   * Payload（フォームデータ / JSON）
   * レスポンスの形式（JSON / HTML / XML）と先頭部分
   * ログイン直後のURL遷移（3DPassport / CAS のリダイレクト）
2. キャプチャの内容から実装方式を確定し、設計案を提示する。
3. **この段階ではコード生成を行わない。**

### 実装案（S01時点の想定。キャプチャで確定させる）

* **A（第一候補）**: `requests.Session` で3DPassport(CAS)ログイン → セッション保持
  → キャプチャした検索リクエストを再現 → パース
* **B（保険）**: Playwrightで会社PCのSSOを使いUI操作＋結果取得
  （※会社PCでPlaywrightが使えるかは**未確認**）
* **C（最終手段）**: 手動エクスポート → ローカル索引化

### Files That May Be Changed

* `document_search_manager/` 配下（新バージョンファイル
  `document_search_manager_YYYYMMDD_NN.py` として追加。既存版は `old/` へ移動）
* `document_search_manager/CHANGELOG.md` / `README.md` / `DESIGN_NOTES.md`
* `document_search_manager/config.example.json`（Enovia用の設定項目）
* `document_search_manager/tests/`（Enovia用の検証を追加）
* `document_search_manager/run_document_search_manager.bat`（呼び出し先の更新）
* `document_search_manager/requirements.txt`（新しい依存が必要な場合のみ）

### Files That Must Not Be Changed

* `outlook_total_organizer/` 配下一式
* `onenote_report_generator/` 配下一式
* `po_database_organizer/` 配下一式（`config.json` は**読み取りのみ**。書き換え禁止）
* `rtocs_organizer/` / `shareflex_dashboard/` / `rss_organizer/` 配下一式
* 各種 `*_translator` / `excel_translation` 配下一式
* `document_search_manager/old/` 配下の全リビジョン（削除・上書き禁止）
* **SharePoint / Nexus の検索ロジック・列構成**（Enovia追加の巻き添えにしない）

## Task

1. `DESIGN_NOTES.md`（特に 3-3）とスキル `document-search-tool-dev` を読む。
2. **越智さんにEnoviaのF12キャプチャを依頼する。**
3. キャプチャから実装方式を確定し、設計案を提示して承認を得る。
4. `EnoviaProvider` を実装する（`SearchProvider` を継承し `probe()` / `search()`）。
   Enoviaタブの列構成は、Enoviaが返すメタデータに合わせて決める
   （Nexusと同じく `COLUMN_SETS` に1つ足すだけで済む構造になっている）。
5. Enovia用の検証を追加し、`python tests/run_tests.py` を全項目通す。
6. CHANGELOG・README・DESIGN_NOTES を更新し、越智さんへ納品する。
7. **受入テスト（実機・越智さんに依頼）**: Enovia画面とツールの件数・上位ヒットを
   突き合わせる。
8. コミット・Pushは越智さんの明示的な指示があった場合のみ。

## Completion Criteria

* `3. Enovia` 単独と `0. All` の両方でEnoviaの文書が検索でき、画面に表示されること。
* `python tests/run_tests.py` が全項目合格すること。
* CHANGELOG に新バージョンのエントリが追加されていること。
* 越智さんの実機で、Enovia画面との突き合わせが完了していること。
* **SharePoint / Nexus の動作に影響が出ていないこと**（既存570項目が通ること）。

## Required Tests

* `python -m py_compile document_search_manager/document_search_manager_YYYYMMDD_NN.py`
* `python tests/run_tests.py`（既存570項目＋Enovia用の追加項目）
* `CHROMIUM_PATH=<chromeのパス> python tests/ui_check.py`（画面を変更した場合）
* 実機: 疎通診断でEnoviaが 🟢 になること、Enovia画面との件数突き合わせ

## Known Risks

* **認証が最大の関門。** CASのService Ticketはワンタイムで再利用できない。
  `requests.Session` でログインを再現できるかは未検証。
* **2017年版＋社内カスタマイズのため、公開情報が当てにならない。**
  キャプチャ無しに着手すると確実に空振りする。
* 会社PCでPlaywrightが使えるか未確認（案Bの前提）。
* Enoviaの結果は SharePoint / Nexus と**メタデータの体系が全く違う**可能性が高い。
  Nexusで作った「タブごとに列構成を切り替える」仕組みがそのまま効くはずだが、
  共通スキーマ（`SearchResult`）に無理に押し込めないか注意する。

## Carry-over（S02から持ち越し）

* **無し。** S02の末に、持ち越しの実機確認3件（v20260903_16 の有効期限表示、
  SharePointタブのフォルダリンクの到達性、一括ダウンロードの成否）が
  すべて完了した（2026-09-03）。**SharePoint / Nexus 側に未確認事項は残っていない。**

## Start Prompt

```
CLAUDE.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md を読み込んでください。

対象リポジトリ: ochi1216/my-claude-code
対象ブランチ: claude/document-search-manager-phase2-nexus-d0tg0m
前回セッション（S02）の最終コミット: 5cd128f（Nexusタブに有効期限の列を追加、v20260903_16）
※作業開始前に、必ず対象ブランチの最新状態をGitHubから取得（fetch/pull）してから作業を始めてください。

セッションタイトル: Document Search Manager 開発 S03 - Phase 3 Enovia検索の追加

着手前に必ず document_search_manager/DESIGN_NOTES.md を読むこと。
特に 3-3（Enoviaの未確認事項）と、S02で追記した 3-1d〜3-1j の教訓。
スキル document-search-tool-dev も参照すること。

現在の状態:
- Phase 1（SharePoint）/ Phase 2・2.5（Nexus）は完了、会社PCで実動作確認済み
- 最新リビジョンは document_search_manager/document_search_manager_20260903_16.py
- 検証は tests/run_tests.py で570項目、tests/ui_check.py で34項目すべて合格

次に行う作業（優先順位順）:
1. Enoviaの実装方式は未確定。まず越智さんにF12キャプチャを依頼する
   （Enoviaで検索を1回実行 → Network → Fetch/XHR のURL・メソッド・Payload・
     レスポンス形式・ログイン時のリダイレクト）。推測で実装しないこと。
2. キャプチャから実装方式を確定し、設計案を提示して承認を得る。
3. 承認後に EnoviaProvider を実装する（SearchProvider を継承）。
4. Enovia用の検証を追加し、既存570項目とあわせて全項目を通す。
5. CHANGELOG・README・DESIGN_NOTES を更新して納品する。
6. コミット・Pushは明示的な指示があった場合のみ。

変更してよい範囲: document_search_manager/ 配下（新バージョンファイルとして追加。
既存版は old/ へ移動）。
変更してはいけない範囲: 他ツール一式、document_search_manager/old/ 配下の全リビジョン、
SharePoint / Nexus の検索ロジックと列構成（Enovia追加の巻き添えにしない）。

完了条件: 3. Enovia と 0. All でEnoviaの文書が検索・表示でき、全検証項目が合格し、
CHANGELOGが更新され、実機での突き合わせが完了していること。

持ち越しの実機確認: 無し（S02末にすべて完了。SharePoint / Nexus 側に
未確認事項は残っていない）。
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
