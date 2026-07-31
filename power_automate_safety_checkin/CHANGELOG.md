# CHANGELOG — power_automate_safety_checkin

このフォルダ内の変更履歴。

## [20260731_04] - 2026-07-31

- ユーザーがSharePointサイト(MyPrivate)へ4リスト
  (`EQ_Config_Members`, `EQ_Received_Items`, `EQ_Events`, `EQ_Responses`)を
  Excelアップロードで登録完了したことを確認。これによりP1完成条件のうち
  SharePoint側の準備が整い、3フロー(`EQ06_Manual_Drill_DEV`等)のGUI構築へ
  進めるようになった。Gate D(列内部名の実測)は、フィルタークエリで内部名を
  使う箇所(`GET_Active_Members`等)に到達した時点で都度確認する方針とする。

## [20260731_03] - 2026-07-31

**追加ファイル:** `EQ_Config_Members.xlsx`, `EQ_Received_Items.xlsx`,
`EQ_Events.xlsx`, `EQ_Responses.xlsx`(SharePointアップロード用テンプレート)

**変更ファイル:** `docs/FLOW_LOGIC_SPEC.md`

- SharePointの「Excelから新しいリストを作る」機能がテーブル形式でないと
  エラーになることが実機検証で判明したため、4リスト分のExcelテンプレートを
  Excelテーブル(ヘッダー+実例行1件)として作成し、ユーザーへ送付した。
- `EQ_Responses.xlsx`初版に、`FLOW_LOGIC_SPEC.md`の`SP_Get_Existing_Response`
  (Title列でのフィルター)と実際の書き込み列一覧との不整合を発見。
  `Title`列(`ResponseKey`格納用)がExcel側に無く、`FLOW_LOGIC_SPEC.md`の
  「書き込む列」一覧にも明記されていなかった(書き忘れると重複回答防止が
  機能しない)。`Title`列を追加し、`FLOW_LOGIC_SPEC.md`のGate 6箇所も修正。
- `EQ_Responses.xlsx`に、各列の想定型・説明をヘッダーセルのコメントとして付与し、
  実例行(斜体グレー、アップロード後に削除する旨を明記)とREADMEシートを追加。

## [20260731_02] - 2026-07-31

**追加ファイル:** `evidence/README.md`

**変更ファイル:** `docs/GATE_STATUS.md`

- S02(Power AutomateフローのGUI構築とGate B/D検証)を開始。
  Gate B(Teamsカードアクション実測)・Gate D(SharePoint列内部名実測)の
  結果を格納する`evidence/`ディレクトリを新規作成し、置くべきファイルの
  一覧・サニタイズ方法(個人メール・Tenant ID・Team ID・Channel IDを
  マスクする方法)を`evidence/README.md`に明文化した。
- `GATE_STATUS.md`のGate D行を、SharePointリスト作成手段をExcelアップロード
  方式へ切替えた実態(S01末の変更)に合わせて修正。
  `scripts/provision_sharepoint_*.ps1`による自動出力は前提にできないため、
  「リストの設定」画面からの手動確認・`evidence/sharepoint_internal_names.json`
  への記録に変更した。
- ユーザーへ確認した結果、SharePoint 4リストへのExcelアップロードは
  **まだ未着手**と判明。このため本セッションでは、3フロー
  (`EQ06_Manual_Drill_DEV` / `EQ04b_On_Response_DEV` / `EQ05_Status_Summary_DEV`)
  のGUI構築・Gate B/D実測には進めなかった(SharePointの準備が前提のため)。
  ユーザーが`docs/MANUAL_STEPS.md`§2に沿ってアップロードを完了させた後、
  フローGUI構築の式・手順提示とトラブル対応を再開する。

## [20260731_01] - 2026-07-31

**追加ファイル:** `scripts/provision_sharepoint_20260730_03.ps1`(`_01`/`_02`は規約により残置)

**変更ファイル:** `config/members.example.json`, `docs/FLOW_LOGIC_SPEC.md`,
`docs/MANUAL_STEPS.md`, `README.md`

- `EQ_Config_Sites`をSharePointリストから廃止。監視対象拠点(大分・大阪・東京)と
  震度閾値は運用中も変わらない固定値であり、かつ`TeamId`/`ChannelId`をサイト
  閲覧者全員に見えるリストへ置く必要もないという指摘を受け、
  `EQ06_Manual_Drill_DEV`内のSwitchアクション(`CMP_Site_Config`)に
  固定値として持たせる設計に変更した。`docs/FLOW_LOGIC_SPEC.md`のアクション
  順序・式を全面的に更新。
- `provision_sharepoint_*.ps1`から`EQ_Config_Sites`関連のリスト作成・データ投入
  処理を削除(SharePointリストは4個に)。
- `EQ_Config_Members`のマネージャー3件のIDを`boss01`/`boss02`/`boss03`から
  `mgr01`/`mgr02`/`admin01`に変更。
- 実機検証で、PnP.PowerShellによるSharePoint自動化にはEntra IDアプリ登録
  (IT部門の承認)が必要と判明したため、`docs/MANUAL_STEPS.md`の推奨手順を
  「Excelアップロードによる一度限りの手動作成」に変更(スクリプトは代替手段として残置)。

## [20260730_01] - 2026-07-30

**追加ファイル:** `README.md`, `config/sites.json`, `config/members.example.json`,
`cards/channel_alert_card.json`, `cards/checkin_card.json`,
`scripts/provision_sharepoint.ps1`, `scripts/deploy_solution.ps1`,
`solution/README.md`, `docs/FLOW_LOGIC_SPEC.md`, `docs/MANUAL_STEPS.md`,
`docs/GATE_STATUS.md`

- Power Automate(標準コネクタのみ)による地震安否確認システムのPoC初版を開始。
  Python + Microsoft Graph API版がAzure ADアプリ登録・管理者同意の壁に当たったこと、
  および先行して提示されたPower Automate構想の精査結果(`docs/REVIEW_earthquake_safety_system_0730_02.md`)
  を踏まえ、手動トリガー版(P1)から着手する。
- SharePoint 5リスト・全列・拠点3件・メンバー21名(スタッフ18名+上司3名)を
  PnP PowerShellで自動プロビジョニングするスクリプトを作成(GUIでの手作業を排除)。
- 非同期アーキテクチャ(カード投げ切り+応答トリガー分離)によるフローロジック仕様を、
  Power Automate画面へそのまま貼り付けられる形で文書化。
- pac CLIによるSolutionのexport/unpack/pack/importスクリプトを作成し、
  DEV→TEST→PRODの環境展開時にフローを再構築する手間を排除。
- 自動化できない最小限の手作業(接続認証、フロー本体の初回構築、Gate B証拠取得)を
  `docs/MANUAL_STEPS.md`に明記。
- PowerShellスクリプトはASTパーサーで構文検証済み(実テナントでの実行は未検証)。

## [20260730_02] - 2026-07-30

**変更ファイル(リネーム):** `scripts/provision_sharepoint.ps1` →
`scripts/provision_sharepoint_20260730_01.ps1`、
`scripts/deploy_solution.ps1` → `scripts/deploy_solution_20260730_01.ps1`

**追加ファイル:** `run_power_automate_tools.bat`

- リポジトリの命名規約(`ツール名_yyyymmdd_連番.拡張子`)が`.py`だけでなく
  実行コード全般に適用されるべきという指摘を受け、`.ps1`スクリプトに
  リビジョン番号を付与した(初回作成のため、旧ファイル名は残さずリネーム)。
- ファイル名から最新リビジョンを自動検出して起動するランチャー
  `run_power_automate_tools.bat` を追加。SharePointプロビジョニング、
  DEVからのSolutionエクスポート、TEST/PRODへのpack-importをメニューから選べる。
- `emergency_alert_tool/run_emergency_alert_tool.bat` で過去に発生した
  文字化け起動不能事案(UTF-8のバッチファイルがShift-JISコンソールで誤解釈された)
  を踏まえ、表示メッセージを全て英数字(ASCII)に統一し、CRLF改行で保存した。
  この方針をリポジトリ直下の`CLAUDE.md`にも明文化した。

## [20260730_03] - 2026-07-30

**変更ファイル:** `run_power_automate_tools.bat`, `docs/MANUAL_STEPS.md`

- 実機検証の結果、`PnP.PowerShell` 3.x系はWindows標準の「Windows PowerShell 5.1」
  では動作せず、PowerShell 7.4以降(`pwsh`)が必須であることが判明。
  `run_power_automate_tools.bat`が`powershell`(5.1)ではなく`pwsh`を呼び出すよう修正。
  `pwsh`が見つからない場合はエラーメッセージで導線(https://aka.ms/PSWindows)を示す。
- 実機で遭遇した2つのトラブルと対処法を`docs/MANUAL_STEPS.md`に追記:
  - 非管理者アカウントでの`Install-PackageProvider`失敗(`-Scope CurrentUser`で解決)
  - 古い`PowerShellGet`(`1.0.0.1`)による`Install-Module`の`Telemetry`型エラー
    (`PowerShellGet`自体の更新+PowerShellウィンドウの再起動で解決)

## [20260730_04] - 2026-07-30

**追加ファイル:** `scripts/provision_sharepoint_20260730_02.ps1`(`_01`は規約により残置)

- 実機検証で、PnP.PowerShellがインストール済み・`Import-Module`単体では動作するにも
  関わらず、スクリプト実行時には`Connect-PnPOnline`が「認識されないコマンド」として
  失敗する事象を確認(モジュールの自動読み込みが環境によって効かない)。
  スクリプト冒頭で明示的に`Import-Module PnP.PowerShell`を行うよう修正。
