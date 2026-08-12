# PROJECT_STATUS — OneNote Report Generator

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
