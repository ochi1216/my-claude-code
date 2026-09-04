# Document Search Manager

社内のドキュメント管理システムを、**同一キーワードで横断検索**するツール。

| 選択肢 | 対象 | 状態 |
|---|---|---|
| `0. All` | 有効な全系統を並列検索（既定） | ✅ 稼働（SharePoint ＋ Nexus ＋ Enovia） |
| `1. SharePoint` | 社内SharePoint全社横断検索 | ✅ **Phase 1で実装済み** |
| `2. Nexus` | Shareflex品質文書サイト（SF_QualityDocumentsProd） | ✅ **Phase 2で実装済み** |
| `3. Enovia` | 3DEXPERIENCE / ENOVIA | ✅ **Phase 3で実装済み**（利用にはEnoviaへのログインが必要。後述） |

未実装の系統があれば、UI上に「実装予定」と明示されます（黙って0件を返しません）。

**「タイトルだけを検索する」**（既定オン）をオフにすると、文書の本文まで
検索します。オンのままのほうが目的の文書に辿り着きやすく、オフにすると
件数が大きく増えます。

Nexusタブには**有効期限**の列があり、期限を過ぎた標準書には **「期限切れ」**、
60日以内に切れるものには **「まもなく」** のバッジが付きます。
有効期限の列で「この日以前」に今日の日付を入れると、
**期限切れの標準書だけを抽出**できます。

画面は**系統ごとのタブ**になっており、**タブごとに表の列構成が切り替わります**。
SharePointとNexusでは持っている情報が違うためです（Nexusの実体はShareflexで、
フォルダ名が内部ハッシュになる一方、SharePointには無い標準Indexを持ちます）。

## 必要要件

- Python 3.9以上
- 対象SharePointへの閲覧権限（**新規のEntra ID権限申請は不要**）

## 認証について（重要）

本ツールは **`po_database_organizer` と同一のEntra IDアプリ登録をそのまま流用**します。
要求スコープは **`Sites.Read.All` のみ**で、新規のGraph権限申請は一切発生しません。

- `config.json` の `tenant_id` / `client_id` を空のままにしておくと、既存ツールの
  `config.json` から自動的に借用します（**読むだけ**で書き換えません）。探索順は
  `../po_database_organizer/config.json` → `../onenote_report_generator/config.json` で、
  キー名は小文字（`tenant_id`）・大文字（`TENANT_ID`）の両方に対応します。
- 既存ツールの `config.json` がどちらにも無い場合は、`config.json` の `credentials_from` に
  フルパスを指定するか、`tenant_id` / `client_id` を直接記入してください（後述）。
- トークンキャッシュは本フォルダ内の `token_cache.json` に分離して保存します
  （`po_database_organizer` と同時に起動しても競合しません）。そのため初回だけ、
  本ツール用のデバイスコード認証が1回必要です。

**EnoviaはGraph / Entra IDとは完全に別の認証**（3DEXPERIENCEのCAS・Cookie）
です。詳しくは次の「Enoviaへのログイン」を参照してください。

## Enoviaへのログイン（重要）

Enovia検索を使うには、**画面の「Enoviaにログイン」ボタン**を1回押す必要があります。

1. 「Enoviaにログイン」ボタンを押すと、**会社PCに入っているEdge**が別ウィンドウで
   開きます（Playwright用の新しいブラウザをダウンロードすることはありません）。
2. 開いた画面でEnoviaにログインします。**1日1回など、既にログイン済みであれば
   そのままEnoviaのトップ画面が表示されます。**
3. ログインできたら、**そのウィンドウを閉じてください。** 閉じたタイミングで
   ログイン情報（Cookie）が `enovia_session.json` に保存され、以後の検索は
   ブラウザを起動せず高速に行われます。
4. Cookieには有効期限があります。検索がエラーになったら、もう一度
   「Enoviaにログイン」を実行してください。

**`enovia_session.json` は `.gitignore` で除外されており、リポジトリには
コミットされません。** 会社PCのEdgeプロファイル（`enovia_profile/` フォルダ）も
同様です。

**Playwrightが使えない環境の場合**：`config.json` の `enovia_auth_mode` を
`"manual"` にし、`enovia_manual_cookie` にブラウザのF12で確認した
`Cookie` ヘッダーの値をそのまま貼り付けてください（Cookieが切れるたびに
手で貼り直す必要があります）。

## セットアップ手順

1. 依存パッケージをインストールする。

   ```
   pip install -r requirements.txt
   ```

2. `config.example.json` を `config.json` にコピーする（中身は編集不要でそのまま動きます）。

   ```
   copy config.example.json config.json
   ```

3. 起動する。`run_document_search_manager.bat` をダブルクリックするか、次を実行する。

   ```
   python document_search_manager_20260903_16.py
   ```

   初回はターミナルにDevice Code Flowの認証コード（URLとコード）が表示されるので、
   表示されたURLをブラウザで開いてサインインする。

4. `http://127.0.0.1:5020` が自動で開く。キーワードを入力して「検索」を押す。

> `run_document_search_manager.bat` は先頭で `cd /d %~dp0` を実行するため、
> ショートカットや別フォルダから起動しても正しく動作します。

## 画面の使い方

- **検索欄**にキーワードを入力し、Enter または「検索」ボタン。
- **検索対象**を `0. All` 〜 `3. Enovia` から選択（既定は `0. All`）。
- **取得件数**は「関連度上位 10 / 25 / 50 / 100 / 200 / 500 件」から選択。
  ここでいう「関連度」は **SharePoint検索が算出するレリバンス（一致度）** です。
  **画面での並べ替えは「取得した範囲の中での並べ替え」**である点にご注意ください
  （例：関連度上位10件を取得して最終更新日で降順にしても、
  「全社で最も新しい文書」ではなく「関連度上位10件の中で最も新しい文書」になります）。
  網羅的に見たい場合は件数を増やしてください。
  初期選択値は `config.json` の `default_max_results` で決まります
  （`config.example.json` の既定は開発段階向けに **10件**。運用時は100等に変更してください）。
  無制限取得は行いません（体感速度を優先しているため）。
- **タイトルをクリック**するとファイルが直接開きます。
- **「サイト」列**をクリックすると、その文書が保管されているサイトが開きます。
- **「フォルダ」列**をクリックすると、その文書が保管されているフォルダが開きます。
  - 表示は `/40. Bench Validation/01. Validation_Plan` のような階層パスです。
  - 先頭の `/` は **`Shared Documents` などの既定ライブラリのルート**を表します
    （どのサイトにもある名前で冗長なため短縮しています）。`PO` のような固有の
    ライブラリ名はそのまま表示されます。
  - **マウスを載せるとフルパス**が表示されます。Excel / CSV にもフルパスを出力します。
- **列見出しをクリック**すると並べ替えできます。クリックのたびに
  昇順（▲）→ 降順（▼）→ 解除、と切り替わります。
- **列見出し右の「⋮」**で、その列の絞り込みができます。
  - **最終更新日**は「この日以降」「この日以前」の日付範囲で指定します（片方だけでも可）。
  - **それ以外の列**はチェックボックスで複数選択します
    （例: 種別で `pptx` と `xlsm` の両方を選ぶ）。候補には件数が表示され、
    候補が多い場合は入力欄で絞り込めます。
  - 絞り込みが効いている列は「⋮」がアクセント色になります。
  - 「フィルタ・ソート解除」ボタンで一括解除できます。
- **タイトル列の右のチェックボックス**で複数のファイルを選び、
  「選択ファイルをZIPで取得」でまとめてダウンロードできます。
  見出しのチェックボックスで表示中の行を一括選択できます。
- **疎通診断**ボタンで、各系統が利用可能かを確認できます。
  キーワード不要・1件分の最小リクエストで、接続可否と動作モードだけを確認します
  （結果テーブルは更新されず、実行ログにのみ表示されます）。
- **Enoviaにログイン**ボタンで、Enovia検索に必要なログイン情報を取得します
  （前述「Enoviaへのログイン」参照）。
- **Enovia検索診断**ボタンで、Enoviaのタイトル限定検索に使えそうな構文
  （全文検索 / `title:` / `ds6w:label:`）の件数を比較できます。
  Enoviaのタイトル限定構文は実機で未確定のため、確認できるまでは
  「タイトルだけを検索する」がオンでもEnoviaは常に全文検索を行います。
- **Enoviaタブ**では、Document Number / Title / Revision / State / Description /
  作成者 / Doc Owner / 最終更新者 / 最終更新日 / 作成日 / フォルダ / 種別 /
  Enoviaで開く、の列構成になります。**同じDocument Numberでもリビジョン違いは
  別行のまま表示します**（Enovia画面と一致させるため）。`0. All` タブでは、
  タイトルに `(Rev.N)` を添えて見分けられるようにしています。
  **Enoviaは一括ZIPダウンロードの対象外です**（文書の状態によってはダウンロードURLが
  拒否されるため）。「Enoviaで開く」からEnovia画面上で操作してください。
- **Excel出力 / CSV出力**で結果を `exports/` フォルダに保存します。
  **画面で絞り込み・並べ替えた状態がそのまま出力されます。**
  - **Excel**：タイトル・サイト・フォルダの各セルが**ハイパーリンク**になっており、
    クリックでそれぞれファイル・サイト・フォルダが開きます。オートフィルタ付き。
  - **CSV**：ハイパーリンクを持てない形式のため、
    「ファイルリンク」「サイトリンク」「フォルダリンク」をURLの列として出力します。

### フォルダの扱い

検索結果には、ファイルだけでなく**フォルダ自体**もヒットします。これらは除外せず、
**種別列に「フォルダ」と表示して区別**しています。

- **理由**：フォルダ名にキーワードが含まれていても、その中のファイルには含まれない、
  というケースがあります。この場合、**フォルダの存在そのものが有用な情報**になります。
- ファイルだけを見たいときは、**種別フィルタで「フォルダ」のチェックを外して**ください。
  逆に「フォルダ」だけを選べば、一致したフォルダの一覧になります。
- フォルダ行のタイトルをクリックすると、そのフォルダが開きます。
- フォルダは一括ダウンロードの対象外です（チェックボックスが無効になります）。
- 常に除外したい場合は、`config.json` の `exclude_folders` を `true` にしてください。

### 系統別ステータスの見方

| 表示 | 意味 |
|---|---|
| 🟢 | 検索成功（1件以上ヒット） |
| 🟡 | 検索は成功したが0件 |
| 🔴 | エラー（メッセージに理由を表示）。Enoviaが未ログインのときもここに出ます |
| ⚪ | 未実装 |

1つの系統がエラーになっても、他の系統の結果は必ず表示されます（部分成功方式）。

## トラブルシューティング

### 疎通診断で「権限不足」と出る

Graphの `/search/query` が `Sites.Read.All` では拒否された場合です。
**権限を追加申請する必要はありません。** `config.json` の `fallback_site_urls` に
検索したいサイトのURLを列挙すると、サイト単位検索モードに切り替わります。

```json
"fallback_site_urls": [
  "https://nexperia.sharepoint.com/sites/JapanDesign",
  "https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd"
]
```

### 検索結果の「開く」リンクが開けない

社内ブラウザが `.mcas.ms`（Microsoft Defender for Cloud Apps）経由でないと
アクセスできない場合があります。`config.json` の以下を `true` にしてください。

```json
"rewrite_host_to_mcas": true
```

### `tenant_id / client_id が特定できませんでした` と出る

既存ツール（`po_database_organizer` / `onenote_report_generator`）の `config.json` が
どちらも存在しない環境です。コンソールに探索したパスがすべて表示されるので、
次のどちらかで対処してください。**新規のEntra ID権限申請は不要です。**

**(1) 直接記入する（推奨）** — 既存ツールと同じEntra IDアプリ登録の値を書く。

```json
"tenant_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
"client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

**(2) 既存の設定ファイルの場所を教える** — 別フォルダにある場合。
バックスラッシュは2つ重ねてください。

```json
"credentials_from": "C:\\\\Users\\\\nx023836\\\\Documents\\\\PythonScripts\\\\my-claude-code\\\\po_database_organizer\\\\config.json"
```

### Enoviaの検索がエラーになる（ログイン情報がありません 等）

「Enoviaにログイン」を実行していないか、Cookieの有効期限が切れています。
画面の「Enoviaにログイン」ボタンを押し、Edgeでログイン後にウィンドウを
閉じてください。会社PCの制限で `channel="msedge"` が使えない場合は、
`config.json` の `enovia_auth_mode` を `"manual"` にしてCookieを直接
貼り付ける方式に切り替えてください（前述「Enoviaへのログイン」参照）。

### Enoviaの件数がEnovia画面と合わない

`federated/search` の `nhits` は、絞り込み前の全種別（Document以外を含む）の
合計です。画面の行は `Document` 型だけに絞っているため、`nhits` より
少なくなるのは仕様です（画面・出力にも注記が出ます）。それでも大きく
食い違う場合は、`enovia_types`（対象タイプ一覧）がEnovia画面の検索範囲と
一致しているかをご確認ください。

## 設定項目（`config.json`）

| キー | 既定値 | 説明 |
|---|---|---|
| `tenant_id` / `client_id` | 空 | 空なら既存ツールの `config.json` から借用（po → onenote の順） |
| `credentials_from` | 空 | 流用元の `config.json` をフルパスで明示指定（最優先で参照） |
| `graph_scopes` | `["...Sites.Read.All"]` | 要求スコープ。**変更すると新規権限申請が必要になるため、原則変更しない** |
| `flask_port` | `5020` | 画面のポート（既存ツールの5000/5010と衝突しない値） |
| `default_max_results` | `10` | APIで件数指定が無い場合のサーバー側の既定値。画面の初期値は常に「上位10件」（前回の作業状態があればそれを優先） |
| `exclude_folders` | `false` | 検索結果からフォルダ自体を除外するか。既定は除外せず種別列で区別する |
| `restore_last_search` | `true` | 再起動時に前回の検索状態を復元するか |
| `max_download_files` | `50` | 一括ダウンロードの1回あたりの上限件数 |
| `download_timeout_sec` | `120` | 1ファイルあたりのダウンロード待ち時間（秒） |
| `search_fields` | 7項目 | Graph Searchに要求する検索マネージドプロパティ。無効な名前があれば自動でfields無しに切り替わる |
| `hard_max_results` | `500` | 取得件数の上限 |
| `provider_timeout_sec` | `180` | 1系統あたりのタイムアウト秒数。超えた系統は 🔴 になるが、他系統の結果は失われない |
| `nexus_site_url` / `nexus_folder_path` | Nexus用 | この2つを組み合わせたURLを、Graph Search の KQL `path:` に渡して検索範囲をNexusに限定する |
| `nexus_list_id` | Nexus用 | 実機調査で判明したShareflexのリストID。現在は記録用（Graph経由の検索では未使用） |
| `nexus_extra_fields` | `[]` | Nexus検索のときだけ追加要求する検索マネージドプロパティ（Shareflex固有の列）。**テナントに存在しない名前を書くと検索がHTTP 400になる**ため、実機で確認できたものだけを足す |
| `title_only_default` / `title_field` | `true` / `title` | 「タイトルだけを検索する」の初期状態と、絞り込みに使う検索プロパティ名 |
| `nexus_resolve_people` | `true` | 人物列の数値ID（`<列名>LookupId`）を氏名に解決するか |
| `expiry_warn_days` | `60` | 有効期限のあと何日以内を「まもなく」と表示するか。0で期限切れのみ |
| `nexus_view_url` | Nexus画面URL | 「Nexusで開く」リンクの土台。`&@qmDocumentNo=<文書番号>` を付けて1件に絞り込んだ状態で開く |
| `nexus_deeplink_field` / `nexus_deeplink_title_field` | `qmDocumentNo` / `qmDocumentTitle` | 上記リンクで使う列フィルタの内部列名 |
| `nexus_scope_mode` | `path` | Nexus検索の絞り込み方式（`path` / `site` / `none`）。画面の「Nexus検索診断」で実測して決める |
| `nexus_enrich_metadata` | `true` | Nexusの標準Indexをリスト項目から取得するか |
| `nexus_enrich_max` / `nexus_enrich_workers` | `200` / `6` | Index取得の上限件数と並列数（1件につき1リクエスト増える） |
| `nexus_field_map` | `{}` | 列名の自動判別が外れた場合の明示指定。実在する列名は起動後の検索でコンソールに出る |
| `dedupe_nexus_from_sharepoint` | `true` | Nexusと同時に検索したときに、SharePoint側の重複行を除外するか。`1. SharePoint` 単独のときは（取りこぼしを防ぐため）除外しない |
| `rewrite_host_to_mcas` | `false` | リンクを `.mcas.ms` 経由に書き換えるか |
| `fallback_site_urls` | `[]` | 全社検索が使えない場合のサイト単位検索対象 |
| `enovia_base_url` | `.../3dspace` | EnoviaのベースURL。「Enoviaで開く」リンクの土台にもなる |
| `enovia_search_url` | `federated/search` のURL | Enoviaの検索APIエンドポイント |
| `enovia_auth_mode` | `playwright` | `playwright`（Edgeでログイン）または `manual`（Cookie手貼り） |
| `enovia_manual_cookie` | 空 | `enovia_auth_mode="manual"` のときに使うCookieヘッダーの値 |
| `enovia_browser_channel` | `msedge` | ログイン時に起動するブラウザ（会社PC既存のEdgeを使う） |
| `enovia_login_timeout_sec` | `300` | ログイン待ちの制限時間（秒）。超えてもその時点のCookieで保存を試みる |
| `enovia_types` | 191種類 | 検索対象とするEnoviaのタイプ一覧。将来Project Space等を増やす場合はここに追記する |
| `enovia_document_type_only` | `true` | 応答を `Document` 型だけに絞るか（`nhits` は絞り込み前の合計になる） |
| `enovia_page_size` | `100` | Enovia検索の1ページあたりの取得件数 |
| `enovia_max_raw_pages` | `20` | 型フィルタで大半が対象外になるキーワードでも、際限なく叩き続けないための上限ページ数 |

## 生成物とGit管理

以下は `.gitignore` で除外しており、リポジトリにはコミットされません。

- `config.json`（テナントID等を含む）
- `token_cache.json`（認証トークン）
- `session_state.json`（前回の検索キーワード・絞り込み条件）
- `cache/`, `exports/`, `downloads/`（検索キーワード・結果・取得したファイル本体）
- `enovia_session.json`（EnoviaのログインCookie）, `enovia_profile/`（Edgeプロファイル）

コミット対象は `config.example.json` のみです。

### バージョン管理と `old/` フォルダ

起動時に、**自分より古いバージョンのスクリプトは自動的に `old/` フォルダへ移動**します。
フォルダ直下には常に最新版だけが残ります。

- 過去のバージョンは削除されず、`old/` に保持されます（リポジトリにもコミット済み）。
- リポジトリ側の構成も同じであるため、`git pull` で旧版が復活して重複することはありません。
- 自分より新しいバージョンは移動しません（旧版を起動したときに最新版を
  退避させてしまわないため）。

## 既知の制限（現時点のスコープ外）

- **Enoviaの一括ZIPダウンロードは未対応。** 詳細画面の `WebPublish URL` は
  文書の状態（`Allow Web publish: No` 等）次第で拒否されることを実機で
  確認済みのため、設計から外した。「Enoviaで開く」からEnovia画面上で
  操作する。
- **Enoviaのタイトル限定検索の構文は未確定。** 「タイトルだけを検索する」を
  オンにしても、Enoviaは常に全文検索を行う（構文を推測で決め打ちしていない）。
  「Enovia検索診断」ボタンで候補の件数を比較できる。
- 検索結果に**本文スニペットは含めない**（一覧表示までが今回のスコープ）。
- **Nexusの標準Indexは Nexusタブでのみ表示**します（SharePointには無い列のため）。
  列名の自動判別が外れた場合は、起動後の検索でコンソールに出る実在の列名を見て
  `nexus_field_map` に設定してください。
- **Index 7列の対応づけは実機で確定済み**です（Nexus画面と突き合わせて一致を確認）。
  `qmDocumentNo` / `nxOldDocumentNo` / `qmDocumentTitle` / `qmEditor`(Doc Author) /
  `qmConfirmer`(Doc Owner) / `nxApplicable` / `nxFunctionalOrg`。
  **各セルにマウスを載せると「どの内部列から採った値か」が表示されます。**
  **「Nexus列診断」ボタン**を押すと、先頭1件についてNexusが持っている
  全ての列と値、および対応づけが実行ログに出ます。
- **「Nexusで開く」は、その1件だけに絞り込んだ状態でNexusを開きます。**
  Document Number の列フィルタ（`@qmDocumentNo=`）を使っています。
  全文検索ではありません（全文検索だと、他の文書の本文に参照文献として
  書かれた番号にも当たり、1件に絞り込めないため）。
- **キーワードを引用符で囲むと完全一致のフレーズ検索**になり、件数が大きく減ります
  （実測: `validation plan` で117件 → `"validation plan"` で14件）。
  Nexus画面の Full text search は既定でAND検索なので、比較するときは引用符を外してください。
- 検索結果のランキングはGraphの返却順に従う。SharePoint画面の並び順とは
  一致しない場合がある。

## 開発者向け

- **`DESIGN_NOTES.md`** … 調査で判明した事実・設計判断の理由・既知の罠。
  このツールを次に改修するときは**まずここを読む**。
- **`tests/`** … 検証ハーネス（ネットワーク不要）。

  ```
  python tests/run_tests.py     # 663項目の自動検証
  python tests/ui_check.py      # ブラウザ操作テスト（Playwright必要・任意）
  ```

  テストは**最新バージョンの本体を自動検出**するため、
  バージョンを上げてもテスト側の修正は不要です。
- **`.claude/skills/document-search-tool-dev/`**（リポジトリ直下）…
  Claude Code でこのツールを改修するときの開発手順を定義したスキル。

## 開発計画（全体像）

| Phase | 内容 | 状態 |
|---|---|---|
| Phase 1 | SharePoint全社検索 MVP | ✅ 完了（v20260903_08、実機動作確認済み） |
| Phase 2 | Nexus検索追加（Graph Searchを `nexus_folder_path` に限定）＋重複排除の有効化 | ✅ 完了（件数はNexus画面と一致することを実測で確認） |
| Phase 2.5 | 系統別タブ＋Nexus標準Index＋タイトル限定検索＋Nexusリンク | ✅ 完了（v20260903_15、実機で対応づけの一致まで確認済み） |
| Phase 3 | Enovia検索追加（`federated/search` を実測して実装） | ✅ 実装完了（v20260904_01）。**実機での確認は未実施**（ログイン・件数突き合わせ等） |
| Phase 4 | 3系統統合の磨き込み（名寄せ・検索履歴・お気に入り） | 未着手 |
