# Gate Status — power_automate_safety_checkin (P1: 手動トリガー版)

`docs/REVIEW_earthquake_safety_system_0730_02.md` の Gate 定義を、
P1(手動トリガー・自動地震検知なし)のスコープに合わせて再評価したもの。

| Gate | 内容 | 状態 | 備考 |
| --- | --- | --- | --- |
| A | コネクタ利用可否(RSS/SharePoint/Teamsが全てStandard) | **未確認** | P1ではRSSコネクタ自体を使わないため対象外。SharePoint/TeamsがStandard表示であることを実環境で確認する必要がある |
| B | Teams Adaptive Cardアクション(非推奨でない・応答データが取得できる) | **合格(2026-09-01実測)** | 実テナントのTeamsコネクタに「チャットやチャネルにカードを投稿する」(`PostCardToConversation`、応答を待たない)が標準コネクタとして存在し、非推奨表記もない。投げ切り型の非同期設計をそのまま採用できる。「アダプティブ カードを投稿して応答を待機する」(`PostCardAndWaitForResponse`)も併存。1:1チャットへの投稿(`location: "Chat with Flow bot"`)も実機で成功。**ただし応答受信トリガーは存在しない**(下記) |
| C | JMA Atom→XML本文取得 | **対象外(P1では不使用)** | 自動地震検知はP2として別途判断。P1は手動トリガーのみのため、このGateはP1の完成条件に含まれない |
| D | SharePoint内部名 | **実測完了(2026-09-01)** | 4リストすべて実測済み。`EQ_Received_Items`はS03で実測し、**リポジトリの`EQ_Received_Items.xlsx`と列構成が違う**ことが判明(下記)。`evidence/sharepoint_internal_names.json`に記録。**Excelアップロードで作ったリストは、内部名が表示名と一致せず`field_1`,`field_2`...という連番になる**(`Title`のみ標準列)。フローの`item/<列>`・`$filter`では内部名を使う必要がある。あわせて、型の誤検出も判明(下記) |
| E | 共同所有・接続継続 | **未確認** | Solutionの共同所有者設定、接続参照の再認証手順は`docs/MANUAL_STEPS.md`のTEST/PROD展開時に確認する |

## Gate D で判明した、SharePoint列の型の誤検出

見本データを含まないExcelをアップロードしたため、SharePointが列の型を推測できず、
テキストであるべき列が**数値型**で作られていた。以下はP1の運用前に修正が必要。

| リスト | 列(表示名) | 内部名 | 現在の型 | 必要な型 |
| --- | --- | --- | --- | --- |
| EQ_Events | SiteCode | `field_2` | 数値 | 1行テキスト |
| EQ_Events | OccurredAt | `field_3` | 数値 | 日付と時刻 |
| EQ_Events | Epicenter | `field_5` | 数値 | 1行テキスト |
| EQ_Events | SiteIntensityCode | `field_7` | 数値 | 1行テキスト |
| EQ_Events | IsTest | `field_11` | 数値 | はい/いいえ |
| EQ_Received_Items | ProcessingStatus | `field_4` | 数値 | 1行テキスト |
| EQ_Received_Items | ErrorCode | `field_5` | 数値 | 1行テキスト |
| EQ_Received_Items | ErrorDetail | `field_6` | 数値 | 1行テキスト |

`AlertStatus`(`field_9`)と`StartedBy`(`field_10`)も同じ問題があったが、修正済み。
`EQ_Config_Members`は型の問題なし(ただし`IsActive`/`IsManager`がテキスト型のため、
フィルターは数値比較ではなく文字列比較にしている)。

## P1完成条件(Definition of Doneの再定義)

- [x] Gate B: Teamsの投げ切りカード投稿アクションが標準コネクタに存在することを実測
- [x] Gate D: SharePoint列内部名を実測(`field_N`形式であることが判明)
- [x] EQ_Eventsの列の型を修正(上表。数値型で作られていた5列をテキスト/はい・いいえへ変更)
- [x] `EQ06_Manual_Drill_DEV`が閾値未満パターンで正常終了する(震度4→`END_Below_Threshold`)
- [x] `EQ06_Manual_Drill_DEV`が閾値以上パターンで最後まで走る(震度5弱→SharePoint記録・
      チャネル投稿・個人カード送信まで全て成功)
- [x] 検証中の誤送信防止が機能する(`testRecipientOverride`により、名簿の内容に
      かかわらず個人カードが検証者だけに届くことを実機で確認)
- [x] カード応答の受け取り〜`EQ_Responses`への保存が動作(2026-09-01実測)
- [x] 被災回答時の上司通知が動作(2026-09-01実測)
- [x] 未回答(タイムアウト)でもフローが正常終了する(2026-09-01実測)
- [x] `EQ05_Status_Summary_DEV`が集計結果をチャネルへ投稿する(2026-09-01実測)
- [x] `EQ_Received_Items`の列内部名を実測(2026-09-01。`evidence/`に記録)
- [ ] `EQ_Received_Items`の列の型を修正(上表の3列。数値型のままでは記録の書き込みが失敗する)
- [ ] SharePoint「項目の更新」アクションの`operationId`・パラメータ名を実測
      (**未実測**。イベントのクローズ処理の前提条件)
- [x] エラー処理を有効にした状態で、EQ06が従来どおり最後まで正常終了する
      (2026-09-01実測。`SCOPE_Try`で包んでも通常の動作を壊していない)
- [x] エラー処理が失敗時に`EQ_Received_Items`へ記録する(2026-09-01実測。
      `evidence/error_log_sample_sanitized.json`。ただし記録される内容は失敗した枝の
      名前止まりで、原因の特定には実行履歴が要る)
- [ ] イベントのクローズ処理が実機で動作する(コードは実装済み・**実機未検証**)
- [ ] 拠点ごとの実Team ID / Channel IDを設定(**未設定**)
- [ ] 検証用設定の解除(`testRecipientOverride`・架空拠点`NARA`・検証用メンバー)
      ※実行前に必ずユーザーの明示的な確認を取る
- [ ] 単一ユーザー(越智さん)での手動訓練が3回連続成功
- [ ] 3名結合テスト(T08〜T11: 4択それぞれの回答保存を確認)
- [ ] 18名訓練(対象者数と回答集計が一致)
- [ ] Premiumコネクタ参照が0件
- [ ] Git上に個人メール・Tenant ID・Team ID・Channel IDが含まれていない

## Gate B の続き: カード応答を受け取るトリガーは存在しない(2026-09-01実測)

Teamsコネクタのトリガーは11種類あり、その全てを確認した結果、
**アダプティブカードの回答を受け取るトリガーは存在しない。**

紛らわしいものとして「チャットでメッセージに応答があったとき」があるが、
実体は `WebhookMessageReactionTrigger`(=When someone reacted to a message in chat)で、
**絵文字リアクションの検知**であり、カードの回答とは無関係。

これにより、`docs/FLOW_LOGIC_SPEC.md`の当初設計(カードを投げ切り、
`EQ04b_On_Response_DEV`という別フローで回答を受ける非同期方式)は**成立しない**。

### 採用した代替案

`PostCardAndWaitForResponse`(アダプティブ カードを投稿して応答を待機する)を
`LOOP_Each_Member`の中で使い、**ループを並列実行**する。

- 直列だと1人目が回答するまで他の人にカードが届かない(レビュー指摘)ため、
  同時実行数を上げて全員分を同時に待つ(Power Automateの上限は50、既定値20)
- 待機には`limit.timeout`(既定`PT1H`)を設定し、未回答者がいてもフローが
  居座り続けないようにする
- `EQ04b_On_Response_DEV`は不要になり、回答の保存・上司通知はEQ06のループ内へ移す

### 検証環境について

実在拠点(OITA/OSAKA/TOKYO)の名簿には実際の社員が登録されているため、テストで
これらを選ぶと本人へ安否確認カードが届いてしまう。検証中は以下の二重の防御を敷いている。

1. `deploy_config.json`の`testRecipientOverride` — 設定されている限り、拠点や
   `IsTest`の値にかかわらず個人カードは検証者だけに届く
2. 架空拠点`NARA`(検証者1名のみ所属) — 実在拠点の名簿に触れずに拠点分岐を試せる

本番運用へ移る際は、1を空文字にし、2を`sites`から取り除く。

自動地震検知(Gate C相当)は、P1完成後にP2として別途着手する。

## 見送った改善(P1のスコープ外。必要になったら着手する)

### エラー内容をアクション単位まで具体化する

`EQ_Received_Items`に残るのは失敗した枝の名前(`CHK_Threshold_Met`)止まりで、
実際に失敗したアクション名もコネクタのメッセージも入らない
(`evidence/error_log_sample_sanitized.json`)。原因の特定にはPower Automateの
実行履歴を開く必要がある。

具体化するには、閾値以上の本処理を`SCOPE_Main`として一段入れ子にし、その直後に
`result('SCOPE_Main')`を見る内側のCatchを置く必要がある。**フローの入れ子が
一段深くなり、再度の生成・インポート・動作確認が要る**ため、S03では見送った
(2026-09-01、ユーザー判断)。「失敗が起きたことに気づける」という当初の目的は
現状で満たしている。

## S03で実装したが実機未検証の項目(2026-09-01)

`solution/build_flows_20260901_02.py`でエラー処理とイベントのクローズを実装した。
ただし開発環境(Linuxコンテナ)からはテナントへインポートも実行もできないため、
**動作は未検証**である。生成したフロー定義(JSON)の構造検証のみ
`solution/verify_flows_20260901_01.py`で実施済み(107項目すべて合格)。

### 存在しないリストGUIDは実行時ではなく保存時に弾かれる(2026-09-01実測)

エラー処理の動作確認のため`EQ_Events`のリストGUIDを存在しない値にしてインポートしたところ、
実行前にデザイナーの保存・検証で`GetTable`が`NotFound`となり、**フローがオフになった**。

```
Flow save failed with code 'DynamicOperationRequestClientFailure' ...
operation 'GetTable' failed with status code 'NotFound' ... "List not found"
```

リストGUIDは保存時に解決されるため、この壊し方では`SCOPE_Catch`まで到達しない。
`$filter`はSharePointがサーバ側で評価する文字列で保存時に検証されないため、
フィルターに使う列の内部名を存在しないものへ差し替える方式に変更した。

### listIds に全ゼロのGUIDが入ると、原因にたどり着けない(2026-09-01実測)

`listIds.EQ_Received_Items`が`00000000-0000-0000-0000-000000000000`のまま
生成・インポートまで通り、フローを開いた時点で`List not found`になって
**フローがオフのまま戻せなくなった。**

全ゼロは書式としては正しいGUIDに見えるため、書式の突き合わせでも「設定済み」判定でも
異常だと分からない。生成側の`is_measured()`で全ゼロを未実測として弾き、
`--diagnose`で明示的に警告するようにした。

実機で確認すべき、公開情報からは確定できなかった点:

| 項目 | 前提にしていること | 外れた場合に起きること |
| --- | --- | --- |
| ~~`Scope`の中に`Terminate`を置けるか~~ | **確認済(2026-09-01)**。エラー処理・クローズ処理を含むSolutionのインポートが成功したため、`Scope`内の`Terminate`と`SCOPE_Catch`の構造、`result('SCOPE_Try')`の式はいずれも検証を通る | — |
| `result('SCOPE_Try')`の戻り値 | `name` / `status` / `error.code` / `error.message` を持つオブジェクトの配列 | エラー内容が`UNKNOWN` / `(no message)`で記録される(記録自体は残る) |
| `body('SP_Create_Event')?['ID']` | SharePointの項目作成の応答に、項目IDが`ID`というキーで含まれる | クローズ処理が対象を特定できず失敗 |
| `EQ_Received_Items`の列の型 | `ProcessingStatus`/`ErrorCode`/`ErrorDetail`が1行テキスト | **実測の結果、3列とも数値型だった。修正するまで記録の書き込みが失敗する** |

いずれも、実測値を`deploy_config.json`へ入れて生成し直せば直せる範囲にしてある
(推測値を埋め込まず、設定から読む作りにしたのはこのため)。

## Gate D の追加実測: EQ_Received_Items(2026-09-01)

実際のリストは、リポジトリの`EQ_Received_Items.xlsx`
(`Title`/`ProcessingStatus`/`ErrorCode`/`ErrorMessage`/`CreatedAt`)と**列構成が異なる**。

| 内部名 | 表示名 | 型 | P1での用途 |
| --- | --- | --- | --- |
| `Title` | Title | Text | エラーのキー(EventID、または`ERR-EQ0x-<時刻>`) |
| `field_1` | SourceUpdatedAt | 数値 | 未使用 |
| `field_2` | SourceLink | 数値 | 未使用 |
| `field_3` | InformationType | 数値 | 未使用 |
| `field_4` | ProcessingStatus | 数値 | `Error`を記録(**要型修正**) |
| `field_5` | ErrorCode | 数値 | エラーコード(**要型修正**) |
| `field_6` | ErrorDetail | 数値 | エラー内容(**要型修正**) |

- エラー内容の列は`ErrorMessage`ではなく**`ErrorDetail`**。フロー側をこの名前に合わせた。
- **`CreatedAt`列は存在しない。** SharePointの標準列`Created`(作成日時)が自動で入るため、
  発生時刻は失われない。`CreatedAt`は設定にあれば書き、無ければ書かない任意扱いにした。
- `SourceUpdatedAt`/`SourceLink`/`InformationType`は、P2の自動地震検知でJMAフィードの
  受信を記録するための列と思われる。**このリストがどの版のExcelから作られたかは未確認。**
