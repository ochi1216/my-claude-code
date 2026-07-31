# フローロジック仕様(コピペ用) — Power Automate PoC版(P1: 手動トリガー)

このドキュメントは、Power Automateの画面で「何を組むか考える」時間をゼロにするためのものである。
各アクションは、命名規則(`handover/CLAUDE_CODE_HANDOVER.md` §14.2の接頭辞)に従って
そのままの名前で作成し、式は記載の通りコピペするだけでよい。

対象は **P1(手動トリガー版)** の5フローのみ。自動地震検知(EQ01/EQ02の自動連携)は
Gate C不合格見込みのため、このPoCには含めない(詳細は `docs/REVIEW_earthquake_safety_system_0730_02.md` 参照)。

非同期アーキテクチャを採用している(レビュー指摘: EQ04を直列ループ内で応答待ちにすると、
1人目の回答まで他の17名にカードが届かない)。カード送信と回答受信を別フローに分離する。

```
EQ06_Manual_Drill_DEV
  トリガー入力(SiteCode, IntensityCode, Epicenter, IsTest)
    → 拠点取得・閾値判定・イベント作成
    → チャネル通知(非対話カード)
    → 対象者へ個人カードを投げ切り（待たない）

EQ04b_On_Response_DEV
  トリガー: カードへの応答があったとき
    → 回答者照合・SharePointへUpsert
    → 被災なら上司へ即通知

EQ05_Status_Summary_DEV
  トリガー: 15分ごとのスケジュール
    → Open状態のイベントを集計・投稿
```

---

## 前提: 環境変数(すべてのフローで共通)

Power AutomateのSolution機能で、以下を**環境変数**として登録する
（フロー内に直書きしない。DEV/TEST/PROD切替を容易にするため）。

| 環境変数名 | 内容 | 例 |
| --- | --- | --- |
| `eq_SharePointSiteUrl` | SharePointサイトURL | `https://contoso.sharepoint.com/sites/EQSafetyCheckin` |

### 拠点(大分・大阪・東京)の設定は「固定値」として扱う

当初はSharePointリスト(`EQ_Config_Sites`)で拠点・震度閾値・通知先を管理する設計だった
（AD-03: 設定はフロー外出し）が、以下の理由から**SharePointリストは廃止**し、
`EQ06_Manual_Drill_DEV`内のSwitchアクション(`CMP_Site_Config`)に固定値として持たせる。

- 監視対象(大分県・大阪府・東京都)と閾値(震度5弱)は運用開始後も変わらない想定であり、
  リストとして外出しするほどの可変性がない。
- 拠点情報は`TeamId`/`ChannelId`を含み、全員が閲覧できるSharePointリストに置くよりも、
  フロー内(編集権限を持つ人だけがアクセスできる)に留める方が適切。

スタッフ・上司の名簿(`EQ_Config_Members`)は人の入れ替わりが起きるため、
引き続きSharePointリストで管理する。

---

## EQ06_Manual_Drill_DEV

### トリガー: `TRG_Manual_Drill`

種類: 手動でフローをトリガーします(Manually trigger a flow)

入力パラメータ:

| 名前 | 型 | 選択肢 | 必須 |
| --- | --- | --- | --- |
| `SiteCode` | テキスト(1行) | — | Yes |
| `IntensityCode` | テキスト(1行、選択肢) | `1,2,3,4,5-,5+,6-,6+,7` | Yes |
| `Epicenter` | テキスト(1行) | — | No |
| `IsTest` | はい/いいえ | 既定値: はい | Yes |

### アクション順序

**1. `CMP_Site_Config`** — Switch(スイッチ)アクション

切り替える値: `triggerBody()['SiteCode']`

拠点情報はSharePointから取得せず、ここに固定値として持たせる(上記「拠点の設定は
固定値として扱う」を参照)。各ケースで「作成(Compose)」を1つ置き、以下のJSONを出力する。
`TeamId`/`ChannelId`は、実際にPower AutomateでTeam/チャネルを用意した後、
このCompose内の値を直接書き換えること。

| ケース | Compose出力(JSON) |
| --- | --- |
| `OITA` | `{"SiteName": "Japan Oita Site", "ThresholdValue": 50, "TeamId": "<OITA_TEAM_ID>", "ChannelId": "<OITA_CHANNEL_ID>"}` |
| `OSAKA` | `{"SiteName": "Japan Osaka Site", "ThresholdValue": 50, "TeamId": "<OSAKA_TEAM_ID>", "ChannelId": "<OSAKA_CHANNEL_ID>"}` |
| `TOKYO` | `{"SiteName": "Japan Tokyo Site", "ThresholdValue": 50, "TeamId": "<TOKYO_TEAM_ID>", "ChannelId": "<TOKYO_CHANNEL_ID>"}` |
| 既定(Default) | **`END_Invalid_Site`**(終了・失敗、"CFG-001: unknown site code") |

**2. `CMP_Intensity_Value`** — Switch(スイッチ)アクション

切り替える値: `IntensityCode` 入力。

各ケースで「作成(Compose)」を1つ置き、以下の数値を出力する。

| ケース | Compose出力 |
| --- | --- |
| `1` | `10` |
| `2` | `20` |
| `3` | `30` |
| `4` | `40` |
| `5-` | `50` |
| `5+` | `55` |
| `6-` | `60` |
| `6+` | `65` |
| `7` | `70` |
| 既定(Default) | **`END_Invalid_Intensity`**(終了・失敗、"SRC-003: invalid intensity code") |

**3. `CHK_Threshold_Met`** — 条件

式:
```
greaterOrEquals(outputs('CMP_Intensity_Value'), outputs('CMP_Site_Config')?['ThresholdValue'])
```

- いいえの場合: **`END_Below_Threshold`**(終了・成功。「閾値未満のためイベントを作成しない」というのは
  正常系であり、失敗ではない)

**4. `CMP_EventID`** — 作成(Compose)

式:
```
concat('EQ-', formatDateTime(utcNow(), 'yyyyMMdd-HHmmss'), '-', triggerBody()['SiteCode'])
```

**5. `SP_Create_Event`** — SharePoint「項目の作成」

リスト: `EQ_Events`

| 列 | 値 |
| --- | --- |
| Title | `outputs('CMP_EventID')` |
| SiteCode | `triggerBody()['SiteCode']` |
| OccurredAt | `utcNow()` |
| Epicenter | `triggerBody()['Epicenter']` |
| SiteIntensityCode | `triggerBody()['IntensityCode']` |
| SiteIntensityValue | `outputs('CMP_Intensity_Value')` |
| AlertStatus | `Open` |
| StartedBy | `Manual` |
| IsTest | `triggerBody()['IsTest']` |

**6. `CMP_OccurredAtJST`** — 作成(Compose)

式(UTC→JST、+9時間):
```
convertTimeZone(utcNow(), 'UTC', 'Tokyo Standard Time', 'yyyy/MM/dd HH:mm')
```

**7. `TM_Post_Channel_Alert`** — Teams「アダプティブ カードをチャットまたはチャネルに投稿する」
(非対話・**待たないアクション**を選択すること。「〜して応答を待つ」ではない)

- 投稿先: チーム = `outputs('CMP_Site_Config')?['TeamId']`、
  チャネル = `outputs('CMP_Site_Config')?['ChannelId']`
- カードJSON: `cards/channel_alert_card.json` の内容をそのまま貼り付け
- 変数バインド:

  | プレースホルダ | 式 |
  | --- | --- |
  | `TestPrefix` | `if(triggerBody()['IsTest'], '【訓練】', '')` |
  | `SiteName` | `outputs('CMP_Site_Config')?['SiteName']` |
  | `Intensity` | `triggerBody()['IntensityCode']` |
  | `Epicenter` | `triggerBody()['Epicenter']` |
  | `OccurredAtJST` | `outputs('CMP_OccurredAtJST')` |
  | `EventID` | `outputs('CMP_EventID')` |

**8. `GET_Active_Members`** — SharePoint「複数の項目の取得」

- リスト: `EQ_Config_Members`
- フィルタークエリ:
  ```
  SiteCode eq '@{triggerBody()['SiteCode']}' and IsActive eq 1 and IsManager eq 0
  ```

**9. `CHK_Members_Found`** — 条件

式: `length(outputs('GET_Active_Members')?['body/value'])`が`0`と等しいか。

- はいの場合: **`END_No_Members`**(終了・失敗、"CFG-003: no active members")

**10. `LOOP_Each_Member`** — Apply to each

対象: `outputs('GET_Active_Members')?['body/value']`
同時実行数(Concurrency Control): **初期値1**(Gate B確認後に引き上げ検討)

ループ内アクション:

**10-1. `TM_Post_CheckIn_Card`** — Teams「アダプティブ カードをチャットまたはチャネルに投稿する」
(1:1チャット宛て、**待たないアクション**)

- 宛先: `items('LOOP_Each_Member')?['Email']`
- カードJSON: `cards/checkin_card.json`
- 変数バインド:

  | プレースホルダ | 式 |
  | --- | --- |
  | `EventID` | `outputs('CMP_EventID')` |
  | `SiteName` | `outputs('CMP_Site_Config')?['SiteName']` |
  | `Intensity` | `triggerBody()['IntensityCode']` |
  | `OccurredAtJST` | `outputs('CMP_OccurredAtJST')` |
  | `EmployeeID` | `items('LOOP_Each_Member')?['Title']` |

**11. `END_Success`** — フローを終了(成功)

---

### エラー処理(SCOPE_Try/Catch/Finally)

引継ぎ資料の指示通り、上記1〜11全体を `SCOPE_Try` で包み、`SCOPE_Catch`
(実行条件: 直前がFailedまたはTimed outまたはSkippedの場合に実行)で
`SP_Log_Error`(EQ_Received_Itemsへ ProcessingStatus=`Error` で記録)を行う。

---

## EQ04b_On_Response_DEV

### トリガー: `TRG_On_Adaptive_Card_Response`

種類: Teams「アダプティブ カードに応答があったとき」
(1:1チャットおよびチャネルの両方を監視。テナントの既定環境でのみ実行される点に注意)

**重要:** このトリガーが返すJSONの実際のキー名(`responder`のパス等)は、
Gate Bで実行履歴から取得するまで **未確定**とする。以下は暫定の式であり、
`evidence/teams_wait_output_sanitized.json` を取得した時点で確定させること
(`docs/05_EXPRESSION_CATALOG.md` 相当の更新)。

### アクション順序

**1. `PAR_Response`** — JSON の解析(Parse JSON)

コンテンツ: `triggerBody()?['data']`(暫定パス)

スキーマ:
```json
{
  "type": "object",
  "properties": {
    "eventId": { "type": "string" },
    "employeeId": { "type": "string" },
    "responseCode": { "type": "string" },
    "comment": { "type": "string" }
  }
}
```

**2. `CFG_Get_Member`** — SharePoint「複数の項目の取得」

- リスト: `EQ_Config_Members`
- フィルタークエリ:
  ```
  Title eq '@{body('PAR_Response')?['employeeId']}'
  ```

**3. `CHK_Responder_Identity`** — 条件(T30対策: カード内のEmployeeIDだけを信用しない)

式(暫定。実際の応答者メールのパスはGate Bで確定):
```
equals(toLower(first(outputs('CFG_Get_Member')?['body/value'])?['Email']), toLower(triggerBody()?['responder']?['email']))
```

- いいえの場合: **`SP_Log_Quarantine`**(EQ_Received_Itemsへ ProcessingStatus=`Error`、
  ErrorCode=`T30_IDENTITY_MISMATCH` を記録し、`END_Quarantine`で終了。回答は保存しない)

**4. `CMP_ResponseMapping`** — Switch

切り替える値: `body('PAR_Response')?['responseCode']`

| ケース | SafetyStatus | WorkStatus |
| --- | --- | --- |
| `1` | `Safe` | `Available` |
| `2` | `Safe` | `Unavailable` |
| `3` | `Affected` | `Available` |
| `4` | `Affected` | `Unavailable` |
| 既定 | **`END_Invalid_Response`**(終了・失敗) | |

**5. `CMP_ResponseKey`** — 作成(Compose)

式:
```
concat(body('PAR_Response')?['eventId'], '|', body('PAR_Response')?['employeeId'])
```

**6. `SP_Get_Existing_Response`** — SharePoint「複数の項目の取得」

- リスト: `EQ_Responses`
- フィルタークエリ: `Title eq '@{outputs('CMP_ResponseKey')}'`

**7. `CHK_Response_Exists`** — 条件

式: `length(outputs('SP_Get_Existing_Response')?['body/value'])` が `0` より大きいか。

- はい: **`SP_Update_Response`**(既存項目のRevisionを+1、RespondedAt更新、Comment上書き)
- いいえ: **`SP_Create_Response`**(新規作成、Revision=1)

いずれも書き込む列: EventID, EmployeeID, Email, ResponseCode, SafetyStatus,
WorkStatus, RespondedAt=`utcNow()`, Comment=`body('PAR_Response')?['comment']`

**8. `CHK_Affected`** — 条件

式: `equals(<SafetyStatusの値>, 'Affected')`

- はいの場合、`LOOP_Notify_Managers`:
  - `GET_Managers`: SharePoint「複数の項目の取得」`EQ_Config_Members`、
    フィルター `SiteCode eq '@{first(outputs('CFG_Get_Member')?['body/value'])?['SiteCode']}' and IsManager eq 1 and IsActive eq 1`、
    並び替え: `EscalationOrder asc`
  - `TM_Notify_Manager`: Teams「メッセージをチャットに投稿する」各上司の1:1チャットへ、
    本文に社員名・拠点・回答内容(SafetyStatus/WorkStatus/Comment)を含める

---

## EQ05_Status_Summary_DEV

### トリガー: `TRG_Recurrence`

種類: 定期実行、間隔15分(初期値。運用で調整)

### アクション順序

**1. `GET_Open_Events`** — SharePoint「複数の項目の取得」

- リスト: `EQ_Events`
- フィルタークエリ: `AlertStatus eq 'Open'`

**2. `LOOP_Each_Open_Event`** — Apply to each、対象: `outputs('GET_Open_Events')?['body/value']`

ループ内:

- `GET_Site_Members`: `EQ_Config_Members`、フィルター
  `SiteCode eq '@{items('LOOP_Each_Open_Event')?['SiteCode']}' and IsActive eq 1 and IsManager eq 0`
- `GET_Event_Responses`: `EQ_Responses`、フィルター
  `EventID eq '@{items('LOOP_Each_Open_Event')?['Title']}'`
- `CMP_Answered_Count`: `length(outputs('GET_Event_Responses')?['body/value'])`
- `CMP_Total_Count`: `length(outputs('GET_Site_Members')?['body/value'])`
- `CMP_Unanswered_Count`: `sub(outputs('CMP_Total_Count'), outputs('CMP_Answered_Count'))`
- `CMP_Affected_Count`: レスポンス配列を `SafetyStatus eq 'Affected'` でフィルターした件数
  ```
  length(filter(outputs('GET_Event_Responses')?['body/value'], item()?['SafetyStatus'] eq 'Affected'))
  ```
- `TM_Post_Summary`: チャネルへ集計結果を投稿(回答数/未回答数/被災者数)

---

## Gate B確認後に更新すべき箇所(一覧)

以下は実行履歴が得られるまで暫定値である。`evidence/`取得後、このドキュメントを更新すること。

1. `TRG_Manual_Drill`の各入力の内部トークン名(`triggerBody()['SiteCode']`等)
2. `TRG_On_Adaptive_Card_Response`のトリガー出力パス(`triggerBody()?['data']`、`?['responder']?['email']`)
3. Teams「アダプティブ カードをチャットまたはチャネルに投稿する」アクションの正式名称と、
   非推奨でないことの確認(Gate B)
