# Gate Status — power_automate_safety_checkin (P1: 手動トリガー版)

`docs/REVIEW_earthquake_safety_system_0730_02.md` の Gate 定義を、
P1(手動トリガー・自動地震検知なし)のスコープに合わせて再評価したもの。

| Gate | 内容 | 状態 | 備考 |
| --- | --- | --- | --- |
| A | コネクタ利用可否(RSS/SharePoint/Teamsが全てStandard) | **未確認** | P1ではRSSコネクタ自体を使わないため対象外。SharePoint/TeamsがStandard表示であることを実環境で確認する必要がある |
| B | Teams Adaptive Cardアクション(非推奨でない・応答データが取得できる) | **未確認・要検証** | 「投稿して応答を待つ」は1:1では非推奨の見込み。本設計は非同期(投げ切り+応答トリガー)を採用しており、`docs/MANUAL_STEPS.md`§5で1回だけ実測する |
| C | JMA Atom→XML本文取得 | **対象外(P1では不使用)** | 自動地震検知はP2として別途判断。P1は手動トリガーのみのため、このGateはP1の完成条件に含まれない |
| D | SharePoint内部名 | **スクリプトで対応** | `scripts/provision_sharepoint.ps1`が列を作成し、実行後に内部名を出力する。実行後に本ファイルを更新すること |
| E | 共同所有・接続継続 | **未確認** | Solutionの共同所有者設定、接続参照の再認証手順は`docs/MANUAL_STEPS.md`のTEST/PROD展開時に確認する |

## P1完成条件(Definition of Doneの再定義)

- [ ] Gate B: 実行履歴からTeamsアクション名・応答JSONパスを実測済み
- [ ] Gate D: SharePoint列内部名を実測し、`docs/FLOW_LOGIC_SPEC.md`の暫定式を確定済みに更新
- [ ] 単一ユーザー(越智さん)での手動訓練が3回連続成功
- [ ] 3名結合テスト(T08〜T11: 4択それぞれの回答保存を確認)
- [ ] 18名訓練(対象者数と回答集計が一致)
- [ ] Premiumコネクタ参照が0件
- [ ] Git上に個人メール・Tenant ID・Team ID・Channel IDが含まれていない

自動地震検知(Gate C相当)は、P1完成後にP2として別途着手する。
