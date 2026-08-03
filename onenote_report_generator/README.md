# OneNote Report Generator

OneNote上のプロジェクト議事録・進捗ページを Microsoft Graph API 経由で取得し、
Gemini AI で要約・構造化した上で、アコーディオン形式のHTMLレポートとして
自動生成する Flask アプリケーション。RPA（画面操作の自動化）による旧方式から、
Graph API 直接取得方式へ完全移行済み（`CHANGELOG.md` 参照）。

## 現在のVERSION

`20260729_02_01`（要約の出力言語モード追加。リモートセッションでの
自動テストのみ実施済み。越智さんの実機での確認は未実施）

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
   python onenote_report_generator_20260729_02.py
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
   - 「サマリーを逆順（新→古）に並べる」チェックボックス（既定ON）で、
     HTMLレポート内のページ表示順を制御できる。OneNoteのページが古い→新しい
     順の場合はON（既定）のまま、既に新しい→古い順の場合はOFFにする
     （VERSION 20260729_01_01）。Gemini解析時の「前回ページとの差分」抽出は
     この設定の影響を受けず、常にページ受け取り順のまま処理される。
   - 「要約の言語」選択（既定「日本語に翻訳して要約」）で、原文が英語・
     中国語等でも日本語に翻訳するか、原文の言語のまま要約するかを選べる
     （VERSION 20260729_02_01）。原文の言語判定はGemini自身のベストエフォート。

## システム構成

```
onenote_report_generator/
├── onenote_report_generator_20260729_02.py   ← メインFlaskアプリ（最新版）
├── onenote_report_generator_20260729_01.py   ← 旧バージョン（履歴保持のため残置）
├── onenote_report_generator_20260727_01.py   ← 旧バージョン（履歴保持のため残置）
├── onenote_report_generator_20260706_01.py   ← 旧バージョン（履歴保持のため残置）
├── templates/
│   └── index.html                             ← VERSION 20260729_02_01 反映済み
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

- **`config.json` 破損時は起動失敗**：`load_config()` はモジュール読み込み時に
  無条件で `json.load()` を呼んでおり、`config.json` が破損しているとFlask起動
  自体が失敗する（未対応）。なお `bookmarks.json` 側は `.bak` へリネームして
  空データで再生成するフォールバックが実装済み（S01でわざと破損させて動作確認済み）。
- **CHANGELOG.md の正式記載**：VERSION 20260706_01_01以前の記載は、越智さんからの
  引継ぎ資料をそのまま反映したもの。
- **単一テナント/単一アカウント前提の認証設計**：`_token` / `_extractor` は
  グローバル変数として実装されており、複数ユーザー・複数テナントの同時
  アクセスには対応していない。同一テナント内の複数サイト（他人のOneDrive・
  自分のOneDriveを含む）は `config.json` の `sites` 配列で対応可能（上記参照）。
- **トークン期限切れ時、画面上の「認証済み」表示自体は更新されない**：
  VERSION 20260727_01_01でノートブック/セクション/ページ取得時のエラー検知・
  自動再認証は追加したが、`/api/auth/status` / `/api/auth/poll` 自体は
  `_token`の有無のみを見ており、期限切れかどうかまでは確認していない
  （実際にエラーが起きるまでは「認証済み」の表示のまま）。
- **「原文の言語のまま要約」モードでの複数ページ言語混在**：ページごとに原文の
  言語が異なる複数ページレポート（例：先週は英語、今週は日本語）の場合、
  前回データとの差分比較用JSON（`prev_context`）の言語が混在する可能性がある
  （VERSION 20260729_02_01、未対応）。また`extract_with_color()`が付与する
  固定マーカー「【更新ポイント】」は原文が英語でも日本語のまま埋め込まれる。

## 開発ルール

このプロジェクトを含む本リポジトリ全体の開発ルール（バージョン管理・
セッション管理）は、リポジトリ直下の `CLAUDE.md` を参照。
