# Session History

セッション終了処理（ユーザーが明示的に指示した場合）のたびに、完了した
セッションを1件だけ追記する。同一セッション内の途中経過は記録しない。

> このリポジトリは複数プロジェクトを1つのリポジトリで管理しているため、
> プロジェクトごとに節を分けて記載する。セッション番号もプロジェクトごとに数える。

---

# Outlook オーガナイザー開発

## Session Index

| Session | Title | Date | Status | Main Files |
| ------- | ----- | ---- | ------ | ---------- |
| S01 | Outlook オーガナイザー開発 S01 - 引継ぎ管理の初期設定 | 2026-07-16 | 完了 | CLAUDE.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md |
| S02 | Outlook オーガナイザー開発 S02 - アクションからR19の除外 | 2026-07-16 | 完了 | outlook_total_organizer/outlook_total_organizer_20260716_01_01.py, outlook_total_organizer/CHANGELOG.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md |
| S03 | Outlook オーガナイザー開発 S03 - アクションタブの対象期間に3週間・1か月を追加 | 2026-07-16 | 完了 | outlook_total_organizer/outlook_total_organizer_20260716_02.py, outlook_total_organizer/CHANGELOG.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md |
| S04 | Outlook オーガナイザー開発 S04 - アクションカードにフラグマークを追加 | 2026-07-16 | 完了 | outlook_total_organizer/outlook_total_organizer_20260716_03.py, outlook_total_organizer/CHANGELOG.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md |
| S05 | Outlook オーガナイザー開発 S05 - 統括コックピットv2刷新・四半期振り返りタブ新設 | 2026-07-16〜2026-07-30 | 一部未完了（詳細は本文参照） | outlook_total_organizer/outlook_total_organizer_20260730_05.py（コミット済み最新）, outlook_total_organizer/outlook_total_organizer_20260730_06.py（未コミット・未検証・未納品）, outlook_total_organizer/diagnose_archive.py, outlook_total_organizer/CHANGELOG.md, CLAUDE.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md |

## S01 - 引継ぎ管理の初期設定

### Purpose

* 「Outlook オーガナイザー開発」プロジェクトを「1タスク＝1セッション」で進めるための引継ぎ管理ファイル一式を初期セットアップする。

### Work Completed

* リポジトリ直下に `CLAUDE.md` を新規作成し、セッション運用ルール・セッションタイトル命名規則・作業終了時の手順・Git運用ルールを記載した。
* `docs/PROJECT_STATUS.md` を新規作成し、現時点でのリポジトリ構成・プロジェクト状況（Outlook オーガナイザーのコードは未着手であること）を記録した。
* `docs/SESSION_HISTORY.md`（本ファイル）を新規作成し、S01 の作業履歴を記録した。
* `docs/NEXT_TASK.md` を新規作成し、次セッションでユーザーからタスク指示を受ける旨を記録した。
* 事前にリポジトリ内を確認し、`CLAUDE.md` および `docs/` 配下のファイルが存在しないこと、Outlook オーガナイザー関連のコードが存在しないことを確認した。

### Files Changed

* `CLAUDE.md`（新規作成）: セッション運用・タイトル命名・作業終了時手順・Git運用ルールを記載
* `docs/PROJECT_STATUS.md`（新規作成）: プロジェクト現状のスナップショットを記載
* `docs/SESSION_HISTORY.md`（新規作成）: セッション履歴管理の枠組みとS01の記録を記載
* `docs/NEXT_TASK.md`（新規作成）: 次回タスク定義の枠組みを記載

### Decisions

* プロジェクト名の表記は「Outlook オーガナイザー開発」に統一する。
* セッションタイトル形式は「プロジェクト名 S連番 - 今回のタスク」とする。
* 既存の他プロジェクト（PO Database Organizer 等）のバージョン命名規則・CHANGELOG運用をOutlookオーガナイザーにも適用するかは未確定のため、`PROJECT_STATUS.md` に「未確認」として記載した。

### Tests

* 本セットアップはドキュメントファイルの新規作成のみであり、コード変更を伴わないため、自動テストは実施していない。
* `git status` および `git diff` によるファイル差分確認のみ実施した。

### Open Items

* 未完了: Outlook オーガナイザーの要件定義・設計・実装はすべて未着手。
* 未確認: プロジェクトの目的、主な利用者、実行環境、外部サービス（Outlook/Microsoft Graph API等）連携の有無。
* リスク: 次タスクの内容が未確定のため、`docs/NEXT_TASK.md` のObjectiveは仮の状態である。

### Next Session

* 次の作業: ユーザーからOutlookオーガナイザーの最初のタスク指示を受け、要件を確認する。
* 次回の推奨タイトル: `Outlook オーガナイザー開発 S02 - （ユーザー指示待ち）`

## S02 - アクションからR19の除外

### Purpose

* アクションダッシュボードで、既存の「R19Projのみ表示」フィルタに加えて、「R19Proj以外のみ表示」フィルタボタンを新設する。

### Work Completed

* セッション開始時に本リポジトリ内（作業ブランチ `claude/outlook-r19-filtering-ee1h81`）で `CLAUDE.md` / `docs/` および Outlook オーガナイザー関連コードを探索したが、いずれも存在しないことを確認した（S01の成果物は別ブランチ `claude/outlook-organizer-setup-nqzdo6` にのみ存在し、未マージだった）。
* リポジトリ全体（全ブランチ・ファイルシステム）を検索しても「R19Proj」「アクションシート」に該当するコードが見つからなかったため、いったんユーザーに確認を試みたところ、ユーザーから既存ソース一式（`outlook_total_organizer_20260713_03_01.py`, `CHANGELOG_outlook_total_organizer.md`）が添付された。このソースはこれまで本リポジトリ外で開発されていたものと判明した。
* `claude/outlook-organizer-setup-nqzdo6` ブランチから `CLAUDE.md` / `docs/*` を作業ブランチに取り込んだ。
* `outlook_total_organizer/` フォルダを新規作成し、ユーザー提供のベースライン（`outlook_total_organizer_20260713_03_01.py`）と変更履歴（`CHANGELOG.md`。元ファイルは`r"""..."""`のPython docstringで囲われていたため、Markdownファイルとして純粋なテキストになるよう囲いを除去）を格納した。
* アクションダッシュボードのHTML/JS生成部分（`HTMLReportGenerator.generate_action_dashboard_report`）を対象に、以下を変更した新バージョン `outlook_total_organizer_20260716_01_01.py` を追加した。
  * コントロールバーの「プロジェクト:」フィルタ行に「🚫 R19Proj以外」ボタンを新設。
  * 絞り込み状態の管理を、真偽値`r19FilterActive`から3状態（`'all'`/`'only'`/`'exclude'`）の`r19FilterMode`に変更し、`toggleR19Filter`を2ボタン共通の関数に統一。既存の「🧩 R19Proj」ボタンと新規の「🚫 R19Proj以外」ボタンは排他的に動作する（片方をONにするともう片方は自動OFF、同じボタンの再クリックで解除）。
  * CSSに`#r19ExcludeFilterBtn.active`（赤系`#dc2626`）を追加。既存の`#r19FilterBtn.active`（紫`#7c3aed`）とは別配色にした。
* `CHANGELOG.md`の先頭に`VERSION 20260716_01_01`のエントリを追加。
* `docs/PROJECT_STATUS.md` を更新（プロジェクト概要・リポジトリ構成・現在の機能・既知の制約などをOutlook オーガナイザーのコードが実在する状態に合わせて全面更新）。

### Files Changed

* `CLAUDE.md`（新規、`claude/outlook-organizer-setup-nqzdo6`ブランチから取り込み）
* `docs/PROJECT_STATUS.md`（`claude/outlook-organizer-setup-nqzdo6`ブランチから取り込んだ上で、S02の内容を反映して更新）
* `docs/SESSION_HISTORY.md`（本ファイル。取り込み＋S02の記録を追記）
* `docs/NEXT_TASK.md`（取り込み＋S03向けに更新）
* `outlook_total_organizer/outlook_total_organizer_20260713_03_01.py`（新規。ユーザー提供のベースラインをそのまま追加）
* `outlook_total_organizer/outlook_total_organizer_20260716_01_01.py`（新規。上記ベースラインに「R19Proj以外」フィルタボタンを追加）
* `outlook_total_organizer/CHANGELOG.md`（新規。ユーザー提供の変更履歴＋今回のS02エントリを追加）

### Decisions

* 本ツールの既存バージョン命名規則（`outlook_total_organizer_yyyymmdd_NN_01.py`、CHANGELOG.mdによる詳細な変更履歴管理）は、本リポジトリ外で既に確立されていたため、リポジトリ直下README.mdの命名規則（`ツール名_yyyymmdd_連番.py`）に合わせず、既存の命名規則をそのまま踏襲した。
* 「R19Proj」と「R19Proj以外」の2つのフィルタボタンは、同時にONにすると表示件数が矛盾する（両方ONなら「R19かつR19でない」で0件になる）ため、排他的トグルとして実装した。
* README.md・requirements.txtは今回のタスク範囲外と判断し、作成しなかった（他ツールと同様の体裁で必要かどうかは未確認）。

### Tests

* `ast.parse`によるPython構文チェック（`outlook_total_organizer_20260716_01_01.py`、エラーなし）。
* `outlook_total_organizer_20260713_03_01.py`と`outlook_total_organizer_20260716_01_01.py`の`diff`により、意図した箇所（CSS1行・HTML1行・JS関数2箇所）のみが変更されていることを確認。
* 生成HTML内のコントロールバー部分（フィルタボタン＋JS）のみを抽出したスタンドアロンHTMLを作成し、Playwrightのヘッドレスブラウザで以下を確認:
  * 初期状態: 全カード表示
  * 「🧩 R19Proj」クリック: R19カードのみ表示、ボタンがactive化
  * 「🚫 R19Proj以外」クリック: 非R19カードのみ表示に切り替わり、R19Projボタンは自動的に非active化
  * 「🚫 R19Proj以外」再クリック: 絞り込み解除、全カード表示に復帰
* Outlook実データ・Gemini API・tkinter GUIを含むエンドツーエンドの実機テストは、実行環境がLinuxコンテナでOutlook/Windows依存機能を動かせないため未実施。

### Open Items

* 未実施: 実機（Windows＋Outlookインストール環境）での動作確認。
* 未確認: `README.md`・`requirements.txt`の要否、本ツールの起動方法・必要な環境変数・主な利用者。
* 未確認: `claude/outlook-organizer-setup-nqzdo6`ブランチ自体は本作業ブランチにマージされていないため、両ブランチが今後どう扱われるか（どちらを正とするか）はユーザー確認が必要。

### Next Session

* 次の作業: 未確定（ユーザーからの次のタスク指示を受ける）。実機テストの実施や、README.md/requirements.txtの整備などが候補。
* 次回の推奨タイトル: `Outlook オーガナイザー開発 S03 - （ユーザー指示待ち）`

## S03 - アクションタブの対象期間に3週間・1か月を追加

### Purpose

* アクションダッシュボード生成タブの「対象期間」プルダウン（従来「24H」「今日」「3日間」「1週間」「2週間」の5択）に、「3週間」「1ヶ月」の2択を追加する。

### Work Completed

* 作業開始前に、セッションのシステム設定上の作業ブランチ（`claude/outlook-date-range-expansion-k5zoeb`）と、タスク指示書に記載の対象ブランチ（`claude/outlook-r19-filtering-ee1h81`、コミット`c5eb73c`）が食い違っていることを検出した。前者にはS01/S02の成果物（`CLAUDE.md`/`docs/`/`outlook_total_organizer/`一式）が一切存在しなかったため、内容を報告のうえユーザーに確認し、`claude/outlook-r19-filtering-ee1h81`を作業ブランチとして使用する指示を受けた。
* `outlook_total_organizer_20260716_01_01.py`をコピーして新バージョン`outlook_total_organizer_20260716_02.py`を作成し、以下2箇所を変更した。
  * `MailManagerGUI._ui_action_tab`: 対象期間コンボボックスの`values`に`"3週間"`, `"1ヶ月"`を追加。
  * `MailManagerGUI._get_action_days`: 日数変換辞書に`"3週間": 21`, `"1ヶ月": 30`を追加。
* 日数換算値は、既存のコックピット/プロジェクト俯瞰/スタッフ俯瞰タブの期間プルダウンで既に使われている「1ヶ月」=30日の換算（`days_map`, `_get_period_days`等）と統一した。ユーザー指示は「１か月」（か）表記だったが、本ツール内の既存表記はすべて「ヶ月」（ヶ）で統一されていたため、既存表記に合わせた。
* `outlook_total_organizer/CHANGELOG.md`の先頭に`VERSION 20260716_02_01`のエントリを追加してコミット・プッシュ後、ユーザーから「今後はバージョンファイル命名規則の末尾`_01`を廃止し`outlook_total_organizer_yyyymmdd_NN.py`に統一する」との追加指示を受けた。これを受けて本セッション成果物のみ`git mv`で`outlook_total_organizer_20260716_02_01.py` → `outlook_total_organizer_20260716_02.py`にリネームし、CHANGELOG.mdのVERSION見出し（`20260716_02_01`→`20260716_02`）および全docs内のファイル名参照を追随修正した。旧命名規則ファイル（`_20260713_03_01.py`, `_20260716_01_01.py`）は遡ってリネームしていない。
* `docs/PROJECT_STATUS.md`を更新（新バージョンファイルの追加、アクションタブの期間選択肢の記載、テスト方法・変更禁止ファイルの更新、新命名規則への変更の記録）。

### Files Changed

* `outlook_total_organizer/outlook_total_organizer_20260716_02.py`（新規。`_20260716_01_01`からのコピー＋対象期間プルダウンへの「3週間」「1ヶ月」追加。当初`_20260716_02_01.py`として追加後、新命名規則への変更指示を受け`_20260716_02.py`にリネーム）
* `outlook_total_organizer/CHANGELOG.md`（`VERSION 20260716_02`エントリを追加。当初`VERSION 20260716_02_01`として追加後、上記リネームに合わせ見出しを修正）
* `docs/PROJECT_STATUS.md`（新バージョンファイル・アクションタブの期間選択肢・テスト方法・変更禁止ファイルの記載を更新）
* `docs/SESSION_HISTORY.md`（本ファイル。S03の記録を追記）
* `docs/NEXT_TASK.md`（S04向けに更新）

### Decisions

* 「対象期間」の日数変換は、既存の`get_relevant_mails_for_period`/`search_mails_fast`側の期間フィルタリングロジック（`days`引数を`timedelta(days=days)`にそのまま使う汎用実装で、上限チェックなし）を変更せず、GUI側の選択肢と変換辞書に値を追加するだけで対応可能と判断した。
* 「1か月」の表記は、ユーザー指示の「か」ではなく、本ツール内の既存表記（コックピット等の他タブ）に合わせて「ヶ月」に統一した。
* 旧バージョンファイル（`_20260713_03_01`, `_20260716_01_01`）は上書きせず、新バージョンファイルとして追加した（プロジェクトのバージョン管理方針を踏襲）。
* バージョンファイル命名規則を、ユーザー指示に基づき`outlook_total_organizer_yyyymmdd_NN_01.py`から`outlook_total_organizer_yyyymmdd_NN.py`（末尾`_01`廃止）に変更した。今後のバージョンファイルはすべてこの新規則に従う。既存の旧規則ファイルは遡ってリネームしない（不必要な差分・過去のCHANGELOGとの不整合を避けるため）。

### Tests

* `ast.parse`によるPython構文チェック（`outlook_total_organizer_20260716_02.py`、エラーなし）。
* `outlook_total_organizer_20260716_01_01.py`と`outlook_total_organizer_20260716_02.py`の`diff`により、意図した2箇所（コンボボックスの`values`、`_get_action_days`の日数変換辞書）のみが変更されていることを確認。
* 本変更はtkinterのネイティブGUIウィジェット（`ttk.Combobox`）の選択肢追加であり、S02のようにHTML/JS部分を抽出してPlaywrightで検証する代替手段が適用できないため、ブラウザでの動作検証は実施していない。
* Outlook実データ・Gemini API・tkinter GUIを含むエンドツーエンドの実機テスト（Windows＋Outlookインストール環境でのプルダウン選択→アクション一覧生成の動作確認）は、実行環境がLinuxコンテナのため未実施。

### Open Items

* 未実施: 実機（Windows＋Outlookインストール環境）での「3週間」「1ヶ月」選択時の動作確認（メール取得件数・処理時間・AI解析結果の妥当性を含む）。
* 未確認: `README.md`・`requirements.txt`の要否、本ツールの起動方法・必要な環境変数・主な利用者（S02から持ち越し）。
* 未確認: `claude/outlook-organizer-setup-nqzdo6`ブランチ（S01の成果物が存在する別ブランチ、未マージ）と本作業ブランチの関係整理（S02から持ち越し）。
* 未確認: `claude/outlook-date-range-expansion-k5zoeb`ブランチ（本セッションのシステム設定上の作業ブランチとして指定されていたが、S01/S02の成果物が存在しなかったため未使用のまま）を今後どう扱うか。

### Next Session

* 次の作業: 未確定（ユーザーからの次のタスク指示を受ける）。実機テスト（S02・S03分含む）の実施や、README.md/requirements.txtの整備などが候補。
* 次回の推奨タイトル: `Outlook オーガナイザー開発 S04 - （ユーザー指示待ち）`

## S04 - アクションカードにフラグマークを追加

### Purpose

* アクションダッシュボードの各カードで、スレッド内のいずれかのメールにOutlookのフラグがアクティブ設定されている場合に、それを視覚的に示すマークを追加する。「🧩 R19Proj」バッジが表示される位置の右・タイトルの左に表示する。完了済みフラグは対象外とする。（マークはユーザー指示によりテキストなしのアイコンのみ、配色は視認性を考慮した淡い色に調整。）

### Work Completed

* 既存コードを調査し、`OutlookMailManager.group_by_thread`（`outlook_total_organizer_20260716_02.py` 1218-1269行）に、スレッド内いずれかのメールが`FlagStatus == 2`（Outlookのアクティブ設定フラグ。`OlFlagStatus`列挙で`olFlagMarked`に相当）であれば`True`になる`is_flagged`フィールドが既に算出されていることを確認した。完了済みフラグ（`FlagStatus == 1`、`olFlagComplete`）は対象外というロジックも既存実装ですでに満たされていた（`toggle_flag`/`remove_flag`の実装とも整合）。よって新規のフラグ判定ロジックは実装せず、既存の`is_flagged`をそのまま利用する方針とした。
* `outlook_total_organizer_20260716_02.py`をコピーして新バージョン`outlook_total_organizer_20260716_03.py`を作成し、以下を変更した。
  * `MailSummarizer.summarize_action_dashboard`: スレッドの`is_flagged`を`action_cards`の各カード辞書に追加。
  * `HTMLReportGenerator.generate_action_dashboard_report`: `is_flagged`から`flag_badge`（`<span class="badge bg-flag">🚩</span>`）を生成し、`.action-r19-wrap`の直後・タイトル(`topic_html`)の直前に`.action-flag-wrap`スロットとして挿入。CSSに`.bg-flag`と`.action-flag-wrap`（既存の`.action-cat-wrap`/`.action-r19-wrap`と同じ仕組みでタイトル位置を揃える固定幅スロット）を追加。
* 実装当初は「🚩 フラグ」というテキスト付きバッジ（幅70px、背景`#dc2626`の濃い赤）で実装したが、ユーザーから2度追加指摘を受けて修正した:
  1. 「フラグは、旗アイコンだけで十分。"フラグ"という記載は不要」との指摘を受け、テキストを削除しアイコンのみ（`🚩`）に変更。スロット幅も70px→30pxに縮小。
  2. 「赤に、赤旗は見えづらい」との指摘を受け、バッジ背景を濃い赤（`#dc2626`）から薄いピンク＋淡い赤枠（`background:#fef2f2; border:1px solid #fecaca;`）に変更し、🚩の赤色自体が視認できるようにした。
* カードヘッダー部分のHTML/CSSのみを抽出したスタンドアロンHTML（`flag_badge_test.html`）を作成し、Node版Playwright（`/opt/node22/lib/node_modules/playwright`をscratchpadに`node_modules`としてシンボリックリンクして利用）のヘッドレスブラウザで、「R19なし/フラグなし」「R19あり/フラグなし」「R19なし/フラグあり」「R19あり/フラグあり」の4パターンの表示とタイトル位置の整列を、上記2回の修正それぞれの後に再検証した。
* `outlook_total_organizer/CHANGELOG.md`の先頭に`VERSION 20260716_03`のエントリを追加。
* `docs/PROJECT_STATUS.md`を更新（新バージョンファイルの追加、アクションダッシュボード機能の記載、確定済み仕様への`is_flagged`追記、テスト方法・変更禁止ファイルの更新）。

### Files Changed

* `outlook_total_organizer/outlook_total_organizer_20260716_03.py`（新規。`_20260716_02.py`からのコピー＋フラグマーク追加）
* `outlook_total_organizer/CHANGELOG.md`（`VERSION 20260716_03`エントリを追加）
* `docs/PROJECT_STATUS.md`（新バージョンファイル・アクションダッシュボード機能・確定済み仕様・テスト方法・変更禁止ファイルの記載を更新）
* `docs/SESSION_HISTORY.md`（本ファイル。S04の記録を追記）
* `docs/NEXT_TASK.md`（S05向けに更新）

### Decisions

* フラグ判定ロジック（`FlagStatus == 2`をアクティブとする、`== 1`の完了済みは除外する）は、ユーザーが明示した「終了済みフラグは無視」という要件と、既存の`group_by_thread`の`is_flagged`実装が完全に一致していたため、新規ロジックを実装せず既存フィールドをそのまま再利用する方針とした（変更範囲の最小化）。
* 表示位置は、ユーザー指示「R19Projのタグが付く場所の右、タイトルの左」に忠実に従い、`.action-r19-wrap`（R19Projバッジのスロット）の直後、`topic_html`（タイトル）の直前に新しいスロット`.action-flag-wrap`を挿入した。
* R19Projバッジと同じ「非該当時も同幅の固定スロットを確保する」設計を踏襲し、フラグの有無でカード間のタイトル開始位置がずれないようにした。
* 絞り込み用のフィルタボタンは追加していない（ユーザー指示は表示のみを要求しており、フィルタ機能はスコープ外と判断）。
* バッジ表記（テキストなしアイコンのみ）と配色（薄いピンク背景）は、いずれもユーザーからの追加フィードバックに基づく変更であり、当初の実装（テキスト付き・濃い赤背景）から修正した。

### Tests

* `ast.parse`によるPython構文チェック（`outlook_total_organizer_20260716_03.py`、エラーなし）。
* `outlook_total_organizer_20260716_02.py`と`outlook_total_organizer_20260716_03.py`の`diff`により、意図した6箇所（`is_flagged`算出・カード辞書への追加、`flag_badge`生成、HTML挿入、CSS2箇所）のみが変更されていることを、テキスト削除・配色修正それぞれの後に確認。
* カードヘッダー部分のHTML/CSSを抽出したスタンドアロンHTMLをNode版Playwrightのヘッドレスブラウザで検証し、最終版（アイコンのみ・薄いピンク背景）で以下を確認:
  * R19なし・フラグなし: どちらのバッジも非表示、タイトルの開始位置が基準
  * R19あり・フラグなし: R19Projバッジのみ表示、タイトル開始位置は基準と一致
  * R19なし・フラグあり: フラグバッジのみ表示（R19Projバッジの位置に相当するスロットは空）、タイトル開始位置は基準と一致
  * R19あり・フラグあり: 両方のバッジが表示、タイトル開始位置は基準と一致
  * スクリーンショットでも位置関係（カテゴリ→R19Proj→フラグ→タイトルの順）を目視確認
* Outlook実データ・Gemini API・tkinter GUIを含むエンドツーエンドの実機テスト（実際にOutlookでメールにフラグを設定し、ダッシュボード生成でバッジが表示されることの確認）は、実行環境がLinuxコンテナのため未実施。

### Open Items

* 未実施: 実機（Windows＋Outlookインストール環境）での🚩マーク表示の動作確認（実際にフラグを付けたメールを含むスレッドでの表示、完了済みフラグのみのスレッドで表示されないことの確認を含む）。
* 未確認: `README.md`・`requirements.txt`の要否、本ツールの起動方法・必要な環境変数・主な利用者（S02から持ち越し）。
* 未確認: `claude/outlook-organizer-setup-nqzdo6`ブランチ（S01の成果物が存在する別ブランチ、未マージ）と本作業ブランチの関係整理（S02から持ち越し）。
* 未確認: `claude/outlook-date-range-expansion-k5zoeb`ブランチを今後どう扱うか（S03から持ち越し）。
* 未確認: フラグマークに絞り込みフィルタ（R19Projボタンのような）が必要かどうかは、ユーザーから明示的な要求がなかったため実装していない。要否は次回以降に確認。

### Next Session

* 次の作業: 未確定（ユーザーからの次のタスク指示を受ける）。実機テスト（S02・S03・S04分含む）の実施や、README.md/requirements.txtの整備などが候補。
* 次回の推奨タイトル: `Outlook オーガナイザー開発 S05 - （ユーザー指示待ち）`

## S05 - 統括コックピットv2刷新・四半期振り返りタブ新設

### Purpose

* S04終了時点でユーザー指示待ちだった状態から開始。本セッション中に依頼されたタスクは多岐にわたり、大きく次の3系統に分かれる。
  1. Outlook再起動連動の未読書き戻し機能、アクションタブの対象期間拡張（2〜6ヶ月）、アクションダッシュボードのカードレイアウト改善、R19Projタグ伝播不具合の修正。
  2. 統括コックピットv2の新規構築と、その後のユーザーフィードバックに基づく全面刷新（解放スコア廃止→異常種類分類、生体信号の畳み込み、スレッド重複解消、sticky見出し、確認済みボタン統一）。
  3. 四半期パフォーマンスレビュー用の新タブ「📈 振り返り」の新規構築（メール送信実績からAIで実績を抽出しMAG Leaderへの報告優先度を判定）と、実機テストで発覚した複数の不具合修正・機能追加。
* CLAUDE.mdのセッション管理ルールを「1タスク=1セッション」から「1つの明確な目的=1セッション」に変更（本セッション冒頭、コミット`ec113ba`）。これにより、本セッション内での追加依頼はすべて同じS05として扱われている。

### Work Completed

**系統1: 既存タブの改善（コミット`33187c9`〜`32c3ad9`、VERSION 20260716_04〜20260724_01）**
* `sync_forced_unread_from_outlook_state`等: Outlook再起動を検知したときだけ、フラグ/「Just Do It」タグ付き既読メールを未読に戻す機能を追加（VBA `ThisOutlookSession`の`Application_Startup`相当の処理を、ツール側でも再起動検知時に代行）。
* アクションタブの対象期間プルダウンに「2ヶ月」「3ヶ月」「6ヶ月」を追加。

**系統2: 統括コックピットv2（コミット`95fe442`まで、VERSION 20260724_02〜20260729_04）**
* 新コンセプトの統括コックピットv2を新規追加（`generate_cockpit_v2_data`/`generate_cockpit_v2_report`）。解放スコア（数値スコア方式）による優先順位付けから開始。
* 「✅完了」「🙈無視」ボタン、「🎨 フォーマットのみ再生成」ボタン、状態フィルタ・3択状態選択・受信日時表示・プロジェクト再分類UIを順次追加。
* R19Projタグがスレッド全体に反映されない不具合を修正（Option B: 軽量な全会話カテゴリ補完方式を採用）。
* アクションダッシュボードのカードレイアウトを複数回改善（件名の視認性確保、進捗ボタンの取り残され不具合修正、モックアップ確認を経た最終レイアウト確定）。
* 検索/整理タブの「未読のみ」検索が遅い問題を調査・修正（`items.Restrict`に`[UnRead] = True`を組み込み高速化）。
* 「📁 レポート管理」の「古いレポートの一括クリーンナップ」不具合を修正（glob パターンの誤り）。
* **統括コックピットv2を全面刷新**（VERSION 20260729_03、ユーザーへ5点の改善案を提示し承認を得て実装）: (A)解放スコア廃止→「異常の種類」5カテゴリ分類、(B)生体信号を異常時のみ表示、(C)複数プロジェクトにまたがるスレッドの重複表示解消、(D)見出しのsticky化、(E)Outlookボタン廃止（クリックで開く方式に統一）。操作を「✅ 確認済み」1つに統一し、`cockpit_v2_acknowledged.json`で管理（アクションタブの進捗とは非連動）。
* 「プロジェクト別」ビューを、各プロジェクトの下階層でも「種類別」と同じ5カテゴリに再分類するよう変更（VERSION 20260729_04）。

**系統3: 四半期振り返りタブの新規構築と修正（コミット`c6a6b77`〜`dc04c76`、VERSION 20260729_05〜20260730_05）**
* 新タブ「📈 振り返り」を新規構築（VERSION 20260729_05）: 自分が送信したメール（実行・判断したこと）を主データ源にする点が既存タブと根本的に異なる。オンラインアーカイブ横断のメール/予定表取得、L2機械フィルタ（`review_activity_qualifies`）、AIによる複数スレッド→「実績」への統合（`summarize_review_month`）、ゴール(G1プロジェクト遂行/G2サイト基盤整備/G3 R04フロー適合)分類、Tier1(MAG Leader等)/Tier2(横のカウンターパート)判定による報告ランク(S/A/B)付け、月次キャッシュ、手動編集機能を実装。
* ステータスバーに進捗表示`[現在/合計 (割合%)]`を追加（VERSION 20260729_06）。あわせて、進捗表示の括弧がタイマー表示のパース処理と衝突しメッセージが切り詰められる不具合を発見・修正。
* **実機テストで「6か月サマリで5月以降しか取得できない」と報告を受け調査**。専用の診断スクリプト`diagnose_archive.py`を新規作成し段階的に原因を特定。オンラインアーカイブの検出自体は正しく動作していたが、現行メールボックス直下にOutlookの「アーカイブ」ボタンで手動退避されたメール（18,991件、受信・送信混在）を溜めている別フォルダがあり、`get_review_mails_for_month`がこれを一切見ていなかったことが根本原因と判明。「アーカイブ」「Archive」「Go2Archive」の名称パターンを横断的に探索するよう修正（VERSION 20260730_01）。
* **「取り直すたびに結果が消える」不安定さを調査・修正**: AI呼び出し失敗時も成功時と同じ形式でキャッシュされ、過去月は無条件再利用されるため、レート制限等で偶発的に失敗した月が「実績0件」として恒久固定される不具合を発見。`_error`フラグを導入し、エラー月は必ず再試行されるよう修正（VERSION 20260730_02）。
* **UIを「対象期間(直近Nか月)」から「対象月チェックボックス」方式に変更**（VERSION 20260730_03）。あわせて、annotate処理を`summarize_review_month`側に統合し、キャッシュだけから最終レポートを組み立てられるよう内部構造を変更。
* ユーザーからのランキング設計フィードバックを受け、**ランクを4段階(S/A/B/🔵進行中)に変更**し「進行中」と「完了だがゴール外」を分離。**スタッフ(部下)の成果反映機能を追加**（VERSION 20260730_04）: L2機械フィルタを拡張し「登録スタッフが送信し自分がTo/Ccに含まれるスレッド」も対象化。スタッフ俯瞰タブの`project_knowledge["staffs"]`登録名をそのまま参照（読み取り専用、書き込みなし）。
* **チェックした月が既存キャッシュにより実際には更新されない不具合を修正**: `force_refresh`引数を追加し、チェックされた月は既存キャッシュの状態に関わらず必ず強制再分析するよう変更（VERSION 20260730_05）。
* **【未完了・未コミット】** 手動追加項目が月別タイムラインで常に固定文字列「手動追加」として扱われ、完了日を入力しても時系列上どこに属すか分からない不具合をユーザーが発見。`outlook_total_organizer_20260730_06.py`として修正コードを作成しコンパイル確認まで完了したが、**標準テスト・納品（SendUserFile）・コミットのいずれも未実施**のままセッション終了処理に入った。

### Files Changed

* `CLAUDE.md`（セッション管理ルールを「1タスク=1セッション」から「1つの明確な目的=1セッション」に変更）
* `outlook_total_organizer/outlook_total_organizer_20260716_04.py`〜`outlook_total_organizer_20260730_05.py`（本セッション中に新規追加した全リビジョンファイル。詳細はCHANGELOG.mdの各VERSIONエントリを参照）
* `outlook_total_organizer/outlook_total_organizer_20260730_06.py`（**未コミット・未検証・未納品**。手動追加項目の月別タイムライン日付表示バグ修正）
* `outlook_total_organizer/CHANGELOG.md`（各VERSIONエントリを追加）
* `outlook_total_organizer/diagnose_archive.py`（新規。アーカイブ検出調査用のスタンドアロン診断スクリプト。本体とは別ファイルでバージョン管理対象外）
* `docs/PROJECT_STATUS.md` / `docs/SESSION_HISTORY.md` / `docs/NEXT_TASK.md`（本セッション終了処理として更新）

### Decisions

* 統括コックピットv2は数値の加重和スコア方式を明確に失敗と判断し、「異常の種類」による分類方式へ全面転換した。振り返りタブの報告ランク付けでも、同じ失敗を繰り返さないよう、最初から加重和ではなく決定木＋根拠チップ方式を採用した。
* 振り返りタブの主データ源は「自分が送信したメール」（＝実行・判断したこと）とし、既存タブ（受信メールへの対応が中心）とは根本的に性質が異なる設計とした。
* スタッフ（部下）の成果は、新しい名簿を作らず既存の「スタッフ俯瞰」タブの登録(`project_knowledge["staffs"]`)を読み取り専用で流用する方針とした（二重管理を避けるため）。振り返りタブはスタッフ俯瞰タブのデータを一切更新しない。
* 振り返りタブの月次キャッシュ(`analysis_cache/review_monthly/*.json`)は、「過去の月は内容が変わらない」という前提で無条件再利用する設計を維持しつつ、(1)エラー結果は例外的に必ず再試行、(2)チェックボックスで明示的に選ばれた月は`force_refresh`で必ず再分析、という2つの例外を設けることで、キャッシュの効率性とユーザーが求める確実な更新の両立を図った。
* Tier1(Javed=MAG Leader, Thomas=BG Leader)/Tier2(Alber=PM Mgr, John=SE Mgr, Alex=TE Mgr, Ulysis=PE Mgr)はいずれも横・上のカウンターパートであり、Ochi氏が直接統括するスタッフ(Nakai=PM, Saji=TE, Oi Yuto=PE/VE兼任, Najib=PE, Kajikawa=Admin)とは別軸の関係であることをユーザーとの対話で確定した。

### Tests

* 本セッション中の全リビジョンについて、`ast.parse`構文チェックと直前リビジョンとの`diff`による変更範囲確認を実施済み（詳細はCHANGELOG.mdの各VERSIONエントリの「動作確認時の注意」を参照）。
* 振り返りタブの純粋関数群（Tier/G2分類・ランク決定木・機械フィルタ・スタッフ検出・キャッシュのforce_refresh挙動等）は、Outlook/Gemini非依存のスタンドアロン`python3`ハーネスで多数のテストケースを検証し全て合格。
* HTML/CSS/JSを含む変更（統括コックピットv2・振り返りタブのレポート画面）は、生成HTML断片をPlaywrightのヘッドレスブラウザで検証済み。
* **本ツールはWindows専用（win32com依存）のため、本セッションの実行環境（Linuxコンテナ）ではOutlook実機・Tkinter GUIでの実行・動作検証は一度もできていない**。実機での挙動はすべてユーザー側での確認結果（本セッション中に複数回、実際にWindows環境で実行した結果を報告いただき、それに基づいて調査・修正した）に依存している。
* `outlook_total_organizer_20260730_06.py`（未コミットの手動追加バグ修正）は、`ast.parse`構文チェックのみ実施し、diff確認・スタンドアロンテスト・Playwright検証・実機確認のいずれも未実施。

### Open Items

* **`outlook_total_organizer_20260730_06.py`が未完了**: 手動追加項目の月別タイムライン表示バグ修正はコンパイル確認のみで、テスト・納品・コミットが未実施。次セッションで最初に対応が必要。
* 振り返りタブの実機確認事項（累積、CHANGELOG.md各VERSIONの「動作確認時の注意」参照）:
  * `analysis_cache/review_monthly/*.json`のうち、スタッフ成果annotate機能（VERSION 20260730_04）追加前に生成されたキャッシュは、該当月をチェックして再生成しない限りスタッフチップ・ランクに反映されない。
  * スタッフ名簿(`project_knowledge["staffs"]`)の登録名と、実際のOutlook送信者表示名(`SenderName`)の表記ゆれ（未確認、検出漏れの可能性）。
  * オンラインアーカイブのストア検出（`ExchangeStoreType`判定・表示名フォールバック）、手動アーカイブフォルダの名称パターン（アーカイブ/Archive/Go2Archive）が他のOutlook環境でも同様に機能するか。
  * `IncludeRecurrences`による定例会議展開、`MeetingStatus`による主催者判定の妥当性。
* 統括コックピットv2の実機確認事項: 実際のデータでの分類結果の妥当性、`cockpit_v2_acknowledged.json`の永続化、複数プロジェクトの重複解消効果。
* S02〜S04から持ち越しの未確認事項（`README.md`/`requirements.txt`の要否、本ツールの起動方法・環境変数、未使用ブランチの整理）は、本セッションでも対応していない。

### Next Session

* 次の作業:
  1. `outlook_total_organizer_20260730_06.py`（手動追加項目の月別タイムライン日付表示修正）のテスト（diff確認・スタンドアロンテスト・Playwright検証）を完了し、ユーザーへ納品する。
  2. ユーザー承認後、コミット・Push（本セッションの慣例により、明示的な指示があるまで実施しない）。
  3. 以降は未確定（ユーザーからの次のタスク指示を受ける）。
* 次回の推奨タイトル: `Outlook オーガナイザー開発 S06 - 振り返りタブ手動追加日付バグ修正の完了と後続対応`


---

# Document Search Manager 開発

## Session Index

| Session | Title | Date | Status | Main Files |
| ------- | ----- | ---- | ------ | ---------- |
| S01 | Document Search Manager 開発 S01 - Phase 1 SharePoint全社検索の実装と開発資産の整備 | 2026-09-03 | 完了 | document_search_manager/document_search_manager_20260903_08.py, document_search_manager/DESIGN_NOTES.md, document_search_manager/tests/ 一式, document_search_manager/README.md, document_search_manager/CHANGELOG.md, .claude/skills/document-search-tool-dev/SKILL.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md |
| S02 | Document Search Manager 開発 S02 - Phase 2 Nexus検索の追加と系統別タブ化 | 2026-09-03 | 完了 | document_search_manager/document_search_manager_20260903_16.py, document_search_manager/old/ (_09〜_15), document_search_manager/tests/test_09〜test_14, document_search_manager/tests/ui_check.py, document_search_manager/README.md, document_search_manager/CHANGELOG.md, document_search_manager/DESIGN_NOTES.md, document_search_manager/config.example.json, document_search_manager/run_document_search_manager.bat, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md |

## S01 - Phase 1 SharePoint全社検索の実装と開発資産の整備

### Purpose

* 社内の3つのドキュメント管理系（SharePoint / Nexus / Enovia）を同一キーワードで
  横断検索するツールを新規開発する。段階開発とし、本セッションでは
  **Phase 1（SharePoint全社検索）** を完成させる。
* あわせて、Phase 2以降で再利用できるよう、調査知見と検証資産を整備する。

### Work Completed

1. **Phase 1 設計提案 → Phase 2 設計監査 → Phase 3 実装**の3フェーズで進行。
   越智さんの承認を得てから実装に着手した。
2. 調査（越智さんの会社PCでのF12キャプチャ提供による）:
   * Nexus（Shareflex）の全文検索が SharePoint標準の `RenderListDataAsStream` ＋
     **`InplaceSearchQuery`** で実装されており、**SharePoint検索インデックス**を
     参照していることを確認。Phase 2 は Graph Search で等価に実現できる見込みが立った。
   * 同リクエストに MCAS が `McasUserAuth` 等を注入していることを確認。
     SharePoint REST の直接呼び出しは非現実的かつ権限追加が必要なため却下した。
3. 実装（`_20260903_01` 〜 `_08` の8リビジョン）:
   * `_01`: Graph Search API による全社横断検索、Flask画面、Excel/CSV出力、疎通診断、
     プロバイダ抽象と並列実行（部分成功方式）
   * `_02`: 実機起動時の2件の不具合修正（batの文字化け、認証情報の流用元不足）
   * `_03`: タイトル・種別が全件空になる不具合の修正、件数選択肢の追加
   * `_04`: タイトル＝ファイルリンク、右端＝サイトリンクへのリンク配置変更
   * `_05`: 列ごとのソート、複数選択フィルタ、日付範囲フィルタ、一括ZIPダウンロード、
     作業状態の保持、旧バージョンの `old/` 自動退避
   * `_06`: フォルダ列の追加、フォルダの区別（案A）、Document Number 列の削除
   * `_07`: 拡張子誤認識の修正、フォルダ表示の短縮、OneDrive対応
   * `_08`: Excel出力のハイパーリンク化、件数表記の明確化
4. 開発資産の整備（`c8e4de4`）: 検証ハーネスのリポジトリ移設、`DESIGN_NOTES.md` の作成、
   開発手順のスキル化。

### Files Changed

* 新規: `document_search_manager/` 一式（本体8リビジョン、README、CHANGELOG、
  DESIGN_NOTES、config.example.json、requirements.txt、起動バッチ、tests/ 一式）
* 新規: `.claude/skills/document-search-tool-dev/SKILL.md`
* 変更: `.gitignore`（config.json / token_cache.json / session_state.json /
  cache/ / exports/ / downloads/ / tests/__pycache__ を除外）
* 変更: リポジトリ直下 `README.md`（本ツールの節を追加）

### Decisions

* **新規のEntra ID権限を申請しない**（越智さんの明確な指示）。既存アプリ登録を流用し
  `Sites.Read.All` のみで実装する。実機で `POST /search/query` が通ることを確認できたため、
  当初の最大リスクは解消した。
* **フォルダを除外せず「種別=フォルダ」として区別する（案A）。** フォルダ名にのみ
  キーワードが一致するケースを取りこぼさないため（越智さんの指摘により方針変更）。
* **フォルダ表示は既定ライブラリ名を `/` に短縮する。** 単純削除では直下の場合に
  空欄となり情報欠落と区別できないため（越智さんの指摘）。
* **拡張子判定を「英字始まり1〜10文字の英数字」に限定する。** 社内の
  `12. Validation` / `MRA2.0` のような命名規則との衝突を避けるため。
* **旧バージョンはリポジトリ側でも `old/` に置く。** ローカルの自動退避と構成を
  一致させないと `git pull` で旧版が復活して重複するため。
* **検証ハーネスはリポジトリ内に置く。** 一時領域にあるとセッション終了で失われるため。
  最新バージョンを自動検出する設計とし、版を上げてもテスト修正が不要にした。

### Tests

* `python tests/run_tests.py`: **268項目すべて合格**（ネットワーク・Graph API 非依存）。
  内訳: 検索の中核56 / 設定9 / fields27 / サイトリンク26 / 状態と一括DL42 /
  フォルダ41 / 拡張子とパス37 / Excel出力30。
* `python tests/ui_check.py`（Playwright）: **14項目すべて合格**。
  ソート、複数選択フィルタ、日付範囲、選択、再読み込み後の状態復元を実操作で確認。
* 検証中に**実バグを5件検出し修正**した:
  1. 未実装系統の単独指定がエラー扱いになる
  2. 絞り込みパネルがチェックのたびに閉じて複数選択できない
  3. 絞り込みパネルが横スクロール領域に切り取られ画面外にはみ出す
  4. 一括ダウンロードで対象未指定のときに全件が取得される
  5. （実機報告由来）拡張子の誤認識により番号付きフォルダがファイル扱いになる
* 会社PCでの実機確認: Graph疎通（`search-api` モード）、キーワード `validation` での
  検索、タイトル・種別・フォルダ列の表示までを越智さんに確認いただいた。

### Open Items

* **実機でのみ確認可能な未確認事項（2件）**:
  1. フォルダリンク（`Forms/AllItems.aspx?id=...`）が正しくフォルダを開くか。
     開かない場合は素のフォルダURL形式へ切り替える。
  2. 一括ダウンロード（`/shares/{token}/driveItem/content`）が成功するか。
     失敗時はZIP内の `_ダウンロード失敗一覧.txt` に理由が記録される。
* Phase 3（Enovia）の実装方式は未確定。F12キャプチャの取得が必要。
  会社PCでPlaywrightが使えるかも未確認。

### Next Session

* 次の作業: **Phase 2（Nexus検索の追加）**。設計は確定済み（`DESIGN_NOTES.md` 3-1）。
* 次回の推奨タイトル: `Document Search Manager 開発 S02 - Phase 2 Nexus検索の追加`

## S02 - Phase 2 Nexus検索の追加と系統別タブ化

### Purpose

* **Nexus（Shareflex / SF_QualityDocumentsProd）検索を実装**し、`2. Nexus` と
  `0. All` から使えるようにする（Phase 2。設計は S01 で確定済み）。
* セッション中に越智さんから追加要望を受け、**Phase 2.5** として
  系統別タブ・Nexus標準Indexの表示・Nexusリンクの実用化・有効期限の表示まで実施した。

### Work Completed

`_20260903_09` 〜 `_16` の8リビジョン。

1. `_09` **Nexus検索の実装**。`NexusProvider` を `SharePointProvider` の継承として
   実装し、Graph の `/search/query` に `path:` 制限付きKQLを渡す方式。
   親クラスに4つのフック（`_query_string` / `_search_fields` / `_fallback_sites` /
   `_degrade_fields`）を設け、既知の罠への対策をNexus側にも自動的に効かせた。
2. `_10` **系統別タブ構成**（越智さんの要望）。`COLUMN_SETS` をタブごとに切り替え、
   Nexusタブに標準Indexの枠を用意。Nexus行のフォルダ・サイト列を廃止。
   「Nexus検索診断」を追加。
3. `_11` **件数不一致の原因確定**と **HTTP 500 の修正**。
4. `_12` **人物列のID解決**と**「タイトルだけを検索する」**（既定オン）の追加。
   各Index列に「値の出所（内部列名）」をツールチップ表示。
5. `_13` **「Nexusで開く」を列フィルタ方式に修正**（`@qmDocumentNo=`）。
6. `_14` **人物列が行によって空欄になる不具合の修正**（並行処理）。
   「Nexus列診断」を追加。
7. `_15` 実機の列診断結果を反映。**対応づけの確定**と、氏名が既に取れている列の
   引き当て省略。
8. `_16` **有効期限の列**を最終更新日の右に追加（期限切れ／まもなくのバッジ付き）。

### Files Changed

* 新規: `document_search_manager/document_search_manager_20260903_16.py`
* 移動: `_09`〜`_15` を `old/` へ（削除せず保持）
* 新規: `tests/test_09_nexus.py` / `test_10_nexus_index_and_tabs.py` /
  `test_11_timeout_and_fields.py` / `test_12_people_resolution.py` /
  `test_13_people_concurrency.py` / `test_14_expiry.py`
* 変更: `tests/test_01` / `test_06` / `ui_check.py`（仕様変更に伴う期待値の更新）
* 変更: `README.md` / `CHANGELOG.md` / `DESIGN_NOTES.md` /
  `config.example.json` / `run_document_search_manager.bat`
* 変更: `docs/PROJECT_STATUS.md` / `docs/SESSION_HISTORY.md` / `docs/NEXT_TASK.md`

### Decisions

* **Nexusの絞り込みは `path:` でフォルダ限定**。推測ではなく**実測で確定**した
  （`validation plan`: ①フォルダ限定117件 ≒ Nexus画面116件、②サイト限定297件、
  ③限定なし126,090件）。この比較のために「Nexus検索診断」を先に作った。
* **件数不一致（14件 vs 116件）の原因は入力の非対称**だった。ツール側にだけ
  引用符付きで入力されており、完全一致のフレーズ検索になっていた（④で14件を再現）。
  **検索ロジックは変更せず**、引用符が含まれる場合に警告を出す形にした。
* **タブは案A（列定義だけを切り替える）**。表を2本持つと保守コストが倍になり、
  必ず片方が腐るため。列構成は「実際に検索した系統」に追従させる。
* **Nexusタブにサイト・フォルダ列を出さない。** Shareflexのフォルダ名は
  `3E08-CD5F` のような内部ハッシュで情報価値がゼロのため。
* **標準Indexはリスト項目の `fields` から取る**（`/shares/.../driveItem?$expand=...`）。
  検索マネージドプロパティ名はテナントごとに違い推測できず、外すと検索全体が
  HTTP 400 になるため。内部名の揺れは正規化して突き合わせる。
* **「Nexusで開く」は列フィルタ `@qmDocumentNo=`**。全文検索では他文書の本文に
  ある参照文献番号にも当たり1件に絞れない（越智さんの指摘）。
* **有効期限は日付から判定する。** `qmStatus = Expired` と `qmStatusEn = Valid` が
  食い違っていたため。矛盾する2値のどちらかを選ぶのではなく、自分で導出できる
  根拠に切り替え、元の値は参考として残す。
* **重複排除はNexusを検索したときだけ。** `1. SharePoint` 単独で除外すると
  Nexus文書がどこにも出ない取りこぼしになるため。

### Tests

* `python tests/run_tests.py`: **570項目すべて合格**（ネットワーク非依存）。
  S01の268項目から302項目の増加。新規は
  test_09(50) / test_10(96) / test_11(32) / test_12(46) / test_13(32) / test_14(42)。
* `python tests/ui_check.py`（Playwright）: **34項目すべて合格**。
  タブ切替による列構成の変化、Nexus標準Index、有効期限バッジを実操作で確認。
* **検証・実機で実バグを6件検出し修正**した:
  1. `ui_check.py` がNexus実装後に**実際のGraphを呼びに行く**状態だった
     （会社PCで本物の結果がダミーに混ざる）
  2. **HTTP 500 で検索結果が丸ごと失われる**（`as_completed` のタイムアウトを
     捕まえておらず、間に合った系統の結果まで捨てていた）
  3. **Nexus行のリンクが機能しない**（SharePoint標準のフォルダビューを張っており、
     Shareflexが数秒後にトップへ強制遷移させていた）
  4. **Doc Author / Doc Owner に別の役割の人が表示されていた**
     （数値IDを採用しない判断が裏目に出て、`nxDocReviewer` / `qmApprover` に
     フォールバックしていた）
  5. **人物列が行によって空欄になる**（並行処理でキャッシュに「空の途中結果」を
     置いていた。6スレッド中5本が空欄になることを再現確認）
  6. 常に真になってしまう検証を1件（自分で書いたもの）発見し、書き直した
* 会社PCでの実機確認: Nexus疎通🟢、`validation plan` で117件、`FMEA` で
  タイトル限定7件、Index 7列の表示、NDS-00072 の Doc Author / Doc Owner が
  Nexus画面と一致すること。

### Open Items

* **v20260903_16 の実機確認（有効期限の表示と期限切れバッジ）が未実施。**
* Phase 1 から残る実機未確認2件（フォルダリンクの到達性、一括ダウンロードの成否）。
* Phase 3（Enovia）の実装方式は未確定。**F12キャプチャの取得が必要。**
* ユーザー情報リスト（`User Information List`）は HTTP 404 で参照できない。
  現状は人物列の氏名が直接返るため影響しないが、氏名が返らない列が出た場合は
  空欄のままになる。

### Next Session

* 次の作業: **Phase 3（Enovia検索の追加）**。
  **実装前に、Enoviaで検索を1回実行したときのF12キャプチャを越智さんに依頼する。**
* 次回の推奨タイトル: `Document Search Manager 開発 S03 - Phase 3 Enovia検索の追加`

