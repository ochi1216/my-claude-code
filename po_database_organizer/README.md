# PO Database Organizer

SharePoint上でプロジェクトごと・業者ごとにフォルダ管理されているPO（パーチャスオーダー）
関連書類をスキャンし、「Project × Vendor × PO番号」を軸にしたカタログをExcel/JSONで
生成するツール。R19 Site Organizer（Graph API + MSAL Device Code Flow によるSharePoint
フォルダ走査）の技術基盤を、PO管理用途に転用したもの。

## スコープ（Phase 1）

現時点ではPO番号以外の命名規則（見積・検収・請求などの文書種別の判別ルール）が
確立していないため、**無理な自動分類はしない**方針とした。

- ファイル名が `PO` で始まるファイルのみを確実にPO本体として認識し、PO番号を抽出する
  （正規表現は `config.json` の `po_number_pattern` で調整可能。デフォルト `^PO[-_]?(\d{3,})`）
- それ以外のファイル（メール履歴・エビデンス等）はPO番号に紐付けず、Project/Vendor単位
  までの情報を保持したまま「未分類書類」として一覧化する（＝見えていなかった漏れの可視化）
- 発注/検収/請求/支払などの**ステータス判定はここでは行わない**。「PO一覧」シートに空の
  Status列を用意するだけに留め、他の管理Excelと `PO番号` キーで結合して後付けできるように
  しておく。ステータス遷移ルールは、実際に他のExcelと突き合わせてから固める想定（Phase 2）

## 必要要件

- Python 3.9以上
- 対象SharePointサイトへの `Sites.Read.All` 権限（Entra IDアプリ登録・Admin Consent済み）

## セットアップ手順

1. 依存パッケージをインストールする。

   ```
   pip install -r requirements.txt
   ```

2. `config.example.json` を `config.json` にコピーし、環境に合わせて編集する。

   ```json
   {
     "tenant_id": "<YOUR_TENANT_ID>",
     "client_id": "<YOUR_CLIENT_ID>",
     "site_host": "nexperia.sharepoint.com",
     "site_path": "/sites/JapanDesign",
     "library_name": "PO",
     "po_number_pattern": "^PO[-_]?(\\d{3,})"
   }
   ```

   - `tenant_id` / `client_id` は、既存のR19 Site Organizerで使用しているEntra IDアプリ
     登録の値をそのまま流用できる（同一テナント・同一パーミッション体系のため）。
   - `site_host` / `site_path` は対象サイトのURLから決定する。ブラウザ上のURLが
     `https://nexperia.sharepoint.com.mcas.ms/sites/JapanDesign/PO/Forms/view.aspx` の
     ように `.mcas.ms`（Microsoft Defender for Cloud Apps経由のプロキシ）を含む場合でも、
     Graph APIは常に `graph.microsoft.com` を直接叩くため、`site_host` には `.mcas.ms` を
     含めず実体のホスト名（`nexperia.sharepoint.com`）を指定する。
   - `library_name` は対象のドキュメントライブラリ名（URLの `/PO/` 部分に対応する想定）。
     一致するライブラリが無い場合は起動時ログに候補一覧が表示されるので、それを見て
     修正する。

3. スクリプトを実行する。

   Windowsの場合は `run_po_database_organizer.bat` をダブルクリックする。同じフォルダ内の
   `po_database_organizer_*.py` のうち最新版（ファイル名の日付_連番が一番大きいもの）を
   自動選択して起動する。バージョンアップ時は新しい `po_database_organizer_YYYYMMDD_NN.py`
   をこのフォルダに追加するだけでよく、バッチファイル自体の修正は不要。
   `config.json` が無い場合や `python` が見つからない場合はエラーメッセージを表示して
   終了する。初回は依存ライブラリ（`msal`）の有無を確認し、無ければ自動で
   `pip install -r requirements.txt` を実行する。

   コマンドラインから直接実行する場合は、フォルダ内にある最新版のファイル名を指定する
   （更新のたびにファイル名の連番が上がるため、実際に存在するファイル名に読み替える）。

   ```
   python po_database_organizer_20260713_02.py
   ```

   初回はターミナルにDevice Code Flowの認証コード（URLとコード）が表示されるので、
   表示されたURLをブラウザで開いてサインインする。以降は `token_cache.json` に
   キャッシュされ、有効期限内は再認証不要。

4. `http://127.0.0.1:5010` が自動で開くので、「スキャン開始」を押す。

   - スキャンは `cache/scan_cache.json` にVendorフォルダ単位で結果を累積保存するため、
     途中で中断しても再実行時は前回分がスキップされる（再開可能）。強制的に全件
     取り直したい場合は「キャッシュ無視で再スキャン」を使う。

5. 完了後、「Excel出力」または「JSON出力」でカタログを保存する。

## 出力構成

### Excel（複数シート）

| シート | 内容 |
|---|---|
| PO一覧 | Project ID / Project / Vendor / PO関連フォルダ / PO番号 / ファイル名 / 最終更新日 / Status(空列)。1書類=1行で、同一PO番号に複数の関連ファイル（改訂版等）がある場合はその数だけ行が並ぶ |
| 未分類書類 | PO番号を特定できなかったファイル一覧（Project ID/Project/Vendor/PO関連フォルダ単位） |

`Project` / `Vendor` / `PO関連フォルダ` / ファイル名 の各セルには、対応するSharePoint上の
フォルダ・ファイルへのハイパーリンクが直接埋め込まれている（別列の「リンク」は廃止）。
「PO関連フォルダ」は Project > Vendor > **PO関連フォルダ** > 書類群 という3階層目のフォルダで、
PO本体だけでなく関連書類全体をまとめて確認したい場合の起点として使う。
「Project ID」は各行の先頭列にあり、他Excelとの結合キーとしても利用できる
（v03でマスタ用の「Projects」「Vendors」シートは廃止）。

`PO番号` 列をキーに、契約管理表・検収管理表など他の管理Excelと VLOOKUP / Power Query で
結合できる構成にしている。

### JSON

`{"projects": [...], "vendors": [...], "pos": [...], "documents": [...]}` のスター型
（正規化された4テーブル構成）。Excel出力の元データであり、将来的にSQLite等へ移行する
場合のソースとしても利用できる。

## 既知の制限（今回のスコープ外）

- PO番号を伴わない書類（メール履歴・エビデンス等）の自動分類は行っていない。分類ルールが
  定まった段階で `classify_filename()` にロジックを追加する想定。
- ステータス（発注/検収/請求/支払等）の自動判定は行っていない。他の管理Excelとの突き合わせ
  結果をもとに、Phase 2でルールを設計する。
- Vendorフォルダ配下の再帰探索は `config.json` の `max_depth`（デフォルト6階層）で
  打ち切る。極端に深いフォルダ構成では取りこぼしが発生し得る。

## 関連ツール（PO本体PDFの中身を読み取る）

PO一覧はフォルダ構造からの一次情報（Project/Vendor/PO番号/リンク等）のみで、PDFの中身
（発注金額・明細行）までは読み取っていない。これを追加するのが以下の2ツール（同じフォルダに
同梱、config.jsonも共用）。

- **`po_pdf_extractor_YYYYMMDD_NN.py`**：ローカルに保存済みのPO PDFが入ったフォルダを
  指定すると、各PDFのヘッダーPO番号・発注金額・明細行（Line/数量/単価/金額/Description）を
  読み取り、Excelサマリー（サマリー/明細の2シート）にまとめる調査用ツール。
  `python po_pdf_extractor_YYYYMMDD_NN.py <PDFフォルダ> [-o summary.xlsx]`
- **`po_pdf_merge_YYYYMMDD_NN.py`**（および `run_po_pdf_merge.bat`）：
  po_database_organizer が出力した「PO一覧」Excelを読み込み、各行のPO本体PDFを
  SharePointから直接ダウンロードして本文を解析し、`PDFヘッダーPO番号` `ヘッダー接頭辞`
  `PDF種別` `PO番号一致` `発注金額` `通貨` `明細行数` `抽出エラー` の列と
  「PO明細(PDF抽出)」シートを追加した `<入力ファイル名>_detail.xlsx` を生成する。
  ブラウザ（Chrome/Edge）は使わず、po_database_organizer と同じGraph API認証で
  ファイル本体を取得するため、SharePointのMCAS確認画面は経由しない。バッチファイル起動時、
  またはExcelファイルを引数なしで実行するとファイル選択ダイアログが開く。処理は10件ごとに
  一時停止し、次の10件へ進む/最後まで自動で進める/中断して保存する、を選べる。
  「PO一覧」の `PDFヘッダーPO番号` セルと「PO明細(PDF抽出)」の該当PO番号・Line 00010行は
  相互にハイパーリンクでジャンプできる（同一PO番号で複数行ある場合も、行ごとに正しく
  対応する明細へリンクする）。「Changed Purchase Order」（変更発注書）にも対応。
