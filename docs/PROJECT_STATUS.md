# Project Status

## 1. Project Overview

- **プロジェクト名**: Youtube Manager 統合開発環境
- **プロジェクトの目的**: YouTubeプレイリスト動画の自動要約・RSS記事要約を生成し、それらのHTMLサマリーを1つの管理画面（統合マネージャー）にまとめて、音声読み上げ（TTS）付きで効率的にレビューできるようにする一連のPythonツール群を開発・保守する。
- **主な利用者**: 越智さん（プログラム初心者と自認・厳格な3フェーズ開発ワークフローを運用）
- **実行環境**:
  - OS: Windows（越智さんのローカル環境）
  - Python 3.13（固定パス起動）
  - Chrome（デバッグポート9222、専用プロファイル）+ Selenium
  - Tkinter GUI（ライトテーマ`#f0f0f0`固定、UI変更は明示的指示がない限り禁止）
  - ブラウザ側はSpeechSynthesis API（音声読み上げ）とlocalStorageを使用
  - 本リポジトリ（クラウド開発環境）にはSelenium/Chrome実行環境がないため、実際のブラウザ・GUI動作確認は越智さんのローカル環境で行う

## 2. Repository Structure

リポジトリはフラット構成（サブディレクトリなし、`docs/`のみ今回新設）。

```
my-claude-code/
├── CLAUDE.md                                          セッション管理ルール
├── README.md                                           未整備（タイトルのみ）
├── HANDOVER_youtube_summary_list.md                    youtube_summary_list系の引継ぎ資料
├── youtube_summary_list_20260703_01.py                 旧版
├── youtube_summary_list_20260711_01.py                 旧版
├── youtube_summary_list_20260725_01.py                 旧版
├── youtube_summary_list_20260725_02.py                 旧版
├── youtube_summary_list_20260801_01.py                 旧版（Glaspボタン検出をアイコンクラス名ベースに変更）
├── youtube_summary_list_20260801_02.py                 旧版（Glaspリトライ回数2→5）
├── youtube_summary_list_20260801_03.py                 最新版（未使用UI設定整理・Glasp起動方式に本物クリック(CDPマウス)追加）
├── consolidated_html_summary_manager_20260708_01.py    旧版
├── consolidated_html_summary_manager_20260711_02.py    旧版
├── consolidated_html_summary_manager_20260716_01.py    旧版
├── consolidated_html_summary_manager_20260722_01.py    旧版
├── consolidated_html_summary_manager_20260722_02.py    最新版（Track 0のGeminiモデル修正）
├── run_youtube_summary_auto.bat                        youtube_summary_list起動用（Chromeデバッグプロファイル起動込み）
├── run_youtube_List_auto_setup.bat                     Youtube_List_Setup起動用
├── run_youtube_channel_remove_auto.bat                 チャンネル解除ツール起動用
├── run_youtube_all_tasks.bat                           旧・一括起動用（要用途確認）
└── docs/
    ├── PROJECT_STATUS.md                               本ファイル
    ├── SESSION_HISTORY.md                               セッション履歴
    ├── NEXT_TASK.md                                     次セッション用引継ぎ
    └── decisions/                                       重要設計判断のADR
```

※越智さんのローカル作業フォルダには本リポジトリ対象外の関連ツール（`Youtube_List_Setup_*.py`・`Youtube_Playlist_management_*.py`等）や大量の旧版・ログ・バックアップファイルが存在する。S02にて整理対象の棚卸しを実施済み（詳細は本ファイル未記載・チャット上のみ、越智さんのローカル作業）。

### 各ファイルの役割

- **`youtube_summary_list_*.py`**: Selenium+Chrome（デバッグポート接続）でYouTubeプレイリストを走査し、動画を要約してHTMLレポートを生成するツール本体。Tkinter GUI・Automode対応。
- **`consolidated_html_summary_manager_*.py`**: `youtube_summary_list`等が出力した複数の`summary_*.html`（YouTube・RSS由来）を1つのHTML（`_Consolidated_Manager.html`）に統合し、既読管理・フィルタ・音声読み上げ（スキップモード0〜4）付きで閲覧するための管理ツール。
- **`HANDOVER_youtube_summary_list.md`**: `youtube_summary_list`系の開発経緯・既知の罠・3フェーズ開発ワークフローに関する引継ぎ資料（越智さん作成）。

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

### 作業中

- Glasp自動起動の信頼性改善（S02から継続）。次の一手として「バッチ処理の2フェーズ化」（トリガーラウンド→検出/リトライラウンド）の設計に合意済みだが未実装。詳細は`docs/decisions/0001-glasp-batch-trigger-detect-redesign.md`と`NEXT_TASK.md`を参照

### 未着手

- youtube_summary_list側の`config/playlists.json`未参照問題の整理（HANDOVER記載、スコープ外合意済み）
- `datetime.min`安全ガード（`upload_time`のNone処理、HANDOVER記載、別パッチ扱いで未着手）
- 兄弟ツール（`Youtube_List_Setup`等）は本リポジトリの管理対象外（未確認）
- youtube_summary_list_20260801_03.pyの「本物クリック（CDPマウス）」オプションの実地検証（越智さんのローカル環境での実行結果待ち）

## 6. Known Issues

- **【未解決・優先度高】youtube_summary_listのGlasp自動起動が低成功率（S02時点）**:
  - 症状: きらきらボタンのクリック自体は成功する（`cdp_button=True`）が、Geminiタブが検出されない（`glasp_tab_detect=False`）失敗が多数発生。リトライ回数を2→5に増やしても改善せず（直近の実行結果は3/26本成功）
  - 判明した事実:
    - Glasp拡張機能は最新版（v2.3.0）に更新済み。更新前後で完全ノーヒットからは改善したが、依然として過半数が失敗
    - 失敗した動画タブでも、後で手動できらきらボタンを1クリックすれば高い確率でGemini/ChatGPTが起動する
    - Glaspのボタンをクリックすると、YouTube側に「文字起こし」パネル（AIによる文字起こし・チャプター生成、完了までスピナー表示）が開く。これはクリックの**結果**であり、クリック前に存在を確認できる条件ではない
    - このパネルの完了を待たずに現在のコードは動いており、かつ検出失敗時は`driver.refresh()`でページを再読み込みするため、生成途中の状態がリセットされている可能性がある
    - パネルの挙動には複数パターンがある（パネルが出ずに成功するケース、UIパターンが複数存在するケース、待っても永久にスピナーが終わらないケース）
  - 現在の仮説: バックエンド側の文字起こし生成に相応の実時間がかかることがあり、同一動画に対して数秒間隔で即座に再クリックしても状況は変わらない。放置して他の処理をしている間に自然と完了することが多い
  - 次の対策案（設計合意済み・未実装）: `docs/decisions/0001-glasp-batch-trigger-detect-redesign.md`参照。バッチ内の全動画に対して「まず1回ずつクリックする」トリガーラウンドを先に済ませ、その後まとめて検出・必要なら再クリックする2フェーズ方式に変更する
- **RSS記事のconclusion/points未生成状態**: consolidated_html_summary_managerのRSSカードは、オンデマンド生成（「主なポイントを生成」ボタン）前は`conclusion`/`points`が空。mode2・mode4選択時、空の場合は読み上げをスキップして次のカードへ進む仕様（意図的な設計）
- **クラウド環境での動作確認不可**: 本ツールはSelenium+Chrome debugポート+ローカルファイル前提のブラウザGUIのため、クラウド開発環境では実ブラウザでの動作確認ができない。構文チェック（`ast.parse`）とdiffレビューのみ実施し、実動作確認は越智さんのローカル環境に依存する
- **youtube_summary_list側の既知の罠（HANDOVER記載、要再確認）**:
  - `config/playlists.json`は存在するがコードから未参照（プレイリストIDの実体は`get_playlist_config()`内のハードコード）
  - BATファイルは`dir /b /o-n`の名前降順で最初の1件を実行するため、ファイル命名次第で意図しないバージョンが動く可能性がある
- 上記のうちHANDOVER記載の「argparse choicesに'V'が未登録」「all_playlists_var初期値」の2件は、`youtube_summary_list_20260711_01.py`時点で修正済みであることを確認済み（詳細は`SESSION_HISTORY.md` S01参照）
- ~~Gemini APIモデルの不整合~~: `_generate_overview_file`（Track 0全体概況生成、Python側、320行目付近）が`gemini-2.0-flash`のままだった問題は、VERSION 20260722_02で`gemini-2.5-flash`に修正済み
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

- **youtube_summary_list**: `python youtube_summary_list_YYYYMMDD_NN.py`（通常起動）または`--auto --playlists V S A B N M`等（Automode）。Windows・Python 3.13固定パス・Chrome debugポート9222が前提
- **consolidated_html_summary_manager**: `python consolidated_html_summary_manager_YYYYMMDD_NN.py`を対象フォルダ（`summary_*.html`が置かれたフォルダ）で実行し、生成された`_Consolidated_Manager.html`をブラウザで開いて確認

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
