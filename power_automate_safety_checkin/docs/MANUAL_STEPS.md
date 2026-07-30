# 手作業チェックリスト(削減できない最小限)

このPoCは「GUIでの手作業を極限まで削減する」ことを主眼にしている。
以下は、Microsoft側の設計・セキュリティモデル上、**自動化できない**手作業である。
これ以外の作業(SharePointの列作成、メンバー投入、式の入力、カードのJSON)は、
`scripts/`のスクリプトまたはコピペで代替する。

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

- [ ] `pac` CLIをインストール(`dotnet tool install --global Microsoft.PowerApps.CLI.Tool`)
- [ ] DEV環境へサインイン: `pac auth create --url <DEV環境URL>`(対話的ブラウザログイン)
- [ ] `PnP.PowerShell`モジュールをインストール: `Install-Module PnP.PowerShell -Scope CurrentUser`

### 2. SharePoint(スクリプトで自動化済み・手動確認のみ)

- [ ] `scripts/provision_sharepoint.ps1`を実行(初回サインインのみ対話的、以降は自動)
- [ ] 実行結果として表示される列内部名を`evidence/sharepoint_internal_names.json`へ保存(Gate D)

### 3. コネクタ接続の初回承認(各コネクタにつき1回のみ)

Power Automate画面で、新規フロー作成時に以下のコネクタへの接続を作成する。
これは「サインインボタンを押す」だけの1クリック作業だが、自動化不可。

- [ ] SharePoint接続の作成・認証
- [ ] Microsoft Teams接続の作成・認証

### 4. フロー本体の初回構築(DEV環境で1回のみ)

`docs/FLOW_LOGIC_SPEC.md`の通りに、以下5フローを構築する。
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

- [ ] `scripts/deploy_solution.ps1 -Action export-unpack ...`でDEVの変更をGit管理下へ
- [ ] `scripts/deploy_solution.ps1 -Action pack-import ...`でTEST/PRODへ展開
- [ ] TEST/PROD環境でのみ、接続参照(Connection Reference)の初回マッピングをGUIで承認
      (import後、フロー一覧から「接続の再認証」を1回クリックするのみ)

---

## 手作業の総量(見積り)

| 作業 | 回数 | 所要時間の目安 |
| --- | --- | --- |
| pac CLI / PnP.PowerShellインストール | 1回 | 10分 |
| SharePoint 5リスト・全列作成 | 0回(スクリプト) | — |
| メンバー18名+上司3名投入 | 0回(スクリプト) | — |
| フロー3本の初回構築(コピペ) | 1回(DEV環境のみ) | 60〜90分 |
| コネクタ接続承認 | 2回(SharePoint/Teams、DEV) | 5分 |
| Gate B証拠取得 | 1回 | 15分 |
| TEST/PROD展開 | 環境数分(CLI一発) | 各5分 |

以前のPower Automate開発で問題だった「画面で考えながら1つずつ組む」という
反復作業(通常、フロー1本あたり数時間かかりうる)を、初回構築の1回・約60〜90分に
圧縮し、それ以降の複製・環境展開・修正反映はコードとCLIで行う。
