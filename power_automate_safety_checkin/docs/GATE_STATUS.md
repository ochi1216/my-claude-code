# Gate Status — power_automate_safety_checkin (P1: 手動トリガー版)

`docs/REVIEW_earthquake_safety_system_0730_02.md` の Gate 定義を、
P1(手動トリガー・自動地震検知なし)のスコープに合わせて再評価したもの。

| Gate | 内容 | 状態 | 備考 |
| --- | --- | --- | --- |
| A | コネクタ利用可否(RSS/SharePoint/Teamsが全てStandard) | **未確認** | P1ではRSSコネクタ自体を使わないため対象外。SharePoint/TeamsがStandard表示であることを実環境で確認する必要がある |
| B | Teams Adaptive Cardアクション(非推奨でない・応答データが取得できる) | **合格(2026-09-01実測)** | 実テナントのTeamsコネクタに「チャットやチャネルにカードを投稿する」(`PostCardToConversation`、応答を待たない)が標準コネクタとして存在し、非推奨表記もない。投げ切り型の非同期設計をそのまま採用できる。「アダプティブ カードを投稿して応答を待機する」(`PostCardAndWaitForResponse`)も併存。**残課題**: 1:1チャットへの投稿(`location: "Chat with Flow bot"`)と、EQ04bで使う応答受信トリガーの有無は未確認 |
| C | JMA Atom→XML本文取得 | **対象外(P1では不使用)** | 自動地震検知はP2として別途判断。P1は手動トリガーのみのため、このGateはP1の完成条件に含まれない |
| D | SharePoint内部名 | **実測完了(2026-09-01)** | `evidence/sharepoint_internal_names.json`に記録。**Excelアップロードで作ったリストは、内部名が表示名と一致せず`field_1`,`field_2`...という連番になる**(`Title`のみ標準列)。フローの`item/<列>`・`$filter`では内部名を使う必要がある。あわせて、型の誤検出も判明(下記) |
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

`AlertStatus`(`field_9`)と`StartedBy`(`field_10`)も同じ問題があったが、修正済み。
`EQ_Config_Members`は型の問題なし(ただし`IsActive`/`IsManager`がテキスト型のため、
フィルターは数値比較ではなく文字列比較にしている)。

## P1完成条件(Definition of Doneの再定義)

- [x] Gate B: Teamsの投げ切りカード投稿アクションが標準コネクタに存在することを実測
- [x] Gate D: SharePoint列内部名を実測(`field_N`形式であることが判明)
- [ ] EQ_Eventsの列の型を修正(上表)
- [ ] `EQ06_Manual_Drill_DEV`が閾値未満パターンで正常終了する
- [ ] `EQ06_Manual_Drill_DEV`が閾値以上パターンで最後まで走る
- [ ] 単一ユーザー(越智さん)での手動訓練が3回連続成功
- [ ] 3名結合テスト(T08〜T11: 4択それぞれの回答保存を確認)
- [ ] 18名訓練(対象者数と回答集計が一致)
- [ ] Premiumコネクタ参照が0件
- [ ] Git上に個人メール・Tenant ID・Team ID・Channel IDが含まれていない

自動地震検知(Gate C相当)は、P1完成後にP2として別途着手する。
