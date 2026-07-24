# OneNote Report Generator

OneNote上のプロジェクト議事録・進捗ページを Microsoft Graph API 経由で取得し、
Gemini AI で要約・構造化した上で、アコーディオン形式のHTMLレポートとして
自動生成する Flask アプリケーション。RPA（画面操作の自動化）による旧方式から、
Graph API 直接取得方式へ完全移行済み（`CHANGELOG.md` 参照）。

## 現在のVERSION

`20260706_01_01`（越智さんの実機 Windows/Chrome で稼働確認済み）

## 必要要件

- Python 3.9以上
- Microsoft Entra ID アプリ登録（`Notes.Read` / `Sites.Read.All` / `Group.Read.All` 権限）
- Gemini API キー

## セットアップ手順

1. 依存パッケージをインストールする。

   ```
   pip install -r requirements.txt
   ```

2. `config.example.json` を `config.json` にコピーし、環境に合わせて編集する。

   - `CLIENT_ID` / `TENANT_ID`：Entra ID アプリ登録の値
   - `GEMINI_API_KEY`：未設定の場合は環境変数 `GEMINI_API_KEY` からも読み込み可能
   - `sites`：対象とする SharePoint サイトの一覧（`displayName` + `site_id` のペア）。
     **同一 Microsoft 365 テナント内であれば、ここに複数サイトを追加するだけで
     UI 上のサイト選択ドロップダウンに反映される**（VERSION 20260512_03_01 で対応済み）。

3. スクリプトを実行する。

   ```
   python onenote_report_generator_20260706_01.py
   ```

   初回はブラウザで Device Code Flow の認証画面が開くので、表示されたコードで
   サインインする。認証トークンは `token_cache.bin` にキャッシュされ、以降は
   再認証不要（プロセス再起動時も有効。ただし現状はプロセス内グローバル変数
   `_token` もキャッシュに使っているため、サーバー再起動直後の1リクエスト目は
   `token_cache.bin` からの読み込みを経由する）。

4. `http://localhost:5000` が自動で開く。①サイト→②ノートブック→③セクション→
   ④ページ範囲→⑤対象ページを選択し、「レポート生成開始」を押す。

   - 選択状態（サイト・ノートブック・セクション・ページ・範囲指定）は
     ⭐ボタンで `bookmarks.json` に名前付き保存でき、次回以降ワンクリックで
     復元できる（VERSION 20260529_01_01）。

## システム構成

```
onenote_report_generator/
├── onenote_report_generator_20260706_01.py   ← メインFlaskアプリ（本体）
├── templates/
│   └── index.html                             ← VERSION 20260706_01_01 反映済み
├── config.example.json                        ← config.json のテンプレート（コミット対象）
├── requirements.txt
├── CHANGELOG.md
├── bookmarks.json                              ← 実行時に自動生成（.gitignore対象）
└── reports/                                    ← 生成済みHTMLレポート格納フォルダ（.gitignore対象）
```

### コアアーキテクチャ（3コンポーネント）

1. **`OneNoteGraphExtractor`**：Microsoft Graph API 経由で OneNote のサイト/
   ノートブック/セクション/ページを取得。`extract_with_color()` が HTML→テキスト
   変換を担当（青文字＝更新ポイントの判定、`<table>` の Markdown 表形式への変換）
2. **`GeminiProcessor`**：Gemini AI でテキストを要約・構造化 JSON 化
3. **`ReportGenerator.generate_html()`**：構造化 JSON からアコーディオン付き
   HTML レポートを生成

## 既知の未解決事項

- **bookmarks.json 破損時の自動復旧が未実装**：`_load_bookmarks()` は
  `json.JSONDecodeError` / `OSError` 発生時に `.bak` へリネームして空データで
  再生成するフォールバックを備えている（コード確認済み）。一方で、`config.json`
  読み込み（`load_config()`）はモジュール読み込み時に無条件で `json.load()` を
  呼んでおり、こちらが破損している場合は Flask 起動自体が失敗する。対応要否は
  越智さん未回答（保留中）。
- **CHANGELOG.md の正式記載**：本ファイルは越智さんからの引継ぎ資料を
  そのまま反映済み。
- **単一テナント/単一アカウント前提の認証設計**：`_token` / `_extractor` は
  グローバル変数として実装されており、複数ユーザー・複数テナントの同時
  アクセスには対応していない。同一テナント内の複数サイトは `config.json` の
  `sites` 配列で対応済み（上記参照）。

## 開発ルール

このプロジェクトを含む本リポジトリ全体の開発ルール（バージョン管理・
セッション管理）は、リポジトリ直下の `CLAUDE.md` を参照。
