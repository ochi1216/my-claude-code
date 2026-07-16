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
├── CLAUDE.md                                          セッション管理ルール（本セットアップで新設）
├── README.md                                           未整備（タイトルのみ）
├── HANDOVER_youtube_summary_list.md                    youtube_summary_list系の引継ぎ資料
├── youtube_summary_list_20260703_01.py                 ベースライン（YouTube要約本体）
├── youtube_summary_list_20260711_01.py                 お気に入りチャンネル動画をHTML先頭に配置
├── consolidated_html_summary_manager_20260708_01.py    ベースライン（統合マネージャー本体）
├── consolidated_html_summary_manager_20260711_02.py    スキップモード手動固定の保持機能
├── consolidated_html_summary_manager_20260716_01.py    mode4追加・mode2/自動判定変更（最新版）
└── docs/
    ├── PROJECT_STATUS.md                               本ファイル
    ├── SESSION_HISTORY.md                               セッション履歴
    └── NEXT_TASK.md                                     次セッション用引継ぎ
```

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

### consolidated_html_summary_manager

- 複数の`summary_*.html`ファイルを走査・パースし、DB（`summary_database.json`）にマージして統合HTMLを生成
- お気に入り／未読／プレイリスト種別によるフィルタ・ソート・既読管理（localStorage）
- 保持期間（`RETENTION_DAYS=7`）に基づくアーカイブ・自動クリーンアップ
- Gemini APIによる全体概況（Track 0）生成、RSS記事のオンデマンド結論・ポイント生成
- **スキップモード（読み上げモード）0〜4**（VERSION 20260716_01時点）:
  - mode0（▶▶・標準）: title → summary → 次へ
  - mode1（▶・一時）: title → summary → points（あれば）→ 次へ
  - mode2（▶・固定、青塗りつぶし）: title → summary → **主なポイントの見出しのみ**（本文非読み上げ・アコーディオン非展開）→ 次へ
  - mode3（▶▶▶・タイトルのみ）: title → 次へ
  - mode4（▶・緑枠）: title → summary → conclusion（あれば）→ 次へ
- 手動でモードを選択した場合、mode2以外は「同一ファイルを聴いている間 or 再生停止まwhile」保持。mode2は従来通りファイル切替・停止に関わらず永続的に保持

## 4. Confirmed Specifications

- **自動判定の優先順位**（`applyAutoSkipMode`、20260716_01時点）:
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

## 5. Current Status

### 完了済み

- youtube_summary_list: ベースライン取り込み、お気に入りチャンネル動画のHTML先頭配置（VERSION 20260711_01）
- consolidated_html_summary_manager: ベースライン取り込み、スキップモード手動固定のファイル切替/停止までの保持（VERSION 20260711_02）、mode4（title+summary+conclusion）追加、mode2の見出しのみ読み上げ化、自動判定優先順位の変更（VERSION 20260716_01）
- 本ドキュメント一式（`CLAUDE.md`・`docs/`）の初期セットアップ

### 作業中

- なし（本セットアップ完了時点）

### 未着手

- youtube_summary_list側の`config/playlists.json`未参照問題の整理（HANDOVER記載、スコープ外合意済み）
- `datetime.min`安全ガード（`upload_time`のNone処理、HANDOVER記載、別パッチ扱いで未着手）
- 兄弟ツール（`Youtube_List_Setup`等）は本リポジトリの管理対象外（未確認）

## 6. Known Issues

- **RSS記事のconclusion/points未生成状態**: consolidated_html_summary_managerのRSSカードは、オンデマンド生成（「主なポイントを生成」ボタン）前は`conclusion`/`points`が空。mode2・mode4選択時、空の場合は読み上げをスキップして次のカードへ進む仕様（意図的な設計）
- **クラウド環境での動作確認不可**: 本ツールはSelenium+Chrome debugポート+ローカルファイル前提のブラウザGUIのため、クラウド開発環境では実ブラウザでの動作確認ができない。構文チェック（`ast.parse`）とdiffレビューのみ実施し、実動作確認は越智さんのローカル環境に依存する
- **youtube_summary_list側の既知の罠（HANDOVER記載、要再確認）**:
  - `config/playlists.json`は存在するがコードから未参照（プレイリストIDの実体は`get_playlist_config()`内のハードコード）
  - BATファイルは`dir /b /o-n`の名前降順で最初の1件を実行するため、ファイル命名次第で意図しないバージョンが動く可能性がある
- 上記のうちHANDOVER記載の「argparse choicesに'V'が未登録」「all_playlists_var初期値」の2件は、`youtube_summary_list_20260711_01.py`時点で修正済みであることを確認済み（詳細は`SESSION_HISTORY.md` S01参照）

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
