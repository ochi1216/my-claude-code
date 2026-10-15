# evidence/ — Gate B・Gate D実測値の格納先

このディレクトリには、Power Automate DEV環境での実行結果から得られる
**サニタイズ済み**の実測値のみを置く。個人メール・Tenant ID・Team ID・
Channel ID等の生の識別子はコミットしない(`GATE_STATUS.md`の完成条件参照)。

## 置くファイル

| ファイル | 内容 | 取得元 |
| --- | --- | --- |
| `teams_card_response_sanitized.json` | Gate B: `PostCardAndWaitForResponse`が返す応答JSON(個人情報をマスクしたもの) | `EQ06_Manual_Drill_DEV`の実行履歴 → `LOOP_Each_Member` → `CMP_Raw_Response`の出力 |
| `sharepoint_internal_names.json` | Gate D: 4リストの列内部名(表示名 → 内部名の対応表) | SharePointの「リストの設定」→ 各列 → URLの`Field=`部分 |

## サニタイズ方法(Gate B)

`teams_wait_output_sanitized.json`を保存する前に、以下を置換すること。

- メールアドレス → `user01@example.com`のようなプレースホルダ
- 表示名 → `テスト太郎`のようなプレースホルダ
- Tenant ID / AAD Object ID(GUID) → `00000000-0000-0000-0000-000000000000`
- Team ID / Channel ID → `<TEAM_ID>` / `<CHANNEL_ID>`

キー名(パスの構造)はそのまま残す。`docs/FLOW_LOGIC_SPEC.md`の
「Gate B確認後に更新すべき箇所」の式は、このJSONのキー構造をもとに確定させる。

## サニタイズ方法(Gate D)

列の内部名(`Field=`で見える`_x0020_`等のエンコードを含む文字列)は個人情報を
含まないため、そのまま記録してよい。表示名と内部名の対応表(JSON or Markdownの表)
として保存する。

## 現在の状態

| ファイル | 状態 |
| --- | --- |
| `teams_card_response_sanitized.json` | 取得済み(2026-09-01) |
| `sharepoint_internal_names.json` | `EQ_Events`・`EQ_Config_Members`は取得済み。`EQ_Responses`・`EQ_Received_Items`は未取得 |

### 列内部名の取得方法

ブラウザ(SharePointにログイン済み)で以下を開くと、表示名・内部名・型の対応が一度に得られる。

```
https://<サイトURL>/_api/web/lists/getbytitle('<リスト名>')/fields?$select=InternalName,Title,TypeAsString&$filter=Hidden eq false and ReadOnlyField eq false
```
