# Document Search Manager — CHANGELOG

## VERSION 20260903_03

会社PCでの実機動作を確認したうえで、表示上の不具合修正と件数選択肢の追加を行った。

### 実機で確認できたこと（重要）

- **Graph `/search/query` が `Sites.Read.All` のみで正常に動作した。**
  疎通診断は `search-api` モードで通り、キーワード `validation` で50件を取得できた。
  懸念していた権限不足のリスクは解消し、**新規のEntra ID権限申請は不要と確定**した。

### 修正

- **タイトル・種別が全件空になる不具合**
  Graphの `listItem` は既定でタイトル等のメタデータを返さないため、画面上で
  すべての行が `(タイトルなし)` と表示され、「種別」列も空になっていた。
  以下の二重の対策で修正した。
  - 検索リクエストに `fields`（検索マネージドプロパティ）を明示的に要求する。
    要求する項目は `config.json` の `search_fields` で調整できる。
  - `fields` が返らなかった場合に備え、**リンク先URLの末尾からファイル名を復元**して
    タイトル・拡張子に充てるフォールバックを追加した（`_name_from_url`）。
    URLエンコード（`%20` や日本語）はデコードして表示する。
  - `search_fields` に指定した名前がテナントに存在せずHTTP 400になった場合は、
    **`fields` 無しで自動的に1度だけ再試行**し、以後は要求しない
    （URL由来のフォールバックで表示は維持される）。

### 追加

- 件数プルダウンに **「上位 10 件」「上位 25 件」** を追加（従来は50/100/200/500）。
  開発中の試行錯誤で結果が多すぎないようにするため。
- プルダウンの初期選択値を `config.json` の `default_max_results` から反映するようにした。
  ハードコードをやめたため、**開発段階は10件、運用段階は100件**といった切り替えが
  設定だけで可能になった。`config.example.json` の既定値は開発段階向けに `10` とした。
- `GET /api/config` エンドポイントを追加（画面表示用の設定のみを返す。
  `tenant_id` / `client_id` は返さない）。

### 変更しないこと（宣誓）

- `document_search_manager_20260903_01.py` / `_02.py` は削除・上書きせず、そのまま残す。
- 認証処理（`GraphAuthManager` / `_load_config`）には一切手を入れていない。
- 検索の並列実行・重複排除・エクスポートのロジックは変更していない。
- `po_database_organizer/` 等、他ツールのファイルは一切変更しない。

### 検証結果

- `python -m py_compile` による構文チェック: 合格。
- 本バージョンの新規検証（26項目、すべて合格）:
  - 実機で発生した「fieldsが返らない」レスポンス形をそのまま再現し、
    タイトル・種別がURLから正しく復元されること（`%20`・日本語のデコードを含む）
  - `fields` が返った場合は `fields` の値を優先すること
  - `fields` 指定がHTTP 400で拒否された際に、fields無しで自動再試行し、
    以後は最初からfields無しで呼ぶこと
  - 件数プルダウンに10/25/50/100/200/500が並び、初期選択値が設定から反映されること
  - `/api/config` が機密情報（tenant_id / client_id）を返さないこと
- 既存の検証ハーネスを v20260903_03 に対して再実行:
  **検索ロジック56項目・設定読み込み9項目とも全項目合格**（累計91項目）。
- ブラウザ描画確認（Playwright）: タイトル・種別が表示され、
  件数プルダウンが「上位 10 件」で初期選択されることを確認。

### 未実施（実機でのみ確認可能）

- 結果リンクが `.mcas.ms` 経由のブラウザで開けるかの確認。
- `search_fields` の各項目が実テナントで有効かどうかの確認
  （無効ならHTTP 400を検知して自動フォールバックする）。

## VERSION 20260903_02

実機（会社PC）での初回起動時に発生した2件の不具合を修正。

### 修正

- **起動バッチの文字化けエラー**
  `run_document_search_manager.bat` の日本語コメントがUTF-8で保存されていたため、
  Windowsのコマンドプロンプト（CP932）が解釈できず、
  `'蜍輔＠縺ｦ...' は、内部コマンドまたは外部コマンドとして認識されていません`
  というエラーが表示されていた（実害はなく処理自体は継続していた）。
  バッチ内のコメントをASCII（英語）のみに変更し、改行コードをCRLFに統一した。
- **tenant_id / client_id の流用元が見つからず起動できない問題**
  `po_database_organizer/config.json` は `.gitignore` で除外されているため、
  `git pull` しただけの環境には存在しない。流用元が1箇所しかなかったため、
  そこに無いと即座に起動失敗していた。以下のように改善した。
  - 流用元の候補を複数化（`po_database_organizer` → `onenote_report_generator` の順に探索）。
  - キー名の表記揺れに対応（`tenant_id` / `TENANT_ID` の両方を受け付ける）。
    `onenote_report_generator` は大文字キーを使用しているため。
  - プレースホルダ（`<YOUR_TENANT_ID>` のような `<` 始まりの値）は未設定として扱い、
    次の候補へ進む。
  - 流用元のJSONが壊れていても停止せず、次の候補へ進む。
  - 2つの候補から `tenant_id` と `client_id` を1つずつ拾って合成することも可能。

### 追加

- `config.json` に **`credentials_from`** を追加。既存ツールの `config.json` が
  別の場所にある場合、フルパスを指定すると最優先で参照する。
- 起動失敗時のエラーメッセージを改善。探索したパスをすべて列挙し、
  対処方法（直接記入する／`credentials_from` を指定する）を具体的に表示する。

### 変更しないこと（宣誓）

- `document_search_manager_20260903_01.py` は削除・上書きせず、そのまま残す。
- 検索ロジック（`SharePointProvider` / `SearchManager` / パーサ）には一切手を入れていない。
  本バージョンの変更は `_load_config` / `_read_credentials` / 起動バッチに限定される。
- `po_database_organizer/` / `onenote_report_generator/` 配下のファイルは一切変更しない
  （`config.json` は読み取りのみ）。

### 検証結果

- `python -m py_compile` による構文チェック: 合格。
- 設定読み込みの新規検証（9項目、すべて合格）:
  - 流用元がどこにも無い場合に、分かりやすいメッセージで終了する
    （越智さんの環境で発生した状況の再現）
  - `po_database_organizer` からの借用（小文字キー）
  - `onenote_report_generator` からの借用（大文字キー）と、無関係なキー
    （`GEMINI_API_KEY` 等）を取り込まないこと
  - プレースホルダを飛ばして次の候補を使うこと
  - `config.json` への直接記入が最優先されること
  - `credentials_from` による明示指定が最優先で参照されること
  - 壊れたJSONの候補があっても停止せず次へ進むこと
  - 2つの候補から1項目ずつ拾って合成できること
- v20260903_01 の全56項目の検証ハーネスを v20260903_02 に対して再実行: **全項目合格**。

## VERSION 20260903_01

初版（Phase 1: SharePoint全社検索 MVP）。

### 追加

- `document_search_manager_20260903_01.py` を新規作成。
- Microsoft Graph Search API (`POST /search/query`, `entityTypes: listItem`) による
  社内SharePoint全社横断検索を実装。
- 検索対象の選択UI（`0. All` / `1. SharePoint` / `2. Nexus` / `3. Enovia`）を実装。
  既定は `0. All`。
- 検索結果の正規化スキーマ `SearchResult` を定義
  （ソース / Document Number / タイトル / 作成者 / 最終更新日 / 種別 / サイト / リンク）。
- 疎通診断機能（起動時および画面の「疎通診断」ボタン）。
  `/search/query` が権限不足だった場合、サイト単位検索
  （`GET /sites/{host}:{path}:/drive/root/search`）へ自動フォールバックする。
- 複数系統の並列実行（`ThreadPoolExecutor`）と部分成功方式。
  系統ごとに 🟢成功 / 🟡0件 / 🔴エラー / ⚪未実装 を表示する。
- Excel（openpyxl）/ CSV 出力。
- Flask UI（`http://127.0.0.1:5020`）。ダークテーマ（bg `#1a1a2e` / accent `#e94560`）。
- `run_document_search_manager.bat`（`cd /d %~dp0` により起動場所に依存しない）。

### 設計上の決定

- **認証は既存の `po_database_organizer` と同一のEntra IDアプリ登録を流用する。**
  要求スコープは `Sites.Read.All` のみで、新規のGraph権限申請は発生させない。
  `config.json` の `tenant_id` / `client_id` が空の場合、
  `../po_database_organizer/config.json` から自動的に借用する（読み取りのみ）。
- トークンキャッシュは `document_search_manager/token_cache.json` に分離する
  （`po_database_organizer` と同時起動した際の書き込み競合を避けるため）。
- 設定・キャッシュ・出力のパスはすべて `Path(__file__).resolve().parent` 基準で解決する
  （カレントディレクトリに依存しない）。
- Nexus（Shareflex）の全文検索は、調査の結果 SharePoint 標準の
  `RenderListDataAsStream` + `InplaceSearchQuery` で実装されていることを確認済み。
  同一の SharePoint 検索インデックスを参照するため、Phase 2 では Graph Search を
  `nexus_folder_path` に限定する方式で等価な検索を行う。
  SharePoint REST を直接呼ぶ方式は、MCASのセッション認証（`McasUserAuth`）の再現が
  必要かつ新規権限を要するため採用しない。
- `dedupe_nexus_from_sharepoint` は Phase 1 では `false`。
  Nexusプロバイダが未実装の段階で除外すると、Nexus文書が一切見えなくなるため。
  Phase 2 で Nexus プロバイダを有効化するのと同時に `true` にする。

### 変更しないこと（宣誓）

- `po_database_organizer/` 配下のファイルは一切変更しない
  （`config.json` は読み取りのみで、書き換えない）。
- `shareflex_dashboard/` / `rtocs_organizer/` / `outlook_total_organizer/` /
  `onenote_report_generator/` 配下は一切変更しない。

### 検証結果

- `python -m py_compile` による構文チェック: 合格。
- スタンドアロン検証ハーネス（ネットワーク非依存）: **56項目すべて合格**。
  - Graph Search レスポンスのパース（`fields` 有無・空hit・カスタム列の各パターン）
  - 日付のJST変換、拡張子抽出、MCASホスト書き換え、サイトURL分解
  - ページング（25件×4回で100件打ち切り、途中エラー時の部分成功、初回エラー時の例外）
  - Nexus重複排除（Phase 1既定=除外しない／Phase 2想定=除外する）
  - 未実装系統の扱い（単独指定時・All指定時とも「未実装」として表示される）
  - Flaskエンドポイント（`/`, `/api/search`, `/api/probe`, `/api/export`）
- ブラウザ描画確認（Playwright、ダミーデータ）: ダークテーマ・結果テーブル・
  系統別ステータス・ログ表示がすべて意図通りに描画されることを確認。

### 未実施（実機でのみ確認可能）

- Graph `/search/query` が `Sites.Read.All` のみで通るかの確認（会社PCでの疎通診断）。
- 結果リンクが `.mcas.ms` 経由のブラウザで開けるかの確認。
- キーワード `validation` による、Nexus画面とツール結果の突き合わせ。
