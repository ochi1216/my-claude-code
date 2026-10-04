# Project Status

> このリポジトリは複数プロジェクトを1つのリポジトリで管理しているため、
> プロジェクトごとに節を分けて記載する。

---

# Outlook オーガナイザー開発

## 1. Project Overview

* プロジェクト名: Outlook オーガナイザー開発
* プロジェクトの目的: Microsoft Outlook（win32com経由のローカルOutlookクライアント）のメールを解析し、対応が必要なアクション項目をダッシュボード化するツール（`outlook_total_organizer`）の継続開発。S05では統括コックピットv2（異常検知）と四半期「振り返り」タブを新規構築した。S06では振り返りタブをスタッフ全員へ拡張し、会社PCからのGemini API直接遮断に対応するプロキシフォールバック移行、起動時にメイン画面を左右分割してOutlookと本ツールを自動配置する新機能を実装した。S07では「より今のニーズに合う形へのコード再構築（AIエージェント化）」に着手する予定（詳細未確定、`docs/NEXT_TASK.md`参照）。
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
    * **最新（コミット済み・PRマージ済み）リビジョン: `outlook_total_organizer_20260821_02.py`**
    * それ以前の全リビジョンファイル（`_20260713_03_01.py`〜`_20260821_01.py`）は削除・上書きせずそのまま保持（バージョン管理方針）
    * `diagnose_archive.py`: オンラインアーカイブ検出調査用のスタンドアロン診断スクリプト（S05で新規作成）。本体のバージョン管理対象外（`_yyyymmdd_NN.py`形式ではない）
    * `run_outlook_total_organizer.bat`: Windows起動用バッチファイル。`dir /b /o-n outlook_total_organizer_*.py`でファイル名の降順ソートにより常に最新リビジョンを自動選択して起動する（特定バージョンのハードコードなし）
    * `json/review_person_goals.json`: 振り返りタブのスタッフ別KPIゴール定義（S06で新設、Nexperia機密情報のため`.gitignore`対象）
    * `CHANGELOG.md`: ツールの変更履歴（2026-05-07分から記録。最新は`## VERSION 20260821_02`）
  * `docs/`: セッション引継ぎ管理ファイル（`PROJECT_STATUS.md`本ファイル・`SESSION_HISTORY.md`・`NEXT_TASK.md`）

## 3. Current Functions

`MailManagerGUI`（tkinterベースのGUI）は6タブ構成:

1. **🔍 検索/整理**: メール検索・整理（`search_mails_fast`）。「未読のみ」検索の高速化済み（S05でRestrict直書き化）。「期間」プルダウンが「任意時間(h)」以外のときは隣接するhスピンボックスをグレーアウトする（S06、`_bind_hour_spinbox_state`。プロジェクト俯瞰・スタッフ俯瞰タブも同様）。
2. **📊 プロジェクト俯瞰**: プロジェクト単位のAI要約レポート（`generate_project_report`）。
3. **👤 スタッフ俯瞰**: スタッフ単位のAI要約レポート（`generate_staff_report`）。登録スタッフ名は`project_knowledge["staffs"]`（キー=スタッフ名）。振り返りタブがこの登録名を読み取り専用で参照する（詳細は後述）。
4. **🚀 統括コックピット**（v1・v2両方を保持。v2が主）:
   * v2（`generate_cockpit_v2_data`/`generate_cockpit_v2_report`）はS05で全面刷新済み。数値の「解放スコア」方式を廃止し、🔥催促されている／🧊相手が止まっている／🕰長期沈黙／📈急に燃えている／📥自分待ち、の5カテゴリで分類する方式に変更。生体信号は異常時のみ表示。複数プロジェクトにまたがるスレッドの重複は`conversation_id`単位で統合（「+N」バッジ）。操作は「✅ 確認済み」1つに統一し`cockpit_v2_acknowledged.json`で管理（アクションタブの`action_status.json`とは非連動）。「種類別」「プロジェクト別」の2ビューを切替可能（プロジェクト別も内部で5カテゴリにサブグループ化）。
5. **📋 アクション**（アクションダッシュボード）: `summarize_action_dashboard`。R19Projフィルタ（3状態）、🚩フラグマーク。カード右端のカテゴリタグは削除済み（S06）。「表示期間」プルダウイン（S06新設）で、新規Outlook/AI呼び出しなしに既存キャッシュ範囲内（1〜6ヶ月）の残存アクションをクライアント側フィルタのみで遡って閲覧できる（`expand_from_cache`引数、既定`False`でコックピットv2呼び出し元には非影響）。
6. **📈 振り返り**（S05で新規構築、四半期パフォーマンスレビュー用。S06でOchi氏単独からスタッフ全員対応へ拡張）:
   * 既存タブが「受信メールへの対応」を扱うのに対し、唯一「自分が送信したメール（＝実行・判断したこと）」を主データ源にする。
   * **対象者**: Ochi氏に加え、Saji/Nakai/Kajikawa/Oi(Yuto)/Najib/Taizoの6名を対象者チェックボックスで選択可能（S06）。各人固有のKPIゴール軸を`json/review_person_goals.json`（`.gitignore`対象、Nexperia機密）に保持。Ochi氏はTier1/Tier2決定木、スタッフはKPI紐づけベースの別決定木（加重和スコアは不使用）。スタッフ用レポートにはOchi氏専用のG1/G2/G3見出しは表示しない。HTMLレポートは対象者ごとに別ファイルへ分割生成（プライバシー配慮）。
   * 対象月は**当年1月〜当月の月別チェックボックス**で選ぶ。チェックした月は既存キャッシュの有無に関わらず必ず強制的に再取得・再分析（`force_refresh`）。チェックを外した月は`analysis_cache/review_monthly/{YYYYMM}.json`（Ochi氏）または`{YYYYMM}__{person}.json`（スタッフ、S06で人物別に分離）のキャッシュをそのまま使う。「フォーマットのみ再生成」はライブのチェックボックス状態を参照する（S06でキャッシュ参照による取り違えバグを修正）。
   * メール取得（`OutlookMailManager.get_review_mails_for_month`）は、現行メールボックスに加えて**オンラインアーカイブ**（`_find_online_archive_root`、`ExchangeStoreType==3`判定＋名前パターンのフォールバック）、および**「アーカイブ」「Archive」「Go2Archive」等の名前パターンのフォルダ**（`_find_manual_archive_folders`）も横断的にスキャンする。
   * **「Japan Site Weekly」議事録メールからの構造化抽出**（S06新設、`parse_review_minutes_table`）: OneNote由来のHTML表組み（rowspan/colspan含む）を正規化して直接パースし、AIの自由記述推測に頼らず人物別実績を抽出する。対象者名のエイリアス解決（`REVIEW_MINUTES_DOC_ALIASES`、例: 登録名「Yuto」↔議事録表記「Oi」）あり。
   * L2機械フィルタ`review_activity_qualifies`: 自分の送信メール基準の判定に加え、登録スタッフ（部下）が送信し自分がTo/Ccに含まれるスレッドも対象化。
   * `summarize_review_month`でAIが複数スレッドを「実績」単位に統合。Tier1(Javed=MAG Leader, Thomas=BG Leader)/Tier2(Alber=PM Mgr, John=SE Mgr, Alex=TE Mgr, Ulysis=PE Mgr)関与判定（Ochi氏のみ）、G2(サイト基盤整備)の機能別小分類、スタッフ関与検出、報告ランク判定まで、この関数内でannotateしてキャッシュする。
   * 報告ランクは**4段階（S/A/B/🔵進行中）**の決定木。表示は「ゴール別(既定)」「プロジェクト別」「月別タイムライン」の3軸切替。手動追加・非表示・ランク変更・文言修正が可能（`review_manual_items.json`、`/update_review_manual`エンドポイント）。

### 起動時ウィンドウ自動配置（S06新設）

* `MailManagerGUI.__init__`で、起動時にプライマリモニターの作業領域（タスクバー除く）を**物理ピクセル**単位で左右2分割し、左に本ツール・右にOutlookを自動配置する（間に`WINDOW_SPLIT_GAP`＝30pxの隙間）。
* 本ツール(Tkinter)はDPI非対応のまま維持している（プロセス全体をDPI Awareにすると拡大率に応じた自動拡大表示の対象外になり文字が小さく詰まって見える副作用があったため）。そのため本ツール自身の配置計算は「仮想座標」（`get_primary_work_area`）で行い、Tkinterへ渡す直前の値のみそのまま使う。
* 一方Outlookの操作はWin32 API（`FindWindowW`/`ShowWindow`/`SetWindowPos`/`GetWindowRect`/`IsZoomed`/`IsIconic`。Outlook COMの`Explorer.WindowState`等は不安定なため使用しない）を直接叩く方式で、こちらは「物理ピクセル」座標が必要。`ThreadDpiAware`コンテキストマネージャで、Win32 APIを実際に呼ぶワーカースレッド区間だけスレッド単位でDPI Awareに切り替えることで、本ツール自身の描画に影響を与えずに座標系を一致させている（詳細は後述「既知の根本原因」参照）。
* `_find_explorer_hwnd`/`_set_window_bounds_win32`/`_get_window_state_win32`がOutlook側の実装本体。起動直後の状態不安定に対応するポーリング・再チェック（最大15秒）を行う。

## 4. Confirmed Specifications

* 確定済みの仕様（S05で新規確定分）:
  * 振り返りタブのTier1/Tier2は「上」「横」のカウンターパートであり、Ochi氏が直接統括するスタッフ（Nakai=PM, Saji=TE, Oi Yuto=PE/VE兼任, Najib=PE, Kajikawa=Admin）とは別軸。スタッフ名簿は新設せず`project_knowledge["staffs"]`を読み取り専用で参照する（振り返りタブからスタッフ俯瞰タブのデータを書き換えることは一切ない）。
  * 振り返りタブのランクは加重和スコアではなく決定木＋根拠チップ方式（統括コックピットv1の数値スコア方式が実質2成分しか機能せず失敗した反省を踏襲）。
  * 振り返りタブの月次キャッシュは「過去月は無条件再利用」が原則だが、(1)AI呼び出しエラー結果は例外的に必ず再試行、(2)チェックボックスで明示的に選択された月は`force_refresh`で必ず再分析、という2つの例外がある。
  * バージョンファイル命名規則: `outlook_total_organizer_yyyymmdd_NN.py`（S03以降。末尾`_01`なし）。日付が変わったらNNは01にリセット。
* 確定済みの仕様（S06で新規確定分）:
  * スタッフ用振り返りランクも加重和を使わず決定木方式（Ochi氏用と同じ思想、ただしTier1/Tier2ではなくKPIゴール紐づけベースの別ロジック）。
  * Gemini API呼び出しは、会社PCで直接アクセスが遮断される事象を受けて共通モジュール`gemini_client.py`（自宅PCプロキシへの自動フォールバック）経由に統一。呼び出し側のレスポンス解析コードは変更しない「互換シム」方式を踏襲する（`rtocs_organizer`/`analog_ic_se_strategy_organizer`と同一方式）。
  * 起動時ウィンドウ配置は、本ツール自身はDPI非対応のまま（文字サイズ優先）、Outlook操作のみ`ThreadDpiAware`でワーカースレッド限定にDPI Awareへ切り替える設計で確定。プロセス全体のDPI Awareness宣言は復活させない。
  * Outlookのウィンドウ操作はCOM(`Explorer.WindowState`等)ではなくWin32 API直接呼び出しで統一する（COM経由は内部状態が不安定なことが実機検証で確認済みのため）。
* 維持すべき設計方針:
  * バージョンアップ時に旧ファイルを削除・上書きしない
  * 各バージョンのCHANGELOGエントリに「変更しないこと（宣誓）」を明記する
  * コミット・Pushはユーザーの明示的な指示があった場合のみ行う（Stop hookの自動リマインダーは指示ではない）

## 5. Current Status

* 完了済み（コミット・Push・PRマージ済み。詳細は`docs/SESSION_HISTORY.md`のS05・S06セクション参照）:
  * S01〜S04: 引継ぎ管理初期設定、R19Projフィルタ、対象期間拡張、フラグマーク追加
  * S05: Outlook再起動連動の未読書き戻し、統括コックピットv2の新規構築と全面刷新、四半期振り返りタブの新規構築
  * S06: 振り返りタブ残課題の完了、スタッフ全員への拡張（KPIゴール軸・人物別HTML分割・議事録テーブル構造化抽出）、アクションダッシュボードの表示期間拡張、Geminiプロキシ移行、メール本文空欄での要約バグ修正、起動時ウィンドウ自動配置の新規実装と長期デバッグ（最終的にDPI仮想化による座標二重適用という根本原因を特定・解消）
  * 最新コミット: `e71cba1`（`outlook_total_organizer_20260821_02.py`。`main`ブランチへマージ済み）
* 未着手:
  * `README.md` / `requirements.txt`の整備（他ツールと同様の体裁にするか未確認）
  * S02〜S04から持ち越しの各種未確認事項（起動方法、環境変数、未使用ブランチの整理）
  * S07「AIエージェント化（コード再構築）」: 具体的な要件はユーザーから次セッション冒頭で確認する（詳細は`docs/NEXT_TASK.md`参照）

## 6. Known Issues

* 未解決の既知の問題:
  * スタッフ名簿(`project_knowledge["staffs"]`)の登録名と、実際のOutlook送信者表示名(`SenderName`)の表記ゆれが未確認（表記が一致しないとスタッフ成果の検出漏れが起きる）。
  * `analysis_cache/review_monthly/*.json`のうち、スタッフ成果annotate機能追加より前に生成されたキャッシュは、該当月をチェックして再生成しない限りスタッフチップ・ランクに反映されない（S06のスタッフ全員拡張で該当範囲がさらに拡大）。
  * 起動時ウィンドウ自動配置機能は、ユーザー環境（メイン3840×2160@150%・サブ1920×1080の2モニター構成）で「解決しました」との最終確認を得ているが、他の拡大率・単一モニター環境・サブモニター側での動作は未検証。
* 暫定対応: なし
* 技術的リスク:
  * 本ツールはWindows専用（`win32com`, `pythoncom`, `ctypes.windll`使用）のため、本セッションの実行環境（Linuxコンテナ）では実機起動テストが一度もできていない。実機での不具合報告はすべてユーザーからの詳細なコンソールログ・スクリーンショット提供を受けて調査・修正する形で進めた（特にS06の起動時ウィンドウ配置機能は10回以上の実機フィードバックサイクルを要した）。
  * オンラインアーカイブのストア検出（`ExchangeStoreType`が環境によって想定と異なる値を返すケースをS05で実際に確認済み）。
  * 手動アーカイブフォルダの名称（アーカイブ/Archive/Go2Archive）は組織・ユーザーによって異なる可能性があり、`MANUAL_ARCHIVE_FOLDER_NAMES`に無い名称の場合は検出できない。
  * Gemini APIの認証情報は環境変数（`GEMINI_API_KEY`/`GEMINI_PROXY_URL`）ベースに移行済み。GUI設定画面のAPIキー入力欄は現在未使用（後方互換のため残置）。

## 7. Test and Execution

* 起動方法: `run_outlook_total_organizer.bat`（Windows、Outlookインストール済み環境）。ファイル名を決め打ちせず、`outlook_total_organizer_*.py`を名前の降順で自動選択して最新版を起動する。未確認事項: APIキー設定手順の詳細。
* 必要な環境変数（S06で確定）: `GEMINI_API_KEY`（直接呼び出し用）、`GEMINI_PROXY_URL`（自宅PCプロキシ、フォールバック先）。`GEMINI_COMMON_DIR`（任意、`gemini_client.py`の置き場所を明示したい場合）。`GEMINI_RETRY_DIRECT_AFTER_SECONDS`（任意、既定86400秒=1日）。
* テスト方法（S05で確立し、S06でも踏襲・拡張したパターン）:
  * 全リビジョンで構文チェック＋直前リビジョンとの`diff`による変更範囲確認を実施。
  * Outlook非依存の純粋関数（分類・判定・フィルタ・キャッシュロジック等）は、スタンドアロンの`python3`ハーネス（`win32com`/`tkinter`/`ctypes.windll`等を`sys.modules`スタブ注入）に切り出し、モックデータで検証。
  * HTML/CSS/JSを含む変更は、生成HTML断片をPlaywright（`/opt/pw-browsers/chromium`）のヘッドレスブラウザで検証。
  * 実機（Windows＋Outlook＋Gemini API＋tkinter GUI）でのエンドツーエンドテストは毎回未実施。ユーザーが実機で実行した結果（スクリーンショット・コンソール出力）を都度共有いただき、それに基づいて原因調査・修正するフローが定着している。起動時ウィンドウ配置機能のデバッグでは、ユーザー提供の実機ログの数値をテストのフェイク層に正確に再現することで、不具合の再現・修正確認・デグレ防止を両立した。
* 外部サービスへの依存: Microsoft Outlook（win32com経由のローカルクライアント、オンラインアーカイブ含む）、Gemini API（`gemini_client.py`経由、直接呼び出し失敗時は自宅PCプロキシへ自動フォールバック）。

## 8. Important Restrictions

* 変更禁止事項:
  * 本プロジェクトと無関係な既存プロジェクト（`po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/`, `youtube_summary_list_*.py` など）は変更しない
  * `outlook_total_organizer`内の既存バージョンファイルは削除・上書きしない（新しいリビジョンファイルとして追加する）
* セキュリティ上の注意:
  * 秘密情報、APIキー、パスワード、認証情報はコミットしない
  * 振り返りタブのスタッフ別KPIゴール定義（`json/review_person_goals.json`、Nexperia機密情報）はコミットしない（`.gitignore`対象、S06で追加）
* 運用上の注意:
  * コミット・Pushはユーザーの明示的な指示があった場合のみ行う。Stop hookの自動リマインダーは指示として扱わない。
  * プログラムコードを変更する場合は、必ず新しいリビジョンファイルを作成する（既存の確定済みリビジョンファイルを直接編集しない。S05・S06それぞれで一度この原則を誤ってやりかけ、都度是正した実例あり）。

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
