# Project Status

## 1. Project Overview

- **プロジェクト名**: SE Strategy オーガナイザー
- **プロジェクトの目的**: 業務データ（RTOCS講義事例、SharePoint上のPO書類、Shareflex品質文書、YouTube動画等）を自動収集・整理・分析し、レポートやダッシュボードとして可視化する複数の業務支援ツール群を1つのリポジトリで管理・開発する。
- **主な利用者**: 越智さん（本リポジトリのオーナー。ツールによって「アナログ半導体のシニアシステムエンジニア」「プログラム初心者と自認する厳格なワークフロー運用者」等、異なる立場で利用）。
- **実行環境**: 未確認（各サブツールはWindows上のローカルPython実行を前提としている記述が複数の引継ぎ資料・READMEに見られるが、リポジトリ自体はGit/GitHub上で管理され、Claude Code Web/CLIから開発される）。

## 2. Repository Structure

### 主要ファイル（リポジトリ直下）

| ファイル | 役割 |
|---|---|
| `README.md` | リポジトリ全体の入口。各サブツールへのリンクと開発ルール（バージョン管理規約）を記載 |
| `CLAUDE.md` | Claude Code Webセッション管理ルール（本セットアップで新規作成） |
| `.gitignore` | ローカル設定・認証キャッシュ等の除外設定 |
| `HANDOVER_analog_ic_scout.md` | 未着手構想「analog_ic_scout（仮称）」の引継ぎ資料（設計段階のみ、実装未着手） |
| `HANDOVER_youtube_summary_list.md` | `youtube_summary_list` プロジェクトの引継ぎ資料（3フェーズ厳格ワークフローの運用ルールを含む） |
| `youtube_summary_list_20260703_01.py` / `youtube_summary_list_20260711_01.py` | YouTubeプレイリスト動画の自動要約・HTMLレポート生成ツール本体（バージョン別に併存） |

### 主要フォルダ

| フォルダ | 役割 |
|---|---|
| `rtocs_organizer/` | BBT「大前研一ライブ」RTOCSコーナーの講義動画自動取得・要約ツール、および蓄積データの傾向分析・企業戦略策定パイプライン一式 |
| `po_database_organizer/` | SharePoint上のPO（パーチャスオーダー）関連書類をスキャンし、Project×Vendor×PO番号のカタログを生成するツール |
| `shareflex_dashboard/` | Nexus品質文書管理サイト（Shareflex/SharePoint）のエクスポートExcelから、組織軸・プロセス軸の集計ダッシュボード（静的HTML）を生成するツール |

### 各サブフォルダ共通構成

各ツールフォルダは概ね以下を含む：
- `README.md`（セットアップ手順・既知の制限）
- `CHANGELOG.md`（バージョンごとの変更履歴）
- `requirements.txt`（依存パッケージ）
- 本体スクリプト（`ツール名_yyyymmdd_連番.py` 形式）

## 3. Current Functions

- **rtocs_organizer**: RTOCS講義動画の自動取得・Gemini要約・HTMLレポート化（`rtocs_organizer_20260711_01.py`）。加えて、蓄積データを横断分析するStreamlitダッシュボード（`rtocs_dashboard_20260715_04.py`、最新）に以下3タブを実装済み：
  1. 一覧・検索
  2. 傾向分析（業界分布年次推移、キーワード頻度・トレンド、地域ミックス、AI俯瞰総評）
  3. 戦略分析（企業名入力→会社分析→直近ニュース収集(英/日/中)→株式市場分析→業界・競合分析→類似事例選定→他業種事例分析→課題分析→戦略策定の一気通貫パイプライン、通常/ディープの2モード）
- **po_database_organizer**: SharePoint（Graph API + MSAL Device Code Flow）からPO関連書類をスキャンし、Excel/JSON形式のカタログを生成（Phase 1: PO番号抽出のみ、ステータス自動判定は未実装）。
- **shareflex_dashboard**: SharePointエクスポートExcelを読み込み、Department軸・Top Level Process軸の階層別ドキュメント件数を集計した静的HTMLダッシュボードを生成（オフライン完結、外部リソース読込なし）。
- **youtube_summary_list**: YouTubeプレイリスト動画をSelenium+Chrome（デバッグポート接続）とGlasp/API要約エンジンで自動要約し、HTMLレポートを生成。

## 4. Confirmed Specifications

- **バージョン管理規約（リポジトリ全体）**: ファイル更新時は `ツール名_yyyymmdd_連番.py` 形式のファイル名で新規追加し、旧バージョンは削除・上書きしない。各ツールフォルダに `CHANGELOG.md` を置き変更点を記録する（`README.md` 記載）。
- **rtocs_organizer 戦略分析**: 各分析ステージが失敗しても処理を止めず、レポート内に「取得失敗」として表示し、部分的なレポートは必ず生成する方針。
- **po_database_organizer**: PO番号以外の文書種別自動分類・ステータス自動判定は行わない方針（Phase 1のスコープ外、意図的な設計判断）。
- **shareflex_dashboard**: SharePointへの自動接続は行わず、手動エクスポート→ローカル集計のオフライン構成を維持する方針（社内ポリシー・`.mcas.ms`プロキシ制約への対応）。
- **youtube_summary_list**: 3フェーズワークフロー（Design Proposal→Architecture Audit→Implementation Patch）を厳守し、明示的承認なしにコード生成しない運用ルールが定められている（`HANDOVER_youtube_summary_list.md`）。UI・カラーの無断変更も禁止。

## 5. Current Status

### 完了済み
- rtocs_organizer 本体（動画取得・要約）および統合ダッシュボード（一覧・検索／傾向分析／戦略分析の3タブ、直近ニュース収集ステージ含む）
- po_database_organizer Phase 1（PO本体の認識・カタログ生成）
- shareflex_dashboard（組織軸・プロセス軸の集計ダッシュボード生成）
- youtube_summary_list 本体（複数バージョン併存）
- 本セッションでのセッション管理用ファイル一式の初期セットアップ

### 作業中
- 特になし（未確認。次セッションの指示待ち）

### 未着手
- analog_ic_scout（仮称、TIアナログ製品分析ツール）: 構想・設計のみ完了、実装未着手（`HANDOVER_analog_ic_scout.md`）
- po_database_organizer Phase 2（文書種別自動分類、ステータス遷移ルール）

## 6. Known Issues

### 既知の問題
- `rtocs_organizer`: `BASE_DIR` が特定ユーザー名のパスでハードコードされている。
- `rtocs_organizer`: `RTOCSConfigGUI` クラスがファイル内で2重定義されており、後方の定義が前方を上書きしている（デッドコードあり）。
- `po_database_organizer`: Vendorフォルダ配下の再帰探索が `max_depth`（デフォルト6階層）で打ち切られ、極端に深いフォルダ構成では取りこぼしが発生し得る。
- `shareflex_dashboard`: ヘッダー行の自動検出（「Document Number」列を含む行）に依存しており、エクスポート時に列名・列順が大きく変わると読み込みに失敗する可能性がある。

### 暫定対応
- `rtocs_organizer` のニュース収集ステージのみ `google-genai`（新SDK）に切り替え、他7ステージは `google-generativeai`（旧SDK）のまま併存させている（`google_search_retrieval` 非サポート化への対応、CHANGELOG参照）。

### 技術的リスク
- `google-generativeai` はGoogle公式に開発終了宣言済みであり、将来的に他ステージも移行が必要になる可能性がある。
- 検索グラウンディングによるニュース収集はベストエフォート実装であり、モデル世代によっては機能しない可能性がある。

## 7. Test and Execution

### 起動方法
- `rtocs_organizer`: `streamlit run rtocs_dashboard_20260715_04.py`（`pip install -r requirements.txt` 後）
- `po_database_organizer`: `python po_database_organizer_20260713_01.py`（`config.json` 準備後、`http://127.0.0.1:5010` が自動起動）
- `shareflex_dashboard`: `python shareflex_dashboard_20260713_01.py <export.xlsx>`
- `youtube_summary_list`: 未確認（Windows環境・固定パスPython実行が前提と引継ぎ資料に記載）

### テスト方法
未確認（自動テストスイートの有無は未確認。各ツールとも手動実行・実データでの動作確認に依拠している模様）。

### 必要な環境変数
- `rtocs_organizer`: `GEMINI_API_KEY`
- `po_database_organizer`: 環境変数ではなく `config.json`（`tenant_id`, `client_id` 等、Entra IDアプリ登録情報）
- `shareflex_dashboard`: なし（オフライン完結）
- `youtube_summary_list`: 未確認

### 外部サービスへの依存
- `rtocs_organizer`: Gemini API（要約・検索グラウンディング）、`yfinance`（上場企業の株価・財務データ）、Google Chrome（リモートデバッグ接続）
- `po_database_organizer`: Microsoft Graph API（SharePoint、MSAL Device Code Flow認証）
- `shareflex_dashboard`: なし（SharePointからは手動エクスポートのみ）
- `youtube_summary_list`: Selenium + Chrome（デバッグポート接続）、Glasp/API要約エンジン

## 8. Important Restrictions

### 変更禁止事項
- 各ツールフォルダの過去バージョンファイル（`_yyyymmdd_連番.py`）は削除・上書きしない。
- `youtube_summary_list` はUI・カラーの無断変更禁止（ライトテーマ維持、明示的指示が必要）。

### セキュリティ上の注意
- `po_database_organizer` の `config.json`、`token_cache.json`、`cache/` は `.gitignore` で除外済み（認証情報・キャッシュのローカル限定）。
- APIキー・認証情報（`GEMINI_API_KEY`、`tenant_id`/`client_id`等）はコミットしない。

### 後方互換性に関する注意
- バージョン別ファイル運用（新バージョンは新規ファイルとして追加）を維持し、既存の安定版ファイルへの上書きは行わない。
- `rtocs_organizer` の戦略分析パイプラインは、1ステージの失敗が他ステージに影響しない設計を維持する（部分的失敗時も部分レポートを生成する方針を崩さない）。
