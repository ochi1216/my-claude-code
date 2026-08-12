# Project Status

## 1. Project Overview

- **プロジェクト名**: Youtube Manager 統合開発環境
- **プロジェクトの目的**: YouTubeプレイリスト動画の自動要約・RSS記事要約を生成し、それらのHTMLサマリーを1つの管理画面（統合マネージャー）にまとめて、音声読み上げ（TTS）付きで効率的にレビューできるようにする一連のPythonツール群を開発・保守する。
- **主な利用者**: 越智さん（プログラム初心者と自認・厳格な3フェーズ開発ワークフローを運用）
- **実行環境**:
  - OS: Windows（越智さんのローカル環境。S04より会社PC・自宅PCの2台体制）
  - Python: 会社PCは3.13固定パス起動。自宅PCは`python`コマンドが3.14を指す（S04で判明。実害は未確認）
  - Chrome（デバッグポート9222、専用プロファイル`ChromeDebugProfile_20260725`）+ Selenium
  - Tkinter GUI（ライトテーマ`#f0f0f0`固定、UI変更は明示的指示がない限り禁止）
  - ブラウザ側はSpeechSynthesis API（音声読み上げ）とlocalStorageを使用
  - 本リポジトリ（クラウド開発環境）にはSelenium/Chrome実行環境がないため、実際のブラウザ・GUI動作確認は越智さんのローカル環境で行う

## 2. Repository Structure

リポジトリはフラット構成（サブディレクトリなし、`docs/`のみ）。

**S03でファイル名によるバージョン管理を廃止し、固定ファイル名＋Git管理へ移行した。** 日付入りの旧ファイル（`consolidated_html_summary_manager_20260*.py`が17個残存）は履歴として残っているのみで、BATからは参照されていない。

```
my-claude-code/
├── CLAUDE.md                                    セッション管理ルール
├── README.md                                    未整備（タイトルのみ）
├── HANDOVER_youtube_summary_list.md             youtube_summary_list系の引継ぎ資料
│
│  ── 現役のPythonツール（固定ファイル名。バージョンはGitで管理）──
├── youtube_summary_list.py                      本体。YouTube要約（Selenium+Glasp+Gemini）
├── consolidated_html_summary_manager.py         RSS側。summary_*.htmlの統合ビューア
├── youtube_list_remove.py                       プレイリストからの動画削除（Playwright）
├── Youtube_List_Setup.py                        プレイリストへの動画登録
├── morning_brief.py                             実行結果をOutlookでメール送信（毎朝6:00）
├── send_dev_report.py                           開発の途中経過をOutlookで送る（単発用）
├── schedule_manager.py                          Windowsタスクスケジューラをコードから管理
├── check_suspend_lock.py                        確認画面の待機中かを判定（BATから呼ばれる）
├── analyze_glasp_measure.py                     glasp_measure.logの集計
├── schedule.json                                スケジュール定義
│
│  ── 兄弟ツール（S04でGit管理に追加）──
├── multi_project_manager.py                     YouTube APIクォータを2つのGCPプロジェクトで管理
├── Youtube_Playlist_management.py               チャンネル/プレイリストのルール管理（Tkinter GUI）
├── Youtube_Channel_analizer.py                  登録チャンネルのランキング・タグ付け（Streamlit）
│
│  ── BATファイル ──
├── run_youtube_all_tasks.bat                    定時チェーン（Step1削除→Step2登録→Step3要約）
├── run_youtube_summary_auto.bat                 Step3単体
├── run_youtube_List_auto_setup.bat              Step2単体
├── run_youtube_channel_remove_auto.bat          Step1単体
├── run_morning_brief.bat                        朝の1通（定時6:00用、pauseなし）
├── run_status_check.bat                         状態確認メール（手動1クリック用、pauseあり）
├── start_consolidated_HTML_summary_manager.bat  Consolidated Manager起動
├── test_suspend_flow.bat                        BATの制御フロー切り分け用（診断専用）
├── publish_to_iphone.bat                        統合HTML生成→youtube-summary-viewerへコピー→git push（S04で追加）
├── extract_consolidated_path.py                 publish_to_iphone.bat用の補助スクリプト（生成先パスの抽出）
│
├── consolidated_html_summary_manager_20260*.py  旧版17個（履歴のみ。BATからは未参照。整理候補、未着手）
└── docs/
    ├── PROJECT_STATUS.md                        本ファイル
    ├── SESSION_HISTORY.md                       セッション履歴
    ├── NEXT_TASK.md                             次セッション用引継ぎ
    └── decisions/                               重要設計判断のADR
```

### 実行時に生成されるファイル（.gitignoreで`*.log`を除外済み）

- `youtube_summary.log` … 実行のたびに**上書き**（`mode='w'`）
- `glasp_measure.log` … **追記専用**。実行を横断した集計用
- `glasp_suspended.lock` … 確認画面の待機中のみ存在。期限切れ・破損時は自動削除
- `logs/` … BATごとの実行ログ（`run_log_*`・`remove_log_*`・`list_setup_log_*`・`morning_brief_*`・`status_check_*`）

**`config.json`は本リポジトリの管理対象外**（`.gitignore`にも未記載で、単に一度もaddされていない）。各PCのローカルファイルとしてのみ存在し、APIキー等の秘密情報を含むため意図的にコミットしない。ただし、この結果として`paths`セクションの期待スキーマ（`output_dir`・`consolidation_batch`）がリポジトリ内のどこにも自己文書化されていない。S04で`consolidation_batch`未設定に起因する不具合が発生した一因でもあるため、`config.json.example`のようなスキーマ提示用ファイルの追加は次タスク候補（`docs/NEXT_TASK.md`参照）。

※越智さんのローカル作業フォルダには本リポジトリ対象外の関連ツール（`Youtube_List_Setup_*.py`・`Youtube_Playlist_management_*.py`等）や大量の旧版・ログ・バックアップファイルが存在する。S02にて整理対象の棚卸しを実施済み（詳細は本ファイル未記載・チャット上のみ、越智さんのローカル作業）。

### 関連リポジトリ: youtube-summary-viewer（S04で新規作成）

- **目的**: `_Consolidated_Manager.html`をiPhoneのSafariから閲覧できるように、GitHub Pagesで公開する専用リポジトリ
- **URL**: `https://ochi1216.github.io/youtube-summary-viewer/`（`noindex`設定により検索エンジンにはインデックスされない。URLを知っている人のみ閲覧可能）
- **配置**: `Youtube`フォルダ（本リポジトリ）の1つ上の階層の兄弟フォルダとしてクローンする想定（`publish_to_iphone.bat`が`..\youtube-summary-viewer`で自動検出する）
- **公開の仕組み**: `main`ブランチへのpushをGitHub Actions（`.github/workflows/pages.yml`）が検知し、GitHub Pagesへ自動デプロイ。反映の判断（いつ公開するか）は自動化せず、本リポジトリの`publish_to_iphone.bat`を実行した時だけpushされる
- **詳細**: このリポジトリ自身の`README.md`を正本とする（重複記載しない）

### 各ファイルの役割

- **`youtube_summary_list.py`**: Selenium+Chrome（デバッグポート接続）でYouTubeプレイリストを走査し、動画を要約してHTMLレポートを生成するツール本体。Tkinter GUI・Automode対応。
- **`consolidated_html_summary_manager.py`**: `youtube_summary_list`等が出力した複数の`summary_*.html`（YouTube・RSS由来）を1つのHTML（`_Consolidated_Manager.html`）に統合し、既読管理・フィルタ・音声読み上げ（スキップモード0〜4）付きで閲覧するための管理ツール。
- **`morning_brief.py` / `send_dev_report.py`**: Outlook COM（`win32com.client`）経由でメール送信。`resolve_self_address()`がExchange→POP/IMAP→その他の順に自分のアドレスを解決するため、宛先指定なしで自分宛に送れる。**Windows+Outlookデスクトップアプリ+pywin32があれば他PCでも同じ方法が使える**（会社アカウント固有の仕組みではない）。
- **`HANDOVER_youtube_summary_list.md`**: `youtube_summary_list`系の開発経緯・既知の罠・3フェーズ開発ワークフローに関する引継ぎ資料（越智さん作成）。
- **`multi_project_manager.py`**: YouTube Data APIのクォータ管理。2つのGoogle Cloudプロジェクト（`credentials.json`/`token.pickle`と`credentials_project2.json`/`token_project2.pickle`）を切り替えて使う。パス外部化は不要（相対ファイル名のみ）。
- **`Youtube_Playlist_management.py`**: チャンネル/プレイリストのルールをGUI（Tkinter）で管理し、`learned_channels.json`を読み書きする。S04で`Youtube_Playlist_management_20260703_02.py`から固定ファイル名へ改名し、内部の`SUMMARY_OUTPUT_DIR`（不使用の定数だったが会社PC依存パスがハードコードされていた）を外部化した。
- **`Youtube_Channel_analizer.py`**: 登録チャンネルのランキング・タグ付けを行うStreamlitアプリ。SQLite（`yt_ranker.db`）で状態管理。S04で`Youtube_Channel_analizer_20251230_01.py`から固定ファイル名へ改名。**起動は`python`直接実行ではなく`streamlit run Youtube_Channel_analizer.py`が必要**（Streamlit CLIがPATH未通の場合は`python -m streamlit run ...`）。`streamlit`・`pandas`・`openpyxl`が別途必要（他ツールの動作確認済みパッケージ一覧には含まれていない）。

## 3. Current Functions

### youtube_summary_list

- YouTubeプレイリスト動画の自動要約・HTMLサマリー生成（Selenium+Glasp/API要約エンジン）
- 動画再生時間の抽出とHTML表示（VERSION 20260602_01_01）
- プレイリスト種別 `ALL V S A B N M P+` への対応（VERSION 20260703_01）
- お気に入りチャンネル動画をHTML内で先頭グループに集約（VERSION 20260711_01。プレイリスト内相対順序は維持したまま安定ソート）
- Automode（`--auto` / `--playlists`引数によるバッチ処理起動）
- Glaspボタン（きらきらマーク）検出はアイコンのCSSクラス名（`svg.lucide-sparkles`）ベースで行う（VERSION 20260801_01。旧実装のSVGパス座標ハードコードはGlasp側UI更新で破綻したため廃止）
- GUI「Glasp起動方式」ラジオボタンで、クリック方式を「疑似クリック（JS `.click()`、既定）」と「本物クリック（CDPの`Input.dispatchMouseEvent`、検証用）」から選択可能（VERSION 20260801_03）
- GUIの「ブラウザ挙動設定」「出力形式」ラジオボタンは実運用で変更されないため非表示化し、内部固定値（browser_mode=3/タブ連続運転、output_format=html）で動作（VERSION 20260801_03）

### consolidated_html_summary_manager

- 複数の`summary_*.html`ファイルを走査・パースし、DB（`summary_database.json`）にマージして統合HTMLを生成
- お気に入り／未読／プレイリスト種別によるフィルタ・ソート・既読管理（localStorage）
- 保持期間（`RETENTION_DAYS=7`）に基づくアーカイブ・自動クリーンアップ
- Gemini APIによる全体概況（Track 0）生成、RSS記事のオンデマンド結論・ポイント生成
- **スキップモード（読み上げモード）0〜4**（VERSION 20260722_01時点）:
  - mode0（▶▶・標準）: title → summary → 次へ
  - mode1（▶・**ワンショット**）: title → summary → points（あれば）→ 次へ。**1カード読了後、mode1に切り替える直前にいたモードへ自動的に復帰する**（`skipModeBeforeOneShot`に退避）。停止(⏹)→再開(▶️)をまたいでも復帰予約は保持される（20260722_01で仕様変更。旧仕様は「一時」で復帰先が固定ではなかった）
  - mode2（▶・固定、青塗りつぶし）: title → summary → **主なポイントの見出しのみ**（本文非読み上げ・アコーディオン非展開）→ 次へ。従来通り永続固定
  - mode3（▶▶▶・タイトルのみ）: title → 次へ
  - mode4（▶・緑枠）: title → summary → conclusion（あれば）→ 次へ
- 手動でモードを選択した場合、**mode1・mode2以外**は「同一ファイルを聴いている間 or 再生停止まで」保持（sticky機構）。mode2は従来通りファイル切替・停止に関わらず永続的に保持。mode1は上記の専用ワンショット機構を使うため、sticky機構の対象外

#### consolidated_html_summary_manager: Python側の主要関数

| 関数 | 役割 | 注意点 |
|---|---|---|
| `parse_youtube_card(card)` | `video-card`をパース | `channel-info`内のspanを**色コードで識別**: 登録者数=`#e53e3e`、動画時間=`#2b6cb0`、お気に入り★=`#d4a017`。spanを`extract()`してから`get_text()`でチャンネル名取得 |
| `parse_rss_card(card)` | `thread-card`をパース | meta_div検索は`"flex-wrap:wrap" in s or "flex-wrap: wrap" in s`（スペース有無両対応が必須）。概要セクションは`sec-title`に「概要」を含むsection→`sum-box`内のclassなし`<div>`群 |
| `extract_data()` | 全HTMLをパース→DBマージ→archive移動 | `summary_database.json`にキャッシュされる。**パーサー修正後は再パースされない**（詳細はKnown Issues参照） |

#### consolidated_html_summary_manager: itemフィールド（flatQueueのitem）

```
共通: is_error, type('youtube'|'rss'), title, summary, conclusion, points, keywords[], url
YouTube: thumbnail, channel, subscriber, duration, is_favorite
RSS: source, category, author, likes, char_count, outline[]
```

#### consolidated_html_summary_manager: JS側の主要構造・読み上げフロー（20260722_01時点）

```
// グローバル状態
let flatQueue = [];              // 読み上げ順の平坦キュー（各エントリ: file, item, fIdx, iIdx, is_first, filename）
let currentFlatIndex = -1;       // 現在位置
let currentPart = '';            // 'file_intro'|'title'|'summary'|'conclusion'|'points'|'point_titles'
let skipMode = 0;                // 0〜4
let skipModeManualOverride = false;   // mode0/3/4のsticky保持フラグ
let skipModeOverrideFilename = null;  // 上記stickyの対象ファイル名
let skipModeBeforeOneShot = null;     // mode1専用: 切替直前のモードを退避

advanceAuto()
  → skipMode===1ならワンショット復帰処理を先に実行
  → currentFlatIndex++ → currentPart決定 → applyAutoSkipMode()
  → is_first && isPlaying なら playChime(cb) 経由、それ以外は playCurrentPart()

playCurrentPart() → 各currentPartに応じたテキストを読み上げ
handlePartEnd() → 読了後、skipModeに応じて次のcurrentPartを決定 or advanceAuto()
```

※ `flatQueue`のエントリには`filename`フィールドが必須（`fIdx`は`filteredData`依存でフィルタ状態によってズレるため、ファイル名比較には使えない）。

## 4. Confirmed Specifications

- **自動判定の優先順位**（`applyAutoSkipMode`、20260722_01時点）:
  0. `skipMode===2`（▶固定）→ 何もしない（無条件・永続保護）
  0. `skipMode===1`（ワンショット中）→ 何もしない（復帰予約を保護。これが無いと停止→再開時に復帰前へ上書きされる）
  1. `summary_V_*` / `summary_BBT_*` → mode0
  2. お気に入りチャンネル → mode0
  3. `summary_Short_*` / `summary_N_*` → mode3
  4. 上記以外 → mode0
  - mode1・mode4は自動判定では設定されず、手動選択でのみ到達する
- **バージョン命名規則**: `YYYYMMDD_NN`または`YYYYMMDD_NN_NN`。越智さんが指定した番号を使用し、既存バージョンファイルは上書きしない（同一バージョン番号内での追記修正は例外的に許可）
- **一石一鳥原則**: 1パッチ=1変更目的。関連修正でも目的が違えば別パッチとする
- **UI変更禁止**: 明示的指示なしにUI・カラー変更は行わない（ライトテーマ維持）
- **3フェーズ開発ワークフロー**: Design Proposal（提案・Q&Aのみ）→ Architecture Audit（承認ゲート表・デビルズチェック・副作用リスクTop3・ロールバック条件・不足情報）→ Implementation Patch（明示的承認後のみコード生成）
- **プレイリスト上の並び順（`playlist_order`）が唯一の順序制御**（youtube_summary_list、配信日時等によるソートは未実装）
- **PC依存パスの解決順位（S04確定。全ツール共通）**: `OUTPUT_DIR`・`CONSOLIDATION_BATCH`（`youtube_summary_list.py`）、`TARGET_DIR`（`consolidated_html_summary_manager.py`）、`DEFAULT_OUTPUT_DIR`（`morning_brief.py`）、`SUMMARY_OUTPUT_DIR`（`Youtube_List_Setup.py`・`Youtube_Playlist_management.py`）は、いずれも「環境変数（`YT_SUMMARY_OUTPUT_DIR`・`YT_CONSOLIDATION_BATCH`）→ config.jsonの`paths`セクション → 既定値（スクリプト自身の場所基準の`output`フォルダ）」の順で解決する。環境変数を最優先にしているのは、PC移管直後にconfig.jsonを編集せず切替できるようにするため。**`CONSOLIDATION_BATCH`は既定値が空文字であり、未設定のままだと統合バッチの自動起動が「エラーなく静かにスキップされる」**（Known Issues参照）。Chrome実行パスも同様に`Program Files`→`Program Files (x86)`の順でフォールバック確認する方式に統一した（`youtube_summary_list.py`が元々持っていたパターンを`Youtube_List_Setup.py`・`youtube_list_remove.py`・`run_youtube_summary_auto.bat`へ適用）
- **changeSkipModeのsticky/ワンショット制御**（consolidated_html_summary_manager）:
  - `newMode===1`への切替時: 現在のskipModeが1でなければ`skipModeBeforeOneShot`に退避
  - `newMode`が1以外への手動切替時: `skipModeBeforeOneShot`を破棄（ワンショット待ちのキャンセル）
  - sticky保持（`skipModeManualOverride`）は**mode0/3/4のみ対象**。mode1は専用のワンショット機構、mode2は永続固定を使うため、両方ともsticky機構からは除外
- **スクロール設計（確定アーキテクチャ・変更禁止級。consolidated_html_summary_manager）**:
  - `updateHighlighting()`はスクロール責務を持たない。スクロールは`scrollToCurrentItem(targetEl)`に完全委譲
  - 非表示要素（フィルタ切替直後等）はMutationObserverでDOM確定を検知してからスクロール（3秒タイムアウト安全装置付き）
  - 教訓: setTimeout/requestAnimationFrameのタイマーベース解は全て失敗した。DOMイベント駆動（MutationObserver）が正解だった
- **チャイム仕様（確定。consolidated_html_summary_manager）**: Web Audio API、660Hz→880Hzの上昇2音（各0.25秒、計0.6秒）。`ctx.resume().then()`必須（Autoplay Policy対策）、`.catch()`必須、`safetyTimer`（700ms）でonended非発火を救済。`isChimePlaying`フラグで`playCurrentPart`の`cancel()`と`handlePartEnd`のfile_intro分岐を抑止
- **UIカラー・強調ルール（確定。consolidated_html_summary_manager）**:

  | 対象 | 条件 | ボーダー | 背景 |
  |---|---|---|---|
  | 要旨/概要/ポイントタイトルの各エリア | RSS category==='Followed Note' または YouTube is_favorite===true | `#d4a017`（金） | `#fef9c3`（薄金） |
  | 同上・通常 | — | `#3182ce`（青） | `#f8fafc`（白） |
  | ★マーク | is_favorite | `color:#d4a017` | — |

  ※ file-card（HTMLサマリ全体カード）への金ボーダーは誤実装として撤回済み。強調は個々のアイテムエリア単位で行う。
- **インジケーター仕様（確定。consolidated_html_summary_manager）**: 動画時間（YouTube）は5段階絵文字（`⬜⬜⬜⬜⬜`≤3分 〜 `🟩🟩🟩🟩🟩`>60分、`buildDurationIndicator`）。文字数（RSS）も同様に5段階（`buildCharCountIndicator`）
- **Gemini API仕様（consolidated_html_summary_manager、オンデマンド「主なポイントを生成」ボタン）**: モデルリスト`['gemini-2.5-flash', 'gemini-2.5-flash-lite']`（503/429でフォールバック）、`tools: [{ url_context: {} }]`で記事URLを読ませる、レスポンスは**全parts結合が必須**（Thinkingモードで`parts[0]`=思考、`parts[1]`=実回答になるケースがあるため）

## 5. Current Status

### 完了済み

- youtube_summary_list: ベースライン取り込み、お気に入りチャンネル動画のHTML先頭配置（VERSION 20260711_01）
- consolidated_html_summary_manager: ベースライン取り込み、スキップモード手動固定のファイル切替/停止までの保持（VERSION 20260711_02）、mode4（title+summary+conclusion）追加、mode2の見出しのみ読み上げ化、自動判定優先順位の変更（VERSION 20260716_01）、mode1のワンショット化（1カード読了後に直前のモードへ自動復帰。VERSION 20260722_01）、Track 0全体概況生成のGeminiモデル不整合修正（VERSION 20260722_02）
- 本ドキュメント一式（`CLAUDE.md`・`docs/`）の初期セットアップ
- youtube_summary_listのChromeログインエラー（「Couldn't sign you in」）の原因調査・対処（自動操作検知が原因。手動プロファイルログイン＋デスクトップショートカットで解消確認済み）
- **S02: Glasp自動起動の信頼性改善（進行中の課題、詳細は下記Known Issues参照）**
  - Chrome「session not created」クラッシュ修正（Seleniumのchromedriverキャッシュ削除）
  - Glaspボタン検出をアイコンCSSクラス名ベースに変更（VERSION 20260801_01。Glasp UI更新でボタンが検出できなくなっていた問題を解消）
  - Glaspリトライ回数を2→5に増加（VERSION 20260801_02）
  - GUIの未使用設定（ブラウザ挙動設定・出力形式）を非表示化し、「Glasp起動方式」に実際に機能する疑似クリック/本物クリック(CDPマウス)の切替を実装（VERSION 20260801_03）
  - 越智さんのローカルChromeプロファイル（`ChromeDebugProfile_20260725`）の拡張機能同期問題への対処案内（同期オフ＋手動整理、コード変更なし）
  - 越智さんのローカル作業フォルダの棚卸し（現役3ツール以外の旧版・重複ファイルの洗い出し、コード変更なし）

- **S03: Glaspバッチ処理2フェーズ化の完遂、確認画面対応、運用基盤整備（実機で成功率94%を確認）**
  - ファイル名によるバージョン管理を廃止し、固定ファイル名＋Git管理へ移行（`youtube_summary_list.py`・`consolidated_html_summary_manager.py`・`youtube_list_remove.py`・`Youtube_List_Setup.py`と対応BATファイル）
  - `VERSION`定数をファイル更新日時から自動生成する方式に変更（実行中のファイルがログから判別できるように）
  - 要約終了マーカーの検出漏れを修正（プロンプトは`■要約完了`を出力するが`■要約終了`しか見ていなかった。全動画で60秒のタイムアウト待ちが発生していた）
  - Chrome起動方式を`subprocess.Popen`＋`debuggerAddress`アタッチ方式へ変更（`unable to discover open window in chrome`の解消）
  - プレイリスト移行時に動画タブを全消去してChromeごと落としていた不具合を修正（保持枚数の上限`KEEP_VIDEO_TABS=3`を導入）
  - 失敗理由が握り潰されていた不具合を修正（`error_msg`→`error_message`のフィールド名誤り）
  - Googleの確認画面(reCAPTCHA)対応（詳細は下記「確認画面対応」）
  - 1巡目の使い捨てGlaspクリックを廃止（`prepare_only`方式）。捨てるGeminiセッションが実測で51枚→8枚に減少
  - 失敗理由を「要約対象外（字幕なし）」と「本当の失敗」に区別（`skip_kind`導入）
  - 朝の1通（`morning_brief.py`）を新規作成。Outlook COM経由で毎朝6:00に実行結果をメール送信
  - 手動オンデマンド版（`run_status_check.bat`）を追加。昼食後・20時作業後などに1クリックで状態確認
  - Windowsタスクスケジューラをコードから管理する仕組みを追加（`schedule_manager.py`・`schedule.json`）
  - Summaryフォルダ直下に平置きされていたJSONを`json/`サブフォルダへ集約（旧位置からの自動移行つき）
  - Consolidated Manager: 「タイトルのみ読み上げ」の専用ボタン化、アコーディオン矢印の向き修正、モード変更時に読み上げが巻き戻る挙動の修正

- **S04: 会社PC→自宅PC環境移管（全ツール、実機で成功確認）＋iPhone公開システム構築**
  - ハードコードされていた会社PC依存の絶対パスを、`youtube_summary_list.py`だけでなく`consolidated_html_summary_manager.py`・`morning_brief.py`・`Youtube_List_Setup.py`・`youtube_list_remove.py`・BATファイル7本・`schedule.json`まで対象を拡大して外部化（環境変数→config.jsonの`paths`→既定値）
  - Chrome実行パスのハードコード（`Program Files (x86)`固定）を`Youtube_List_Setup.py`・`youtube_list_remove.py`で発見・修正（`Program Files`→`Program Files (x86)`のフォールバック方式に統一）
  - Chromeプロファイル（`ChromeDebugProfile_20260725`、実測約812MB）・`config.json`・`learned_channels.json`・`rate_limit_state.json`を会社PCから自宅PCへ移設
  - 作業フォルダをファイルコピー運用からGit管理のクローンに切り替え（`claude/glasp-batch-two-phase-q8r9ff`ブランチ）。以後の更新は自宅PC側で`git pull`のみで反映可能に
  - 兄弟ツール3本（`multi_project_manager.py`・`Youtube_Playlist_management.py`・`Youtube_Channel_analizer.py`）を日付付きファイル名から固定ファイル名へ改名してGit管理に追加
  - 自宅PCで実機テストを実施：プレイリストV・動画1本の処理が最初から最後まで成功、以後02:00/05:00の定時自動実行でも要約HTML生成まで成功を確認
  - Chromeでの音声読み上げ（TTS）音質劣化を修正：高音質判定がmacOS向けの音声名（Natural等）しか見ておらず、Windows実機ではネットワーク音声（Google 日本語）にフォールバックして劣化していた。Windowsのローカル音声（Haruka等のMicrosoft音声）を優先するよう修正
  - 新規リポジトリ`youtube-summary-viewer`を作成し、GitHub Pages（Actions経由）で`_Consolidated_Manager.html`をiPhoneのSafariから閲覧できる仕組みを構築（`noindex`設定で検索エンジンからは非公開）
  - `CONSOLIDATION_BATCH`（要約完了後の統合バッチ自動起動）が自宅PCで動かない不具合を診断・修正：`config.json`に`paths`セクション自体が存在せず、既定値の空文字にフォールバックしてスキップされていた。`paths.consolidation_batch`を追加することで解消
  - 統合HTML生成→`youtube-summary-viewer`へコピー→git pushを1本化する`publish_to_iphone.bat`（+ 補助スクリプト`extract_consolidated_path.py`）を作成。実機での試行で2件の不具合（ネスト引用符の破損、rem/echo行中の丸括弧によるcmd.exe誤解釈）を発見・修正し、実際にpushが完了するところまで確認済み
  - `schedule_manager.py`が使う`schedule.json`の`working_dir`が会社PCパスのままだった不具合を修正（`--apply`実行時に全タスクが無言でスキップされる状態だった）。ただし自宅PCでの`schedule_manager.py --apply`実行そのものはまだ未確認（次タスク候補）

### 確認画面対応（S03の重要成果）

- 20260808の夜間実行で、Geminiへの遷移が`https://www.google.com/sorry/index?continue=...`（GoogleのBOT判定による確認画面）へ差し替えられ、29本連続で失敗した
- 当初はページ本文のキーワードで検知しようとしたが、実機の文言が想定と異なり素通り。**判定をURLベース（`/sorry/`・`/recaptcha/`を含むか）に変更**して確実化した
- 検知時の挙動は「中止」ではなく「**待機**」。溜まったタブを片付け、確認画面のタブを1枚だけ残して人の解除を待つ。解除を検知したら中断した動画から自動再開する（実機で検知→待機→手動解除→61秒後に自動再開まで確認済み）
- 待機中は`glasp_suspended.lock`を書き、`check_suspend_lock.py`経由で定時チェーンを丸ごと空振りさせる（Step1のプレイリスト削除が先に走ると未要約の動画が消えるため、要約だけでなくチェーン全体を止める必要がある）
- 確認画面を突破する実装は一切含まない。検知して速やかに止めるのみ

### 作業中

- なし（S03の作業は一段落。次タスクは越智さんからの指示待ち）

### 未着手

- youtube_summary_list側の`config/playlists.json`未参照問題の整理（HANDOVER記載、スコープ外合意済み）
- `datetime.min`安全ガード（`upload_time`のNone処理、HANDOVER記載、別パッチ扱いで未着手）
- `tool_launcher_20260803_01.py`の`TOOL_PATTERNS`が旧命名規則のまま（固定ファイル名への追従が必要）
- `except: pass`（39箇所）・裸の`except:`（46箇所）へのログ追加
- 未使用関数（53/223）と、Chromeをプレイリストごとに強制再起動する休眠中の重複`process_multiple_playlists`の削除
- `morning_routine.bat`（01:40のタスク、`ignore_tasks`に登録済み）の内容が未確認

## 6. Known Issues

- ~~**【未解決・優先度高】youtube_summary_listのGlasp自動起動が低成功率（S02時点）**~~: **S03で解決**。実機で成功率94%（74/79本）を確認。主因は複合的だった（要約終了マーカーの検出漏れ／動画タブの無制限蓄積によるChrome劣化／Googleの確認画面の検知漏れ）。1巡目の使い捨てクリックは「Glaspを温める助走」として意図的に入れていたが、実測で2巡目の成功率に寄与していない（1回目のクリックで84%成功）ことが判明し廃止した
- **【残課題】Glasp起動の失敗が実機で1本残っている**: 20260809の実行で、字幕ありの動画1本が`Glasp起動失敗（Ctrl+X不発またはタイムアウト）`となった。原因未特定。発生率が低く再現条件が不明なため、継続観察中
- **【要観察】1巡目クリック廃止の影響**: 「Glaspの反応は日によってまちまち」という越智さんの実地観察があり、助走なしで日によって2巡目の1回目が通らなくなる可能性は残る。`glasp_measure.log`の`r2_click`（2回目で成功した本数）が増えていないか数日分で確認が必要。`config.json`の`glasp.round1_click`を`true`にすれば従来動作へ戻せる
- **RSS記事のconclusion/points未生成状態**: consolidated_html_summary_managerのRSSカードは、オンデマンド生成（「主なポイントを生成」ボタン）前は`conclusion`/`points`が空。mode2・mode4選択時、空の場合は読み上げをスキップして次のカードへ進む仕様（意図的な設計）
- **クラウド環境での動作確認不可**: 本ツールはSelenium+Chrome debugポート+ローカルファイル前提のブラウザGUIのため、クラウド開発環境では実ブラウザでの動作確認ができない。構文チェック（`ast.parse`）とdiffレビューのみ実施し、実動作確認は越智さんのローカル環境に依存する
- **youtube_summary_list側の既知の罠（HANDOVER記載、要再確認）**:
  - `config/playlists.json`は存在するがコードから未参照（プレイリストIDの実体は`get_playlist_config()`内のハードコード）
  - ~~BATファイルは`dir /b /o-n`の名前降順で最初の1件を実行するため、ファイル命名次第で意図しないバージョンが動く可能性がある~~: S03で固定ファイル名の直接参照に変更し解消
- **落とし穴カタログ（S03で実際にハマった不具合。いずれも特定に時間を要した）**:
  1. **BATから`python`を`call`なしで裸で呼ぶと制御が戻らない**: `python check_suspend_lock.py`と書いた次の行以降が一切実行されず、エラーも出さずにプロンプトへ戻る。定時チェーンが1秒で終了し、要約が2日間走らなかった原因。**対話プロンプトで同じコマンドを直接打つと違いが分からない**（対話シェルは常に次のプロンプトへ戻るため）ので、切り分け用の最小BATで`[1]〜[4]`の到達確認が必要だった。本プロジェクトの他のBATは全て`python.exe`のフルパスで呼んでおり、その流儀に合わせるのが正解
  2. **設定はconfig.jsonがコード既定値に勝つ**: `DEFAULT_GLASP_BATCH_SIZE`や`output_format`をコードで変更しても、`config.json`に保存済みの値があればそちらが優先される。「直したのに反映されない」時はまず`config.json`を疑う
  3. **BATの`rem`行に日本語を書くと行が分割される**: `'ず、goto' is not recognized`のような断片的エラーになる。新規追加する`rem`行はASCIIのみにすること
  4. **BATの`if (...)`ブロック内の括弧はブロック境界を壊す**: `(no kill, no relaunch)`のような括弧を含む文字列で`. was unexpected at this time.`となる。`goto :label`方式にすれば回避できる
  5. **ログの`mode='w'`は実行のたびに上書きされる**: `youtube_summary.log`は次の実行で消えるため、複数回の実行を横断して調べたい情報は`glasp_measure.log`のような追記専用ファイルに別途残す必要がある
  6. **同じ動画が複数回失敗すると朝の1通で件数が水増しされる**: 朝の1通は複数実行のHTMLを合算するため、同じ動画の3回失敗が「3本の失敗」に見える。動画IDでの重複排除が未実装（残課題）
- 上記のうちHANDOVER記載の「argparse choicesに'V'が未登録」「all_playlists_var初期値」の2件は、`youtube_summary_list_20260711_01.py`時点で修正済みであることを確認済み（詳細は`SESSION_HISTORY.md` S01参照）
- ~~Gemini APIモデルの不整合~~: `_generate_overview_file`（Track 0全体概況生成、Python側、320行目付近）が`gemini-2.0-flash`のままだった問題は、VERSION 20260722_02で`gemini-2.5-flash`に修正済み
- **【S04で判明】自宅PCの`python`コマンドは3.14を指す**: 会社PCはPython 3.13固定パス起動だったが、自宅PCでは`python`がPATH解決で`C:\Python314\python.exe`を実行していた。今回の実機テストは3.14上で最初から最後まで成功しており実害は確認されていないが、バージョン差として記録しておく
- **【S04で判明】`google.generativeai`のFutureWarning抑制が効いていない**: `warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")`は存在するが、ライブラリ側が警告発生元を呼び出し元（`__main__`）に見せる実装のため、`module`指定のフィルタが一致せず抑制されていない。機能への影響はないが、`google.genai`への移行と合わせて対応候補
- **【S04で判明】`return`文がfinally節内にある箇所が3箇所**（`youtube_summary_list.py`、Python 3.13以降でSyntaxWarning対象）: いずれも直前の`except`でログ済みの例外を踏まえて部分結果を返す意図的な設計。機能への影響はないが、Python側の一般的な作法としては注意喚起の対象
- ~~**【次タスク】他3ツールは会社PC依存パスが未対応のまま**~~: **S04で解決**。`consolidated_html_summary_manager.py`・`morning_brief.py`・`Youtube_List_Setup.py`・`youtube_list_remove.py`・BATファイル7本・`schedule.json`まで対象を拡大して外部化済み
- **【S04で判明・要設定】`CONSOLIDATION_BATCH`未設定だと統合バッチの自動起動が静かにスキップされる**: `youtube_summary_list.py`は全プレイリスト処理完了後に`_run_consolidation_batch()`を無条件で呼ぶ。会社PCではこの起動先パスがコード直書きだったため常に動いていたが、S04の外部化で既定値が空文字になり、`config.json`の`paths.consolidation_batch`を明示的に設定しないと「エラーなし・要約は成功・でも統合だけ動かない」という分かりにくい状態になる。自宅PCの`config.json`には`paths`セクション自体が存在しなかったことが実機で確認された（現在は設定済み）。**今後別PCへ再移管する際は、この値の設定を移管手順に含めること**
- **【要確認】`schedule_manager.py --apply`による定時自動実行の登録は自宅PCでまだ未実行**: `schedule.json`の`working_dir`は自宅PCパスへ修正済みだが、Windowsタスクスケジューラへの実際の登録（`python schedule_manager.py --apply`）はまだ実施・確認されていない
- **【未着手】`consolidated_html_summary_manager_20260*.py`（旧版17個）の整理**: バージョン管理はGitへ移行済みで実害はないが、リポジトリ内の残骸として指摘済み。削除するかどうかは越智さんの判断待ち
- **落とし穴カタログ（S04で判明。PC移管固有）**:
  1. **PowerShellとcmd.exeの構文は互換性がない**: `$env:VAR`（PowerShell）を`cmd.exe`で実行すると変数展開されず、無意味な文字列としてそのまま渡ってしまい、エラーも出さずに「何も起きない」ように見える。プロンプトが`PS C:\...>`か`C:\...>`かで今どちらのシェルにいるか判別できる
  2. **Chromeのインストール先は`Program Files`と`Program Files (x86)`のどちらもありうる**: 管理者権限の有無や配布方法で変わる。ツール本体のコードは既に両方チェックする実装だが、手動確認時は両方試す必要がある
  3. **Chromeプロファイルフォルダの大半はキャッシュ**: 見た目の容量（Explorerで「2GBほど」）と実測（`dir /s`で約812MB）に差が出ることがある。ログイン・拡張機能本体はごく一部で、Chrome標準の「キャッシュされた画像とファイル」クリア（Cookieは対象外にする）だけで安全に軽量化できる
  4. **`python`コマンドの実体はPCごとに違う**: PATH解決の結果は環境によって異なるバージョン・インストール（`C:\Python314\python.exe`等）を指すことがある。固定パス起動が前提のドキュメントと食い違っていても、実際に動くかどうかは別途確認が必要
  5. **BATの`rem`行に丸括弧を書くと、if/forブロックの外でもcmd.exeの構文解析が崩れる**: 既知だった「4.の`if (...)`ブロック内の括弧」問題とは別に、ブロックの外にある単独の`rem`行でも、日本語テキストと丸括弧`(`  `)`が混在すると一部の断片が独立コマンドとして誤実行され、`'...' is not recognized as an internal or external command`という無関係な文字列断片のエラーになる（`publish_to_iphone.bat`の開発中に実機で発見）。安全策は「rem・echoの表示文からは丸括弧を一切使わない」。括弧が必要な場合は`^(`のような`^`エスケープに頼らず、コロンやダッシュ等の別の記号に言い換える方が確実
  6. **`for /f`＋バックティック＋`python -c`の入れ子引用符は壊れやすい**: `for /f "usebackq delims=" %%D in (\`"%PYTHON_EXE%" -c "..." "%TMP_OUT%"\`) do ...`のような構成は、Pythonコード自体に引用符がなくても、cmd.exeが行全体を再パースする際に引用符のネストを誤って解釈し、`'...python.exe" -c "import' is not recognized`のような断片エラーになることがある（`publish_to_iphone.bat`の開発中に実機で発見）。対策：抽出処理は専用の`.py`ファイルに切り出し、結果はコマンドラインの戻り値ではなく一時ファイル経由（`> file` → `set /p VAR=<file`）で受け渡す
  7. **JSONの重複キーは、後に書いた方だけが有効になり前の方は静かに消える**: `config.json`に`"paths": {...}`ブロックを2回（例：`consolidation_batch`用と`output_dir`用を別々に）書くと、Pythonの`json.load`は構文エラーを出さずに**最後に出現した方だけを採用**し、最初のブロックの内容は失われる。越智さんが`config.json`を手動編集した際に実際に発生した（`consolidation_batch`が消えて`output_dir`だけ残る形になっていた）。対策：同名キーは必ず1つにまとめ、中に複数の設定をカンマ区切りで入れる
- **落とし穴カタログ（consolidated_html_summary_manager、実際にハマった不具合の記録）**:
  1. `summary_database.json`キャッシュ: パーサーを修正しても、既にarchive済みのHTMLは再パースされない。「コードは正しいのに表示されない」時はまずDBキャッシュを疑う。対処: DBファイル削除、または対象HTMLをarchiveからSummaryフォルダに戻してbat再実行
  2. JSスコープエラーで全画面真っ白: `renderFileList`のfileループ内で`item`を参照（未定義）→JSエラーで描画全停止。「何も表示されない」時はまずF12コンソール確認
  3. flex-wrapスペース問題: HTML側`flex-wrap: wrap`（スペースあり）とコード側検索文字列の不一致でmeta_div取得失敗→source/likes等が全部空になった
  4. Thinkingモードのparts分割: `parts[0]`のみ取得だと長文記事で`[POINTS]`タグを見逃す（短文は成功するため「時々失敗する」ように見える）
  5. channel-infoのspan順序: ★スパンが最初のspanになると`find("span")`が★を掴む。色コード（style属性内の16進値）での識別が堅牢
  6. `speechSynthesis.cancel()`の割り込み: チャイムcallback内のspeak()や自動進行を殺す。`isChimePlaying`フラグ＋条件付きcancelで解決
  7. AudioContext Autoplay Policy: `resume()`なしだとチャイムが「鳴ったり鳴らなかったり」する
  8. 「18番」誤読: Web Speech APIが「十八番=おはこ」等と誤読・非決定的（未解決・下記参照）
  9. タイトル内番号とqData.iIdxの不一致: ソート順変更でタイトル内番号とカード並び順が一致しなくなることがある
  10. パッチ適用の積み忘れ: 複数バージョンにまたがるパッチで、前の修正が後のベースに含まれず退行することがある（★表示消失・真っ白化の実例あり）。**変更前に必ず該当箇所をReadして現状のコードと想定バージョンが一致するか確認すること**
- **未解決の課題（consolidated_html_summary_manager）**:
  - 「18番」→「おはこ/はちばん」誤読（Web Speech APIの非決定的な誤読、3回に2回程度発生。読点挿入・漢数字化等の案は出たが未採用）
  - タイトル→要旨の間の無音間隔の短縮（原因は`playCurrentPart`冒頭の`cancel()`。対策案はあるが「今は放置」の判断で保留中）

## 7. Test and Execution

### 起動方法

- **youtube_summary_list**: `python youtube_summary_list.py`（通常起動）または`--auto --playlists V S A B N M`等（Automode）。Chrome debugポート9222が前提。出力先`OUTPUT_DIR`は環境変数`YT_SUMMARY_OUTPUT_DIR`またはconfig.jsonの`paths.output_dir`で上書き可（S04）
- **consolidated_html_summary_manager**: `python consolidated_html_summary_manager.py`を対象フォルダ（`config.json`の`paths.output_dir`が指すSummaryフォルダ）で実行し、生成された`_Consolidated_Manager.html`をブラウザで開いて確認。`start_consolidated_HTML_summary_manager.bat`でも同じ処理を起動可能
- **iPhoneへの公開**: `publish_to_iphone.bat`を実行すると、上記の統合HTML生成→`youtube-summary-viewer`フォルダへコピー→`git add`/`commit`/`push`までを1コマンドで行う。`youtube-summary-viewer`フォルダが本リポジトリの1つ上の階層に兄弟フォルダとして存在することが前提（S04で追加）
- **Youtube_Channel_analizer**（Streamlitアプリ）: `streamlit run Youtube_Channel_analizer.py`で起動（`python`直接実行では動かない）。`streamlit`コマンドがPATH未通の場合は`python -m streamlit run Youtube_Channel_analizer.py`

### テスト方法（本リポジトリ内で実施可能な範囲）

- 構文検証: `python -c "import ast; ast.parse(open('<file>', encoding='utf-8').read())"`
- 変更前後のdiffレビュー（行数・差分の確認）
- 実際のブラウザ動作・音声読み上げ・Selenium連携は本リポジトリでは検証不可（越智さんのローカル環境での確認が必須）

### 必要な環境変数

- `GEMINI_API_KEY`: consolidated_html_summary_managerのTrack 0（全体概況）生成に使用（Python側、サーバーサイド）。未設定の場合はTrack 0生成をスキップ
- ブラウザ側のオンデマンドRSS要約生成（Gemini API直接呼び出し）は、localStorageに保存されたAPIキー（モーダルUIでユーザーが入力）を使用し、環境変数とは別管理

### 外部サービスへの依存

- Selenium + Chrome（デバッグポート接続）
- Gemini API（`google-genai` SDK、および ブラウザからの直接fetch）
- Glasp等の要約エンジン（youtube_summary_list側、詳細未確認）

## 8. Important Restrictions

### 変更禁止事項

- 明示的指示なしのUI・カラー変更（ライトテーマを維持すること）
- 既存バージョンファイルの上書き（新バージョンは新規ファイルとして追加する）
- 越智さんの承認（3フェーズワークフローのPhase 3相当）前のコード生成

### セキュリティ上の注意

- `GEMINI_API_KEY`等の秘密情報・APIキー・パスワード・認証情報をコミットしない
- ブラウザ側のAPIキーはlocalStorage保存であり、リポジトリ資産には含まれない

### 後方互換性に関する注意

- スキップモードの自動判定・手動固定ロジックは複数バージョンにわたり変更されてきた経緯があるため、変更前に必ず`docs/SESSION_HISTORY.md`で直近の仕様変更履歴を確認すること
- mode2の意味・挙動はVERSION 20260716_01で「pointsの本文読み上げ」から「見出しのみ読み上げ」に変更されている（過去の資料・コメントに古い説明が残っている場合は本ファイルの記述を優先する）
- mode1の挙動はVERSION 20260722_01で「一時的（次に上書きされるまでの単なる一回読み）」から「ワンショット（1カード読了後、切り替える直前にいたモードへ自動復帰）」に変更されている
