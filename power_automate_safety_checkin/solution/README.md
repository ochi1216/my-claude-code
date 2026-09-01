# solution/ — フローをJSONで生成してCLIから流し込む

Power AutomateのGUIでフローを手組みする代わりに、フロー定義(JSON)を
スクリプトで生成し、`pac` CLIでDEV環境へインポートする。

GUI操作は「接続の作成(サインイン)」と「動作確認」だけに限定される。

## なぜこの方式にしたか

S02でGUI構築を試みたところ、以下の問題があった。

- アクション1つずつのクリック操作が膨大(EQ06だけで30ステップ超)
- 「保存」を押す前に画面を再読み込みすると、作りかけが全て消える
- 同じ作業をEQ04b・EQ05でも繰り返す必要がある

一方、クラウドフローの実体はJSON(Logic Appsのワークフロー定義言語)であり、
Dataverse Solutionとしてインポートできる。生成はスクリプト化できるため、
2回目以降の修正・再展開はコマンド1つで済む。

## 前提: 実測で確定させた仕様

Solutionにフローを入れる形式は公開ドキュメントだけでは特定できなかったため、
実テナントで作った最小フローをエクスポート・unpackして確定させた。

| 項目 | 実測結果 |
| --- | --- |
| `Other/Customizations.xml` | `<Workflows />` は**空のまま**。ここにフローを書くと`pac solution pack`が「unexpected children」として無視する |
| フロー定義 | `Workflows/<Name>-<GUID大文字>.json` |
| メタデータ | `Workflows/<Name>-<GUID大文字>.json.data.xml`(これが無いとインポートが通らない) |
| JSONへの参照パス | `<JsonFileName>/Workflows/...`(**先頭スラッシュ必須**。無いと`Part URI must start with a forward slash`エラー) |
| `Other/Solution.xml` | `<RootComponent type="29" id="{GUID小文字}" behavior="0" />` |

コネクタのoperationIdも同様に実測した(`docs/GATE_STATUS.md` Gate B/D参照)。

| 操作 | operationId | type |
| --- | --- | --- |
| SharePoint 項目の作成 | `PostItem` | `OpenApiConnection` |
| SharePoint 複数の項目の取得 | `GetItems` | `OpenApiConnection` |
| Teams カードを投稿(応答を待たない) | `PostCardToConversation` | `OpenApiConnection` |
| Teams カードを投稿して応答を待機 | `PostCardAndWaitForResponse` | `OpenApiConnectionWebhook` |

Teamsコネクタのトリガー11種類を確認した結果、**カードの回答を受け取るトリガーは
存在しない**(「チャットでメッセージに応答があったとき」は`WebhookMessageReactionTrigger`で
絵文字リアクション用)。このため回答は待機型アクションで受ける。

## セットアップ(初回のみ)

### 1. 設定ファイルを作る

```powershell
copy deploy_config.example.json deploy_config.json
```

`deploy_config.json`に実値を入れる。このファイルは`.gitignore`で除外されており、
Team ID・Channel ID・サイトURL・リストGUIDといった社内情報はコミットされない。

必要な値の取り方:

| 項目 | 取得方法 |
| --- | --- |
| `sharePointSiteUrl` | SharePointサイトのURL |
| `listIds.*` | SharePointの「リストの設定」画面URLの`List=%7B...%7D`部分、またはGUIで一度SharePointアクションを作ってエクスポートしたJSONの`table`の値 |
| `connectionReferences.*` | エクスポートしたフローJSONの`connectionReferenceLogicalName`(例: `njp_sharedsharepointonline_d85a5`) |
| `sites[].teamId` / `channelId` | Teamsアクションを一度GUIで作ってエクスポートしたJSONの`body/recipient/groupId`・`channelId` |
| `workflowIds.*` | 任意のGUID(新規作成時)。既存フローを更新する場合はそのフローのGUID |

### 2. Solutionの器をDataverseに作る(初回のみ)

```powershell
pac auth create
pac env list                       # 対象環境のIDを確認
pac solution init --publisher-name NexperiaJP --publisher-prefix njp
```

## 生成とデプロイ(以降は毎回これだけ)

```powershell
python build_flows_20260901_01.py --config deploy_config.json --out .\src --cards ..\cards
pac solution pack --zipfile .\EQSafetyCheckin.zip --folder .\src
pac solution import --environment <ENV_ID> --path .\EQSafetyCheckin.zip
```

生成されるフローは有効状態(`StateCode=1`/`StatusCode=2`)でインポートされる。
手動トリガーのフローは実行ボタンを押さない限り動かないため、有効なままで支障はない
（下書きで入れると再インポートのたびに「オンにする」を押す必要があり、手間が増える）。

## 検証中の誤送信防止

`deploy_config.json`の`testRecipientOverride`にメールアドレスを設定すると、
**個人カードの宛先は、名簿の内容にかかわらず常にそのアドレスになる。**

`IsTest`の状態や選んだ拠点には依存させていない。防ぎたいのは人為ミス
(訓練フラグの付け忘れ、拠点の選び間違い)であり、人の操作を条件にすると
そのミス自体で安全弁が外れてしまうため。**本番運用へ移るときは、この値を
空文字にする。それが唯一の切替操作**である。

背景: S02の実機テストで、名簿に載っていた実在の同僚2名へ安否確認カードが
実際に届いてしまった。

### 拠点分岐のテストについて

`sites`に架空の拠点(例: `NARA`)を追加し、`EQ_Config_Members`にその拠点の
メンバーとして検証者だけを登録しておくと、実在拠点の名簿に一切触れずに
拠点分岐・閾値判定・メンバー抽出まで一通り試せる。本番移行時に
`sites`から取り除く。

## 生成されるフロー

| フロー | 状態 |
| --- | --- |
| `EQ06_Manual_Drill_DEV` | 生成対象 |
| `EQ04b_On_Response_DEV` | **不要になった**。カード応答を受け取るトリガーがテナントに存在しないため、回答の受け取りはEQ06のループ内(`PostCardAndWaitForResponse`)へ統合する |
| `EQ05_Status_Summary_DEV` | 生成対象(実機未検証)。`workflowIds`に載っているフローだけが生成されるため、不要なら設定から外せばよい |

## 未確認事項

- 未回答(タイムアウト)時にループが正常終了するかは**再検証中**。詳細は下記。
- `EQ05_Status_Summary_DEV`は**実機未検証**。
- エラー処理(`SCOPE_Try`/`SCOPE_Catch`による`EQ_Received_Items`へのログ記録)は**未実装**。
  `EQ_Received_Items`の列内部名も未取得。
- 実在拠点(OITA/OSAKA/TOKYO)での訓練は**未実施**。現状は架空拠点`NARA`でのみ検証している。
- 3名結合テスト・18名訓練は未実施。

## タイムアウト(未回答)の扱い

実際の訓練では時間内に回答しない人が必ずいるため、それでフローが失敗しては困る。

最初は待機アクションの後続を2つに分け、片方(`SP_Create_Response`)を
`runAfter=Succeeded`、もう片方(受け皿のCompose)を`runAfter=TimedOut`にしていたが、
**タイムアウト時にループ全体が失敗した**(実測)。エラーは
`ActionFailed. An action failed. No dependent actions succeeded.`。
受け皿自体は成功していたが、もう一方がスキップのまま残るとスコープが失敗と判定される。

このため、**待機アクションの後続を`CHK_Responded`という条件1つにまとめ**、
その中で回答あり/未回答に分岐する構造へ変更した。

```
TM_Post_CheckIn_Card (待機, limit.timeout)
  └─ CHK_Responded  runAfter: [Succeeded, TimedOut]
       条件: actions('TM_Post_CheckIn_Card')?['status'] == 'Succeeded'
       ├─ はい: SP_Create_Response → CHK_Affected → 上司通知
       └─ いいえ: CMP_No_Response (記録のみ)
```

`runAfter`に`Failed`を含めていないのは意図的で、本物の失敗はこれまで通り
フローの失敗として表に出す。

## EQ05での拠点→通知先の解決

`EQ_Events`には`SiteCode`しか入っていないため、投稿先のTeam/Channelを引く必要がある。
ループ内でSwitchや変数を使うと並列実行で壊れるため、フロー先頭の`CMP_Site_Map`で
拠点コードをキーにしたオブジェクトを1つ作り、`outputs('CMP_Site_Map')?[<siteCode>]`
でキー参照している。

被災者数は式では数えられない(WDLに`filter`関数が無い)ため、
「配列のフィルター」アクション(`type: Query`)で絞ってから`length()`で数える。

## 並列ループ内で変数を使わない理由

Power Automateの変数は**フロー実行全体で共有**される。`LOOP_Each_Member`は
並列実行しているため、ループ内で`変数の設定`を使うと、あるメンバーの値が
別のメンバーの処理に混ざる。安否・出社可否の判定は変数ではなく**式で直接計算**する。

## 検証中の上司通知について

`testRecipientOverride`が設定されている間は、上司通知の宛先も同じアドレスへ
強制的に向けられる。実在の上司に訓練の被災報告が飛ぶことはない。
