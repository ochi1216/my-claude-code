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
| `EQ05_Status_Summary_DEV` | **未実装** |

## 未確認事項

- 1:1チャットへのカード投稿(`location: "Chat with Flow bot"`, `body/recipient`にメールアドレス)は、
  チャネル投稿と違い実測できていない。初回実行時に要確認。
- 回答が返ってきたときのJSONの構造(`body('TM_Post_CheckIn_Card')`の中身)は**未実測**。
  現在はループ内の`CMP_Raw_Response`で生の応答をそのまま記録しており、実行履歴から
  読み取って確定させる。確定後、回答の解釈・`EQ_Responses`への保存・被災時の上司通知を
  実装する。
- 未回答者がいた場合のタイムアウト時の挙動(ループが失敗扱いになるか)は未確認。
