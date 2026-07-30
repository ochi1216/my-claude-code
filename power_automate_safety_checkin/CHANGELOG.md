# CHANGELOG — power_automate_safety_checkin

このフォルダ内の変更履歴。

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
