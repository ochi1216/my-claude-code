# Project Status

> このリポジトリは複数プロジェクトを1つのリポジトリで管理しているため、
> プロジェクトごとに節を分けて記載する。

---

# Outlook オーガナイザー開発

## 1. Project Overview

* プロジェクト名: Outlook オーガナイザー開発
* プロジェクトの目的: Microsoft Outlook（win32com経由のローカルOutlookクライアント）のメールを解析し、対応が必要なアクション項目をダッシュボード化するツール（`outlook_total_organizer`）の継続開発。S05では、既存の「受信メールへの対応」中心の機能群に加えて、統括コックピットv2（異常検知）と、四半期パフォーマンスレビュー用の「振り返り」タブ（自分の実行・判断の実績を報告優先度付きで可視化）を新規構築した。
* 主な利用者: ユーザー本人（Japan Site Manager／Engineering Managerとして、TE/PE/PM/VE/Adminの各機能を統括する立場）。四半期パフォーマンスレビューでMAG Leader(上司)へ報告する用途を含む。
* 実行環境: Windows上のローカルOutlookクライアント＋Python（`win32com`使用のためWindows専用）。Gemini API（`google-genai`）でメール内容を解析。開発・検証環境（Claude Code Web、Linuxコンテナ）ではOutlook実機・tkinter GUIを直接実行できないため、実機での動作確認は毎回ユーザーに依頼している。

## 2. Repository Structure

* 主要ファイル（リポジトリ直下）
  * `README.md`: リポジトリ全体の概要と、各ツールの開発ルール（バージョン管理・命名規則）を記載
  * `CLAUDE.md`: Claude Code Web セッション運用ルール（S05冒頭で「1タスク=1セッション」から「1つの明確な目的=1セッション」に変更）
  * `HANDOVER_youtube_summary_list.md`: YouTube Summary List ツールの引継ぎ資料
  * `youtube_summary_list_20260703_01.py`, `youtube_summary_list_20260711_01.py`: YouTube Summary List ツール本体（バージョン別）
* 主要フォルダ（`outlook_total_organizer/`以外は本プロジェクトと無関係、変更禁止）
  * `po_database_organizer/`: PO Database Organizer
  * `rtocs_organizer/`: BBT RTOCS Organizer
  * `shareflex_dashboard/`: Shareflex Document Dashboard
  * `outlook_total_organizer/`: Outlook オーガナイザー本体
    * **最新（コミット済み）リビジョン: `outlook_total_organizer_20260730_05.py`**（約10,460行）
    * **`outlook_total_organizer_20260730_06.py`が存在するが未コミット・未検証・未納品**（手動追加項目の月別タイムライン日付表示バグ修正。詳細は本ファイル5節・6節、および`docs/NEXT_TASK.md`参照）
    * それ以前の全リビジョンファイル（`_20260713_03_01.py`〜`_20260730_05.py`）は削除・上書きせずそのまま保持（バージョン管理方針）
    * `diagnose_archive.py`: オンラインアーカイブ検出調査用のスタンドアロン診断スクリプト（S05で新規作成）。本体のバージョン管理対象外（`_yyyymmdd_NN.py`形式ではない）
    * `run_outlook_total_organizer.bat`: Windows起動用バッチファイル
    * `CHANGELOG.md`: ツールの変更履歴（2026-05-07分から記録。最新は`## VERSION 20260730_05`）
  * `docs/`: セッション引継ぎ管理ファイル（`PROJECT_STATUS.md`本ファイル・`SESSION_HISTORY.md`・`NEXT_TASK.md`）

## 3. Current Functions

`MailManagerGUI`（tkinterベースのGUI）は6タブ構成:

1. **🔍 検索/整理**: メール検索・整理（`search_mails_fast`）。「未読のみ」検索の高速化済み（S05でRestrict直書き化）。
2. **📊 プロジェクト俯瞰**: プロジェクト単位のAI要約レポート（`generate_project_report`）。
3. **👤 スタッフ俯瞰**: スタッフ単位のAI要約レポート（`generate_staff_report`）。登録スタッフ名は`project_knowledge["staffs"]`（キー=スタッフ名）。振り返りタブがこの登録名を読み取り専用で参照する（詳細は後述）。
4. **🚀 統括コックピット**（v1・v2両方を保持。v2が主）:
   * v2（`generate_cockpit_v2_data`/`generate_cockpit_v2_report`）はS05で全面刷新済み。数値の「解放スコア」方式を廃止し、🔥催促されている／🧊相手が止まっている／🕰長期沈黙／📈急に燃えている／📥自分待ち、の5カテゴリで分類する方式に変更。生体信号は異常時のみ表示。複数プロジェクトにまたがるスレッドの重複は`conversation_id`単位で統合（「+N」バッジ）。操作は「✅ 確認済み」1つに統一し`cockpit_v2_acknowledged.json`で管理（アクションタブの`action_status.json`とは非連動）。「種類別」「プロジェクト別」の2ビューを切替可能（プロジェクト別も内部で5カテゴリにサブグループ化）。
5. **📋 アクション**（アクションダッシュボード）: `summarize_action_dashboard`。R19Projフィルタ（3状態）、🚩フラグマーク、カードレイアウトは複数回改善済み。
6. **📈 振り返り**（**S05で新規構築**、四半期パフォーマンスレビュー用）:
   * 既存タブが「受信メールへの対応」を扱うのに対し、唯一「自分が送信したメール（＝実行・判断したこと）」を主データ源にする。
   * 対象月は「対象期間(直近Nか月)」ではなく、**当年1月〜当月の月別チェックボックス**で選ぶ（S05途中でユーザー要望により変更）。チェックした月は既存キャッシュの有無に関わらず必ず強制的に再取得・再分析（`force_refresh`）。チェックを外した月は`analysis_cache/review_monthly/{YYYYMM}.json`のキャッシュをそのまま使う。
   * メール取得（`OutlookMailManager.get_review_mails_for_month`）は、現行メールボックスに加えて**オンラインアーカイブ**（`_find_online_archive_root`、`ExchangeStoreType==3`判定＋名前パターンのフォールバック）、および現行メールボックス直下にユーザーが手動で退避させた**「アーカイブ」「Archive」「Go2Archive」等の名前パターンのフォルダ**（`_find_manual_archive_folders`、`MANUAL_ARCHIVE_FOLDER_NAMES`）も横断的にスキャンする。
   * L2機械フィルタ`review_activity_qualifies`: 自分の送信メール基準の判定に加え、**登録スタッフ（部下）が送信し自分がTo/Ccに含まれるスレッド**も対象化（マネジメント成果の可視化）。
   * `summarize_review_month`でAIが複数スレッドを「実績」単位に統合。Tier1(Javed=MAG Leader, Thomas=BG Leader)/Tier2(Alber=PM Mgr, John=SE Mgr, Alex=TE Mgr, Ulysis=PE Mgr)関与判定、G2(サイト基盤整備)の機能別小分類、スタッフ関与検出(`REVIEW_STAFF_FUNCTIONS`)、報告ランク判定まで、この関数内でannotateしてキャッシュする。
   * 報告ランクは**4段階（S/A/B/🔵進行中）**の決定木: 成果未確定→🔵進行中／ゴール(G1〜G3)に非紐付け→🅑B／Tier1関与・Tier2 2名以上・Japan Site全体・定量効果・スタッフの成果を牽引のいずれかでS、無ければA。加重和スコアは使わない（統括コックピットv1の反省を踏襲）。
   * 表示は「ゴール別(既定)」「プロジェクト別」「月別タイムライン」の3軸切替。手動追加（会議・口頭判断等）・非表示・ランク変更・文言修正が可能（`review_manual_items.json`、`/update_review_manual`エンドポイント）。
   * **既知の未修正バグ**: 手動追加項目の月別タイムライン表示が常に固定文字列「手動追加」になり、入力した完了日が使われない（`_06`で修正コード作成済み、未検証・未コミット。詳細は5節・6節）。

## 4. Confirmed Specifications

* 確定済みの仕様（S05で新規確定分）:
  * 振り返りタブのTier1/Tier2は「上」「横」のカウンターパートであり、Ochi氏が直接統括するスタッフ（Nakai=PM, Saji=TE, Oi Yuto=PE/VE兼任, Najib=PE, Kajikawa=Admin）とは別軸。スタッフ名簿は新設せず`project_knowledge["staffs"]`を読み取り専用で参照する（振り返りタブからスタッフ俯瞰タブのデータを書き換えることは一切ない）。
  * 振り返りタブのランクは加重和スコアではなく決定木＋根拠チップ方式（統括コックピットv1の数値スコア方式が実質2成分しか機能せず失敗した反省を踏襲）。
  * 振り返りタブの月次キャッシュは「過去月は無条件再利用」が原則だが、(1)AI呼び出しエラー結果は例外的に必ず再試行、(2)チェックボックスで明示的に選択された月は`force_refresh`で必ず再分析、という2つの例外がある。
  * バージョンファイル命名規則: `outlook_total_organizer_yyyymmdd_NN.py`（S03以降。末尾`_01`なし）。日付が変わったらNNは01にリセット。
* 維持すべき設計方針:
  * バージョンアップ時に旧ファイルを削除・上書きしない
  * 各バージョンのCHANGELOGエントリに「変更しないこと（宣誓）」を明記する
  * コミット・Pushはユーザーの明示的な指示があった場合のみ行う（Stop hookの自動リマインダーは指示ではない）

## 5. Current Status

* 完了済み（コミット・Push済み。詳細は`docs/SESSION_HISTORY.md`のS05セクション参照）:
  * S01〜S04: 引継ぎ管理初期設定、R19Projフィルタ、対象期間拡張、フラグマーク追加
  * S05: Outlook再起動連動の未読書き戻し、統括コックピットv2の新規構築と全面刷新、四半期振り返りタブの新規構築、および振り返りタブの実機テストで発覚した複数の不具合修正（アーカイブ検出、キャッシュのエラー握りつぶし、チェックボックスUI化、4段階ランク、スタッフ成果反映、force_refresh）
  * 最新コミット: `dc04c76`（`outlook_total_organizer_20260730_05.py`）
* **作業中（未完了）**:
  * `outlook_total_organizer_20260730_06.py`: 振り返りタブの手動追加項目が月別タイムラインで日付を無視し常に「手動追加」にまとめられる不具合の修正。`ast.parse`構文チェックのみ実施済み。**diff確認・スタンドアロンテスト・Playwright検証・ユーザーへの納品（SendUserFile）・コミットのいずれも未実施**。
* 未着手:
  * `README.md` / `requirements.txt`の整備（他ツールと同様の体裁にするか未確認）
  * S02〜S04から持ち越しの各種未確認事項（起動方法、環境変数、未使用ブランチの整理）

## 6. Known Issues

* 未解決の既知の問題:
  * `outlook_total_organizer_20260730_06.py`が未完了（上記5節参照）。次セッションで最優先対応。
  * スタッフ名簿(`project_knowledge["staffs"]`)の登録名と、実際のOutlook送信者表示名(`SenderName`)の表記ゆれが未確認（表記が一致しないとスタッフ成果の検出漏れが起きる）。
  * `analysis_cache/review_monthly/*.json`のうち、スタッフ成果annotate機能（`_20260730_04`）追加より前に生成されたキャッシュは、該当月をチェックして再生成しない限りスタッフチップ・ランクに反映されない。
* 暫定対応: なし
* 技術的リスク:
  * 本ツールはWindows専用（`win32com`, `pythoncom`使用）のため、本セッションの実行環境（Linuxコンテナ）では実機起動テストが一度もできていない。実機での不具合報告（アーカイブ検出、キャッシュの不安定さ等）はすべてユーザーからの報告を受けて調査・修正する形で進めた。
  * オンラインアーカイブのストア検出（`ExchangeStoreType`が環境によって想定と異なる値を返すケースをS05で実際に確認済み。名前パターンのフォールバックで対応したが、他の未知のパターンが存在する可能性がある）。
  * 手動アーカイブフォルダの名称（アーカイブ/Archive/Go2Archive）は組織・ユーザーによって異なる可能性があり、`MANUAL_ARCHIVE_FOLDER_NAMES`に無い名称の場合は検出できない。

## 7. Test and Execution

* 起動方法: `run_outlook_total_organizer.bat`（Windows、Outlookインストール済み環境）。未確認事項: 必要な環境変数、APIキー設定手順の詳細。
* テスト方法（S05で確立したパターン）:
  * 全リビジョンで`ast.parse`構文チェック＋直前リビジョンとの`diff`による変更範囲確認を実施。
  * Outlook非依存の純粋関数（分類・判定・フィルタ・キャッシュロジック等）は、AST抽出によりスタンドアロンの`python3`ハーネスに切り出し、モックデータで検証。
  * HTML/CSS/JSを含む変更は、生成HTML断片をPlaywright（`/opt/pw-browsers/chromium`）のヘッドレスブラウザで検証。
  * 実機（Windows＋Outlook＋Gemini API＋tkinter GUI）でのエンドツーエンドテストは毎回未実施。ユーザーが実機で実行した結果（スクリーンショット・コンソール出力）を都度共有いただき、それに基づいて原因調査・修正するフローが定着している。
* 必要な環境変数: 未確認
* 外部サービスへの依存: Microsoft Outlook（win32com経由のローカルクライアント、オンラインアーカイブ含む）、Gemini API（`google-genai`）

## 8. Important Restrictions

* 変更禁止事項:
  * 本プロジェクトと無関係な既存プロジェクト（`po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/`, `youtube_summary_list_*.py` など）は変更しない
  * `outlook_total_organizer`内の既存バージョンファイルは削除・上書きしない（新しいリビジョンファイルとして追加する）
* セキュリティ上の注意:
  * 秘密情報、APIキー、パスワード、認証情報はコミットしない
* 運用上の注意:
  * コミット・Pushはユーザーの明示的な指示があった場合のみ行う。Stop hookの自動リマインダーは指示として扱わない。
  * プログラムコードを変更する場合は、必ず新しいリビジョンファイルを作成する（既存の確定済みリビジョンファイルを直接編集しない。S05中に一度この原則を誤ってやりかけ、gitから復元して是正した実例あり）。

---

# Document Search Manager 開発

## 1. Project Overview

* プロジェクト名: Document Search Manager 開発
* プロジェクトの目的: 社内の3つのドキュメント管理系（SharePoint / Nexus(Shareflex) /
  Enovia(3DEXPERIENCE)）を、**同一キーワードで横断検索**するツール
  (`document_search_manager/`) の開発。検索対象は `0. All`（既定）/ `1. SharePoint` /
  `2. Nexus` / `3. Enovia` から選択する。
* 主な利用者: 越智さん本人（Japan Site Manager）。必要な社内文書がどこにあるか
  分からず、3系統を個別に探し回っている状況の解消が動機。
* 実行環境: 会社PC（Windows）＋ Python。`http://127.0.0.1:5020` のFlask画面。
  開発・検証環境（Claude Code Web、Linuxコンテナ）では会社のSharePointに
  アクセスできないため、Graph API疎通・リンク到達性・一括ダウンロードの実動作は
  毎回越智さんに実機確認を依頼している。

## 2. Repository Structure

* `document_search_manager/`
  * **最新リビジョン: `document_search_manager_20260903_08.py`**（約1,700行）
  * `old/`: 旧リビジョン `_20260903_01.py` 〜 `_20260903_07.py`（削除せず保持）。
    ツール起動時に自分より古い版を自動でここへ退避する。リポジトリ側の構成も
    一致させてあるため `git pull` で旧版が復活して重複することはない。
  * `README.md`: 利用者向け（導入手順・画面の使い方・設定項目・トラブルシュート）
  * `CHANGELOG.md`: 変更履歴（`## VERSION 20260903_01`〜`_08`）
  * **`DESIGN_NOTES.md`**: 設計メモ・調査記録。**次に改修するときは最初にここを読む**
  * `config.example.json` / `requirements.txt` / `run_document_search_manager.bat`
  * `tests/`: 検証ハーネス（268項目）＋ `ui_check.py`（ブラウザ操作14項目）
* `.claude/skills/document-search-tool-dev/SKILL.md`: このツールの開発手順スキル

## 3. Current Functions

Flask画面（ダークテーマ bg `#1a1a2e` / accent `#e94560`）の構成:

1. **検索**: キーワード入力、検索対象の選択（0.All/1.SharePoint/2.Nexus/3.Enovia）、
   取得件数（関連度上位 10/25/50/100/200/500 件、既定10件）
2. **疎通診断**: 各系統が利用可能かを最小リクエスト1回で確認。
   SharePointは `search-api`（全社横断）/ `site-drive`（サイト単位）を自動判定する
3. **結果一覧**（列: ソース / タイトル / 選択 / 作成者 / 最終更新日 / 種別 / サイト /
   フォルダ）
   * タイトル＝ファイルへの直接リンク、サイト＝保管先サイト、フォルダ＝保管フォルダ
   * 列見出しクリックで昇順→降順→解除のソート
   * 見出しの「⋮」で列ごとの絞り込み。最終更新日は日付範囲（以降/以前）、
     それ以外はチェックボックスの複数選択
   * 選択チェックボックスで複数ファイルの一括ZIPダウンロード
4. **出力**: Excel（タイトル/サイト/フォルダのセル自体がハイパーリンク、
   オートフィルタ付き）/ CSV（URLを列として保持）。画面の絞り込み・並び順を反映する
5. **状態の保持**: 終了・再起動しても、前回の検索キーワード・対象・件数・並び順・
   絞り込み条件を復元する（結果は保存せず自動で再検索する）

## 4. Confirmed Specifications

* **新規のEntra ID権限を申請しない**（越智さんの明確な指示）。既存の
  `po_database_organizer` と同一アプリ登録を流用し、スコープは `Sites.Read.All` のみ。
  **`POST /search/query`（entityTypes: listItem）がこのスコープだけで通ることを
  実機で確認済み。**
* `tenant_id` / `client_id` は `config.json` が空なら既存ツールから自動借用する
  （探索順: `po_database_organizer` → `onenote_report_generator`、
  `credentials_from` で任意パス指定も可）。越智さんの環境では
  `C:\Users\nx023836\Documents\PythonScripts\SharePoint\PO_Matrix_manager\config.json`
  を `credentials_from` で参照している。
* **検索結果のフォルダは除外せず「種別=フォルダ」として区別する**（案A）。
  フォルダ名にキーワードが含まれる一方で中のファイルには含まれないケースでは、
  フォルダの存在そのものが情報になるため。
* **フォルダ列は `Shared Documents` などの既定ライブラリ名を `/` に短縮**して表示する。
  単純削除では直下の場合に空欄となり情報欠落と区別できないため。
* 拡張子とみなす条件は「英字で始まる1〜10文字の英数字」（例外 `7z`）。
  社内の `12. Validation` / `MRA2.0` のような命名を誤判定しないため。
* Document Number 列は表示しない（Enoviaでのみ必要。Phase 3 で復活させる）。
* 維持すべき方針: 旧バージョンを削除しない／認証・検索ロジックに不用意に触らない／
  コミット・Pushは明示的な指示があったときのみ。

## 5. Current Status

* **Phase 1（SharePoint全社検索）完了。会社PCで実動作を確認済み。**
* コミット済み最新: `c8e4de4`（開発資産の整備）。本体は `_20260903_08.py`。
* 検証: `python tests/run_tests.py` で **268項目すべて合格**。
  `tests/ui_check.py`（Playwright）で **14項目すべて合格**。
* **実機でのみ確認可能な未確認事項が2件残っている**:
  1. フォルダリンク（`Forms/AllItems.aspx?id=...`）が正しくフォルダを開くか
  2. 一括ダウンロード（`/shares/{token}/driveItem/content`）が成功するか
* 未着手: Phase 2（Nexus）、Phase 3（Enovia）、Phase 4（3系統統合の磨き込み）

## 6. Open Items

* Phase 2（Nexus）は**設計が確定済み**（`DESIGN_NOTES.md` 3-1参照）。
  Graph Search を `nexus_folder_path` に限定するだけで新規権限は不要。
* Phase 3（Enovia）は**未確認事項が残る**。実装前に、Enoviaでの検索時の
  F12キャプチャ（Network → Fetch/XHR）を越智さんに依頼する必要がある。
  会社PCでPlaywrightが使えるかも未確認。

---

# OneNote オーガナイザー開発

最終更新：S01（2026-07-24）

## Project Overview

OneNote上のプロジェクト議事録・進捗ページを Microsoft Graph API 経由で取得し、
Gemini AI で要約・構造化した上で、アコーディオン形式のリッチな HTML レポートを
自動生成する Flask アプリケーション。

- 開発者：越智さん（Nexperia Japan Site Manager）
- これまでの開発は claude.ai（Project Chat）上で行われており、GitHubリポジトリへの
  コミットは今回（S01）が初めて。実コードは S01 で越智さんからアップロードされた
  4ファイル（`.py` 本体・`templates/index.html`・`bookmarks.json`・`CHANGELOG.md`）を
  元に、本リポジトリ `onenote_report_generator/` フォルダへ導入した。

## Repository Structure

このリポジトリ（`ochi1216/my-claude-code`）は複数の社内ツールを1リポジトリで
管理するモノレポ。本プロジェクトが使用するのは以下。

```
onenote_report_generator/
├── onenote_report_generator_20260706_01.py   ← メインFlaskアプリ本体
├── templates/index.html                       ← VERSION 20260706_01_01
├── config.example.json                        ← 新規作成（config.jsonのテンプレート）
├── requirements.txt                            ← 新規作成
├── CHANGELOG.md                                ← 越智さんの引継ぎ資料から反映
├── README.md                                   ← 新規作成
├── bookmarks.json                              ← .gitignore対象（実行時生成・社内情報含む）
└── reports/                                    ← .gitignore対象（生成レポート格納）
```

他ツール（`po_database_organizer/`、`rtocs_organizer/`、`shareflex_dashboard/`、
`youtube_summary_list_*.py`）は本プロジェクトのスコープ外のため未確認。

## Current Functions

コード実物（S01でアップロードされたもの）から確認済み。

- **認証**：MSAL Device Code Flow（`OneNoteGraphExtractor`）。単一テナント
  （`CONFIG['TENANT_ID']`）・単一 `PublicClientApplication` を前提とし、
  トークンは `token_cache.bin` にキャッシュ。プロセスグローバル変数 `_token` で保持。
- **サイト/ノートブック/セクション/ページ取得**：Graph API 経由。
  `get_notebooks` / `get_sections` / `get_pages` / `get_page_html` はいずれも
  `site_id` を引数に取る設計（VERSION 20260512_03_01でconfig固定値から変更済み）。
- **複数サイト対応（同一テナント内）**：`/api/sites` エンドポイントが
  `config.json` の `sites` 配列（`displayName` + `site_id` のペア）をそのまま
  返却し、UI①のサイト選択ドロップダウンに反映される。**同一 Microsoft 365
  テナント内であれば複数サイトの追加・切替は既に可能**（コード確認済み）。
- **テキスト抽出**：`extract_with_color()` が HTML→テキスト変換を担当。
  青文字（RGB判定）を「更新ポイント」として抽出し、`<table>` は Markdown表形式
  （`| セル1 | セル2 |`）に変換してから物理削除（二重出力防止）。
- **Gemini解析**：`GeminiProcessor.analyze_html()` が前回ページとの差分を
  考慮しつつ、summary/updates/details/pending_actions の固定JSONスキーマで
  構造化データを返す。
- **レポート生成**：`ReportGenerator.generate_html()` がアコーディオン形式の
  ライトテーマHTML（白背景・青基調 #3498db）を生成。Gemini API概算費用も
  フッターに表示。
- **ブックマーク機能**：サイト・ノートブック・セクション・ページ選択状態を
  `bookmarks.json` に名前付きで保存/復元/削除（`GET/POST /api/bookmarks`、
  `DELETE /api/bookmarks/<id>`）。破損時は `.bak` にリネームして空データで
  自動復旧するフォールバックあり（`_load_bookmarks()` に実装済み、コード確認済み）。
- **レポート管理**：`/reports`（一覧）、`/reports/open/<filename>`（ローカル
  ブラウザで開く）、`/reports/cleanup`（7日以上前のレポート削除）。

## Confirmed Specifications

- UIはライトテーマ（白背景・青基調）で実装済み。ダークテーマの指定は別プロジェクト
  設定との混在の可能性があるとの申し送りがあり、本プロジェクトでは踏襲しない
  （引継ぎ資料に明記）。
- バージョン形式：`YYYYMMDD_連番_サブ番号`（例：`20260706_01_01`）をファイル名・
  `<title>` タグ双方に埋め込む。
- Flaskは `debug=False` 固定運用（認証トークン等の機微情報を扱うため）。
  コード変更後は手動でのプロセス完全停止＆再起動が必須（自動リロードなし）。

## Current Status

- S01時点：越智さんが実機（Windows/Chrome）で VERSION 20260706_01_01 の
  稼働を確認済み（引継ぎ資料記載）。
- S01でリポジトリへの初回コミット前段階（コードのリポジトリ導入・管理ファイル整備中）。
- 「別のOneNoteサーバー追加」要件について、Phase 1確認（引継ぎ資料6章の
  1〜3のどれに該当するか）は本セッションでこれから実施する（`docs/NEXT_TASK.md` 参照）。

## Known Issues

- ✅ **引継ぎ資料の記載を実機テストで訂正**：引継ぎ資料は「bookmarks.json破損時の
  自動復旧が実装コードに未反映」（🔴未解決）としていたが、S01でアップロードされた
  実コードには `_load_bookmarks()` に `.bak`リネーム＋空データ再生成のガードが
  既に実装されており、**実際にbookmarks.jsonをわざと壊した状態でFlaskテスト
  クライアント経由で動作確認したところ、クラッシュせず正常に復旧することを確認した**
  （S01テスト結果、`docs/SESSION_HISTORY.md`参照）。CHANGELOG.md上もVERSION
  20260529_01_01の時点で実装済みと記載されている。引継ぎ資料の当該記述は
  誤りだった可能性が高い（越智さんへの確認要）。
- 🔴 **未確認：`config.json` 破損時の起動失敗リスク**：`load_config()` は
  モジュール読み込み時に無条件で `json.load()` を呼んでおり、`config.json` が
  破損しているとFlask起動自体が失敗する（コード確認済み・実際にこの経路は
  未テスト）。bookmarks.json側のような復旧ガードは無い。
- 🟡 CHANGELOG.mdへの正式記載：引継ぎ資料の内容をそのまま反映済み（追加の
  記載整理は未実施）。
- 🟡 単一テナント/単一アカウント前提の認証設計：`_token` / `_extractor` は
  プロセスグローバル変数。複数ユーザー・複数テナントの同時アクセスには未対応。

## Test and Execution

S01で実施した範囲（`docs/SESSION_HISTORY.md`に詳細記録）：

- `python3 -m py_compile` による構文チェック（合格）
- `config.example.json` / `bookmarks.json`（アップロード分）のJSON妥当性チェック（合格）
- ダミー設定でのFlaskアプリ起動・全ルート登録確認、`GET /`・`GET /api/sites` の
  応答確認（合格。複数サイトがconfig.jsonの`sites`配列から正しく返ることを確認）
- ブックマークCRUD（POST/GET/DELETE）のFlaskテストクライアント経由での動作確認（合格）
- bookmarks.json破損時の自動復旧（`.bak`リネーム＋空データ再生成）の実地確認（合格）
- `extract_with_color()` のテーブルMarkdown変換・青文字更新ポイント抽出の単体確認（合格）

未実施（本リモートセッションでは実施不可）：

- 実際のMSAL Device Code Flow認証（Microsoft Entra ID実テナントが必要）
- 実際のGraph API呼び出し（ノートブック/セクション/ページ取得）
- 実際のGemini API呼び出し
- 越智さんの実機（Windows/Chrome）でのブラウザ動作確認

## Important Restrictions

- `bookmarks.json`（実データ）・`config.json`・`token_cache.bin` はコミット禁止
  （`.gitignore` 対象）。`bookmarks.json` には実際の会議名・プロジェクト名・
  SharePointサイトIDが含まれるため、公開リポジトリへの流出防止のため。
- 「他のOneNoteサーバー追加」の設計に着手する前に、Phase 1として越智さんへ
  要件確認を行うこと（引継ぎ資料で明示されたルール）。

---

# RSS オーガナイザー開発（移管済み）

> **⚠️ 2026-08-13 に `ochi1216/home-pc-workspace` の `rss-organizer/` へ移管しました。**
> 以後の開発・状況管理は移管先の `rss-organizer/docs/PROJECT_STATUS.md` で行います。
> このリポジトリの `rss_organizer/` は移管時点の記録であり、更新しません。

## 移管前の到達点（S01）

RSS/Atomフィードを複数ソースから収集し、Gemini APIで要約してHTMLレポートを生成する
Windows向けTkinterデスクトップツール。3タブ構成（キーワード探索／フォローnote／AI最先端フィード）。

S01では「AI最先端フィードが毎回大量に読み込まれる」問題に対応した。
実際の `ai_feed_history.json`（直近1週間・606件）を集計したところ、
arXiv 4フィードが全体の57%（345件）を占めており、これが主因と判明した。
Papers with Code は同期間0件で、Windows実機での `feedparser` 実行により
`SSLV3_ALERT_HANDSHAKE_FAILURE` でフィード自体が機能停止していることを確認した。

ユーザー判断により論文・研究カテゴリの取得を停止し、20フィード → 15フィードとした
（英語メディア5／AI企業・研究機関ブログ6／論文・研究0／日本語メディア4）。

## 移管後に行われた変更（このリポジトリには反映されていない）

- 会社PC依存のハードコードパス3箇所の外部化（出力先Summaryフォルダ、統合バッチ起動パス2箇所）
- 設定・履歴ファイルのスクリプト位置基準化
- Playwright がコンソールタイトルの非ASCII文字で起動できない問題への対処
- noteフォロー同期からのログイン処理の廃止（未ログインで閲覧可能と判明したため）
- 固定ファイル名＋Gitによるバージョン管理への移行（`rss_organizer.py`）

## 注意

`rss_organizer/` のコードには会社PCの絶対パスが残っている。
`mkdir(parents=True)` により実在しないユーザー名のフォルダが作られ、
エラーも出ないまま誤った場所へHTMLが出力されるため、他のPCで実行しないこと。
