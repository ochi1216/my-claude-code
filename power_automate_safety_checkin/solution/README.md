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
| SharePoint 項目の更新 | **未実測** | 未実測 |

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
| `connectionReferences.*` | エクスポートしたフローJSONの`connectionReferenceLogicalName`(例: `njp_sharedsharepointonline_xxxxx`) |
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
python build_flows_20260901_02.py --config deploy_config.json --out .\src --cards ..\cards
pac solution pack --zipfile .\EQSafetyCheckin.zip --folder .\src
pac solution import --path .\EQSafetyCheckin.zip
```

`pac auth create`でサインイン済みなら、インポート先は選択中の環境になるため
`--environment`は要らない。環境を明示したい場合は`pac env list`でIDを確認して渡す。

```powershell
pac env list
pac solution import --environment 0a1b2c3d-4e5f-6789-abcd-ef0123456789 --path .\EQSafetyCheckin.zip
```

**環境IDは`<...>`で囲まない。** PowerShellは`<`をリダイレクト記号として解釈するため、
`--environment <ENV_ID>`のようにプレースホルダのまま貼ると
`演算子 '<' は、今後の使用のために予約されています`というエラーになる(実機で発生)。

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

### 本番切替チェックリスト

**この手順を実行した瞬間から、実在の社員へ実際にカードが届く。**
実行前に必ず越智さんの明示的な確認を取ること。上から順に進める。

実測・実装が済んでいること:

- [x] `EQ_Received_Items`の列内部名を実測した(2026-09-01)
- [ ] `EQ_Received_Items`の`ProcessingStatus`/`ErrorCode`/`ErrorDetail`を数値型から1行テキストへ直した
- [ ] SharePoint「項目の更新」アクションの`operationId`・`idParameter`を実測し、`deploy_config.json`へ反映した
- [ ] `features.errorLogging` / `features.eventClose` を`true`にして生成し、インポートできた
- [ ] 意図的に失敗させて、`EQ_Received_Items`へ`ProcessingStatus=Error`の行が入ることを確認した
- [ ] 訓練終了後に`EQ_Events`の`AlertStatus`が`Closed`になり、`EQ05`がその回を集計しなくなることを確認した

拠点の設定:

- [ ] `sites[].teamId` / `channelId` に、OITA / OSAKA / TOKYO の実Team ID・Channel IDを設定した
- [ ] `responseTimeout`を検証用の短い値から運用値(既定`PT1H`)へ戻した

ここから先が「実在の社員へ届く」側の操作:

- [ ] `sites`から架空拠点`NARA`を取り除いた
- [ ] `EQ_Config_Members`から検証用メンバー(`emp98` / `emp99`)を削除した
- [ ] **`testRecipientOverride`を空文字にした** ← 誤送信防止の安全弁を外す唯一の操作
- [ ] 生成し直したときのコンソール表示が`[本番宛先モード]`になっていることを目視した
- [ ] 実在拠点で、まず3名程度の小規模訓練を実施した
- [ ] 問題がなければ18名訓練を実施した

## 生成されるフロー

| フロー | 状態 |
| --- | --- |
| `EQ06_Manual_Drill_DEV` | 生成対象 |
| `EQ04b_On_Response_DEV` | **不要になった**。カード応答を受け取るトリガーがテナントに存在しないため、回答の受け取りはEQ06のループ内(`PostCardAndWaitForResponse`)へ統合する |
| `EQ05_Status_Summary_DEV` | 生成対象・実機動作確認済み(2026-09-01)。`workflowIds`に載っているフローだけが生成されるため、不要なら設定から外せばよい |

## 機能フラグ(20260901_02 で追加)

エラー処理とイベントのクローズは、どちらも実測値が揃っていないと正しく動かない。
実測が済むまで既存の動作を止めないよう、`deploy_config.json`の`features`で
個別に有効化する方式にした。**未指定・両方falseなら、生成物は`20260901_01`と
1バイトも変わらない**(`verify_flows_20260901_01.py`で毎回確認している)。

```json
"features": {
  "errorLogging": false,
  "eventClose": false
}
```

| フラグ | 有効にすると | 必要な実測値 |
| --- | --- | --- |
| `errorLogging` | EQ06・EQ05の本体を`SCOPE_Try`で包み、失敗時に`SCOPE_Catch`から`EQ_Received_Items`へ1行(`ProcessingStatus=Error`)記録して失敗終了する | `listIds.EQ_Received_Items`、`columnInternalNames.EQ_Received_Items` |
| `eventClose` | 全員分の回答待ちが終わったら`EQ_Events`の`AlertStatus`を`Closed`に、失敗した場合は`Error`にする | `sharePointUpdateAction.operationId` / `.idParameter` |

実測値が`<未実測>`のまま有効にすると、**生成の時点で止まる**。推測値で作ると
インポートは通ってしまい、訓練当日の実行時に初めて失敗するため。

### エラー処理の構造

```
INIT_var...            ← 変数の初期化は最上位にしか置けないため、スコープの外に残す
SCOPE_Try
  ├ CMP_Site_Config / CMP_Intensity_Value / CHK_Threshold_Met(従来の本体そのまま)
SCOPE_Catch            runAfter: [Failed, TimedOut]
  ├ FLT_Failed_Actions … result('SCOPE_Try') から status=Failed のものだけ残す
  ├ CMP_Error_Code / CMP_Error_Raw / CMP_Error_Message(255文字で切り詰め)
  ├ SP_Log_Error       … EQ_Received_Items へ ProcessingStatus=Error で記録
  ├ CHK_Event_Created  … イベント作成済みなら AlertStatus を Error にする(eventClose時のみ)
  └ END_Failed         … 実行そのものを失敗として終わらせる
```

最後の`END_Failed`が無いと、「Catchが成功した」ことで**実行全体が成功扱いになり、
本物の失敗が実行履歴で緑色になってしまう**。

`Skipped`は`runAfter`に含めていない。`SCOPE_Try`の手前は変数の初期化しかなく、
スキップされる経路が無いため。

**Terminateで終わる経路はCatchを通らない。** 拠点コード誤り(`END_Invalid_Site`)、
震度コード誤り(`END_Invalid_Intensity`)、対象者ゼロ(`END_No_Members`)は
`Terminate`で即座に実行が終わるため、`EQ_Received_Items`には残らない。
記録に残るのは、コネクタの失敗(リストGUID誤り、SharePoint側の障害、
Teams投稿の失敗など)である。

### SharePoint「項目の更新」アクションの実測手順

`operationId`もパラメータ名も公開情報からは確定できない。以下で実測する。

1. Power AutomateのGUIで、インスタント フロー(手動トリガー)を新規作成する
2. アクションを1つだけ追加する: SharePoint →「項目の更新」
3. サイトのアドレス・リスト名(`EQ_Events`)・IDを適当に埋めて保存する
4. そのフローを **エクスポート(パッケージ .zip)** し、展開して中のJSONを開く
5. `"host"`の`"operationId"`と、項目IDを渡しているパラメータ名を控える

```json
"host": { "connectionName": "shared_sharepointonline", "operationId": "????" },
"parameters": { "dataset": "...", "table": "...", "??": 1, "item/Title": "..." }
```

6. `deploy_config.json`の`sharePointUpdateAction`へ入れる

```json
"sharePointUpdateAction": {
  "operationId": "<手順5で控えたoperationId>",
  "idParameter": "<項目IDを渡しているパラメータ名>"
}
```

7. 確認用のフローは削除してよい

更新対象はイベントのタイトルではなく**SharePointの項目ID(整数)**で指す。
イベント作成時の応答`body('SP_Create_Event')?['ID']`を変数`varEventItemId`へ
控えておき、それを使う。`Title`は必須列のため、更新時にも同じ値を送り直している。

### 列内部名の実測手順

SharePointにログイン済みのブラウザで下記を開くと、表示名・内部名・型が一度に得られる。

```
https://<サイトURL>/_api/web/lists/getbytitle('EQ_Received_Items')/fields?$select=InternalName,Title,TypeAsString&$filter=Hidden eq false and ReadOnlyField eq false
```

`EQ_Received_Items`もExcelアップロードで作ったため、`EQ_Events`で起きたのと同じ
**「見本データ無しのExcelから作ったせいでテキスト列が数値型になる」問題**が
起きていないかを、内部名と一緒に必ず確認する。必要な型は以下。

**実測済み(2026-09-01)**。実際のリストは`EQ_Received_Items.xlsx`と列構成が異なり、
エラー内容の列は`ErrorMessage`ではなく`ErrorDetail`、`CreatedAt`は存在しなかった
(SharePointの標準列`Created`が自動で入るため、`CreatedAt`は任意扱いにしている)。

| 内部名 | 表示名 | 実測した型 | 必要な型 |
| --- | --- | --- | --- |
| `Title` | Title | Text | 1行テキスト ✓ |
| `field_4` | ProcessingStatus | 数値 | **1行テキスト(要修正)** |
| `field_5` | ErrorCode | 数値 | **1行テキスト(要修正)** |
| `field_6` | ErrorDetail | 数値 | **1行テキスト(要修正)**。255文字を超える分はフロー側で切り詰めている |

`field_1`〜`field_3`(`SourceUpdatedAt`/`SourceLink`/`InformationType`)はP1では使わない。

## deploy_config.json への設定の追加

`deploy_config.json`はGit管理外のため、新しい設定項目が増えても自動では入らない。
手で足すとカンマの付け忘れで壊しやすいので、追記用のスクリプトを用意している。

```powershell
python update_deploy_config_20260901_01.py --received-items-list-id <GUID> --enable-error-logging
```

- 追加されるのは`columnInternalNames.EQ_Received_Items`・`features`・
  `sharePointUpdateAction`の3つ。**すでにある値は書き換えない**(何度実行してもよい)
- 書き換える前に`deploy_config.json.bak_<日時>`という控えを作る
- リストGUIDは社内情報のためスクリプトには書いていない。`--received-items-list-id`で
  渡すか、引数なしで実行して問い合わせに答える(すでに設定済みなら不要)
- `--enable-error-logging` / `--enable-event-close` で機能フラグを`true`にできる。
  付けなければ`false`のまま追加される
- 書き出したあとJSONとして読み直し、壊れていないことを確かめてから終了する

## 生成物の検証(テナントに入れる前)

```powershell
python verify_flows_20260901_01.py
```

`deploy_config.json`は不要(ダミー設定で構造だけを見る)。インポートで弾かれる
ありがちな間違いをここで潰す。

- 機能フラグを全てオフにしたとき、`20260901_01`と1バイトも変わらない出力になるか
- `runAfter`が同じスコープ内に実在するアクションを指しているか
- アクション名がフロー全体で一意か
- `Terminate`がループの中に入っていないか(入れるとインポートで弾かれる)
- `InitializeVariable`が最上位のみか(同上)
- 参照・代入している変数がすべて初期化済みか
- 並列ループの中で`SetVariable`を使っていないか(値が混ざる)
- 未実測のまま機能を有効にしたとき、生成が止まるか

実機での動作確認の代わりにはならない。Windows/Power Automate環境が要る確認は
引き続き実機で行う。

## 未確認事項

- `EQ_Received_Items`の列内部名は実測済み(2026-09-01)。ただし
  **`ProcessingStatus`/`ErrorCode`/`ErrorDetail`が数値型で作られており、
  1行テキストへ直すまでエラー記録の書き込みは失敗する。**
- **SharePoint「項目の更新」アクションの`operationId`・パラメータ名は未実測**。
  実測するまで`features.eventClose`は有効にできない。
- エラー処理・クローズ処理は**実機未検証**。生成物の構造検証のみ実施済み。
  スコープの中に`Terminate`を置けること、`result('SCOPE_Try')`が期待する形の
  配列を返すことは、インポートと実行で確認する必要がある。
- 実在拠点(OITA/OSAKA/TOKYO)での訓練は**未実施**。現状は架空拠点`NARA`でのみ検証している。
- 3名結合テスト・18名訓練は未実施。
- 拠点ごとの実Team ID / Channel IDは**未設定**。

## タイムアウト(未回答)の扱い

実際の訓練では時間内に回答しない人が必ずいるため、それでフローが失敗しては困る。

最初は待機アクションの後続を2つに分け、片方(`SP_Create_Response`)を
`runAfter=Succeeded`、もう片方(受け皿のCompose)を`runAfter=TimedOut`にしていたが、
**タイムアウト時にループ全体が失敗した**(実測)。エラーは
`ActionFailed. An action failed. No dependent actions succeeded.`。
受け皿自体は成功していたが、もう一方がスキップのまま残るとスコープが失敗と判定される。

このため、**待機アクションの後続を`CHK_Responded`という条件1つにまとめ**、
その中で回答あり/未回答に分岐する構造へ変更した。この形で、1分のタイムアウト後に
フローが正常終了することを実機で確認済み(2026-09-01)。

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
