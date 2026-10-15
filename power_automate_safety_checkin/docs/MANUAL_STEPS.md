# 手作業チェックリスト(削減できない最小限)

このPoCは「GUIでの手作業を極限まで削減する」ことを主眼にしている。
以下は、Microsoft側の設計・セキュリティモデル上、**自動化できない**手作業である。
式の入力・カードのJSONはコピペで代替する。SharePointのリスト・列作成は、
当初PowerShellでの完全自動化を目指したが、Entra IDアプリ登録がIT部門の
承認を要することが判明したため、**Excelアップロードによる一度限りの手動作成**を
基本とする(理由は下記「なぜ自動化できないのか」参照)。

## なぜ自動化できないのか

- **接続認証(OAuth)**: SharePoint・Teamsへの接続は、個人またはサービスプリンシパルの
  資格情報をアプリに預ける行為である。パスワードやトークンをスクリプト・リポジトリに
  保存する設計は、CLAUDE.mdの「認証情報をコミットしない」という原則に反するため、
  意図的に自動化しない。
- **フロー本体の初回構築**: Power AutomateのCloud Flowは、GUIでの構築(または
  一度エクスポートされた実体)なしに、JSONだけからゼロで生成することができない
  （`pac solution init`はSolutionの空の入れ物を作るだけで、フローの中身は作らない）。

## チェックリスト

### 1. 環境準備(最初の1回のみ)

- [ ] **PowerShell 7以降(`pwsh`)をインストール** (https://aka.ms/PSWindows)。
      `PnP.PowerShell` 3.x系はWindows標準の「Windows PowerShell 5.1」では動作せず、
      PowerShell 7.4以降が必須(未導入だと`Import-Module`が
      `Modules_InsufficientPowerShellVersion`エラーで失敗する)。
      インストール後は、スタートメニューの「PowerShell 7」(pwsh)を使うこと。
      `run_power_automate_tools.bat`は`pwsh`を自動的に呼び出す。
- [ ] `pac` CLIをインストール(`dotnet tool install --global Microsoft.PowerApps.CLI.Tool`、
      または https://aka.ms/PowerAppsCLI のインストーラー)
- [ ] DEV環境へサインイン: `pac auth create --url <DEV環境URL>`(対話的ブラウザログイン)
- [ ] `pwsh`(PowerShell 7)を起動し、`PnP.PowerShell`モジュールをインストール:
      `Install-Module PnP.PowerShell -Scope CurrentUser -Force`
      - 会社のPCで`Install-PackageProvider`等が「管理者権限が必要」と出る場合は、
        `-Scope CurrentUser`を付けて実行すること(このリポジトリの手順はすべて
        管理者権限なしで完結する設計)。
      - 非常に古い`PowerShellGet`(バージョン`1.0.0.1`、Windows標準の初期版)が
        入っていると、`Install-Module`実行時に`型 ... Telemetry が見つかりません`
        というエラーで失敗することがある。その場合は
        `Install-Module -Name PowerShellGet -Force -AllowClobber -Scope CurrentUser`
        で更新し、**PowerShellウィンドウを閉じて開き直してから**再試行すること。

### 2. SharePoint(4リスト。Excelアップロードによる手動作成を推奨)

実機検証の結果、`scripts/provision_sharepoint_*.ps1`によるPnP.PowerShell自動化には、
Entra IDアプリ登録(委任アクセス)が必要で、これは通常のユーザー権限では
自己登録できず、IT部門への依頼が必要になることが判明した。

4リスト・列を作るだけの一度限りの作業であれば、**SharePointの「Excelから新しいリストを作る」
機能を使った手動アップロードの方が、IT部門への依頼なしで完結し早い**。以下のいずれかで進める。

- [ ] **(推奨)** SharePointサイトで「サイトコンテンツ」→「新規」→「リスト」→「Excelから」を選び、
      4つのリスト用Excelファイル(`EQ_Config_Members`, `EQ_Received_Items`, `EQ_Events`, `EQ_Responses`)を
      それぞれアップロードする(`EQ_Config_Sites`は作らない。下記「拠点情報について」参照)
- [ ] (代替、IT部門の協力が得られる場合のみ) `scripts/provision_sharepoint_*.ps1（最新版）`を実行

- [ ] 作成後、列の内部名を`evidence/sharepoint_internal_names.json`へ保存(Gate D)
      (SharePointの「リストの設定」→各列をクリック→URLの`Field=`部分で確認できる)

#### 拠点情報(大分・大阪・東京)について

`EQ_Config_Sites`はSharePointリストとして作らない。監視対象拠点と震度閾値(5弱)は
運用中も変わらない固定値であり、かつ`TeamId`/`ChannelId`をサイト閲覧者全員に
見える形で置く必要もないため、`docs/FLOW_LOGIC_SPEC.md`の`CMP_Site_Config`
(Power Automateのフロー内のSwitchアクション)に直接値を書き込む方式に変更した。

### 3. コネクタ接続の初回承認(各コネクタにつき1回のみ)

Power Automate画面で、新規フロー作成時に以下のコネクタへの接続を作成する。
これは「サインインボタンを押す」だけの1クリック作業だが、自動化不可。

- [ ] SharePoint接続の作成・認証
- [ ] Microsoft Teams接続の作成・認証

### 4. フロー本体の初回構築(DEV環境で1回のみ)

`docs/FLOW_LOGIC_SPEC.md`の通りに、以下3フローを構築する。
記載の式・カードJSONはすべてコピペで完結する(考える作業は発生しない)。

- [ ] `EQ06_Manual_Drill_DEV`
- [ ] `EQ04b_On_Response_DEV`
- [ ] `EQ05_Status_Summary_DEV`

構築後、1つのSolution(例: `EQSafetyCheckin`)にまとめる。

### 5. Gate B証拠取得(1回のみ、必須)

- [ ] `EQ06_Manual_Drill_DEV`を1回実行し、実行履歴を確認
- [ ] Teamsアクション名が非推奨(Deprecated)表記でないことを確認
- [ ] 個人カードへの応答を1件テストし、`TRG_On_Adaptive_Card_Response`の
      実際の出力JSON(サニタイズ後)を`evidence/teams_wait_output_sanitized.json`へ保存
- [ ] `docs/FLOW_LOGIC_SPEC.md`の「Gate B確認後に更新すべき箇所」を実測値で更新

### 6. 以降の変更・環境展開(すべて自動化)

- [ ] `scripts/deploy_solution_*.ps1（最新版） -Action export-unpack ...`でDEVの変更をGit管理下へ
- [ ] `scripts/deploy_solution_*.ps1（最新版） -Action pack-import ...`でTEST/PRODへ展開
- [ ] TEST/PROD環境でのみ、接続参照(Connection Reference)の初回マッピングをGUIで承認
      (import後、フロー一覧から「接続の再認証」を1回クリックするのみ)

---

## 手作業の総量(見積り)

| 作業 | 回数 | 所要時間の目安 |
| --- | --- | --- |
| pac CLI / PnP.PowerShellインストール | 1回 | 10分 |
| SharePoint 4リスト・全列作成 | 1回(Excelアップロード) | 15〜20分 |
| メンバー18名+マネージャー2名+管理者1名投入 | 0回(Excelに含めてアップロード) | — |
| フロー3本の初回構築(コピペ) | 1回(DEV環境のみ) | 60〜90分 |
| コネクタ接続承認 | 2回(SharePoint/Teams、DEV) | 5分 |
| Gate B証拠取得 | 1回 | 15分 |
| TEST/PROD展開 | 環境数分(CLI一発) | 各5分 |

以前のPower Automate開発で問題だった「画面で考えながら1つずつ組む」という
反復作業(通常、フロー1本あたり数時間かかりうる)を、初回構築の1回・約60〜90分に
圧縮し、それ以降の複製・環境展開・修正反映はコードとCLIで行う。
