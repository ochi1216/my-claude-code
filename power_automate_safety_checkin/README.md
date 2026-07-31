# 地震安否確認システム — Power Automate版(PoC)

大分県・大阪府・東京都のいずれかで震度5弱以上の地震が発生した際に、緊急連絡網の
スタッフへ安否確認を送り、「安否(無事/被災)」「出社可否」を回答してもらい、
被災者があれば上司へ即座に通知する仕組みを、**Microsoft 365標準機能(Power Automate,
SharePoint, Microsoft Teams)のみ**で構築するもの。

## 位置づけ

- Nexperia B.V. 日本支社には現在、緊急連絡網が存在しない。本ツールはその空白を埋める
  **暫定措置**であり、会社が有料安否確認サービスを承認・契約するまでの間の運用を想定する。
- 対象は日本支社40名(開発部門18名＋ビジネスデベロップメント部門22名)のうち、
  まずは開発部門18名を対象とした**PoC**として開始する。
- 将来、有料サービスが導入された場合、本ツールは正規手段ではなく補助に位置づけを変える。

## なぜPower Automateか

同種の仕組みをPython + Microsoft Graph API(アプリケーション権限)で先行実装したが、
Azure ADアプリ登録・`Mail.Send`権限への管理者同意が必要であり、個人の権限では完結しない
ことが判明した(詳細は `docs/REVIEW_earthquake_safety_system_0730_02.md` 参照)。

Power Automateの標準コネクタ(SharePoint・Teams)のみで構成すれば、IT部門への
追加ライセンス申請や管理者同意なしに、ユーザー自身の権限内で構築できる。

## このフォルダの方針: 自動化ファースト

Power AutomateのGUI操作は煩雑になりがちなため、以下を徹底している。

| 作業 | 従来 | このプロジェクト |
| --- | --- | --- |
| SharePointリスト・列の作成 | 画面で1つずつクリック | `scripts/provision_sharepoint_*.ps1（最新版）` で自動生成 |
| 拠点・メンバーデータの投入 | 画面で1行ずつ手入力 | `config/*.json` から一括投入 |
| フローの条件式・変換式 | 画面で都度考えて入力 | `docs/FLOW_LOGIC_SPEC.md` にコピペ用の式を明記 |
| Adaptive Card | カードデザイナーで組み立て | `cards/*.json` を直接貼り付け |
| DEV→TEST→PROD展開 | 環境ごとに手作業で再構築 | `scripts/deploy_solution_*.ps1（最新版）` (pac CLI) で一発展開 |

削減できない最小限の手作業(接続認証・フロー本体の初回構築1回)は
`docs/MANUAL_STEPS.md` に明記している。

## ファイル構成

```
power_automate_safety_checkin/
├── config/
│   ├── sites.json              # 拠点(大分・大阪・東京)の定義。SharePointには置かず、
│   │                            # Power AutomateのCMP_Site_Configアクションを作る際の値の元ネタとして使う
│   └── members.example.json    # スタッフ18名+マネージャー2名+管理者1名のプレースホルダ
├── cards/
│   ├── channel_alert_card.json # チャネルへの開始通知カード(非対話)
│   └── checkin_card.json       # 個人への安否確認カード(回答用)
├── scripts/
│   ├── provision_sharepoint_yyyymmdd_NN.ps1 # SharePoint 4リスト自動作成+メンバー投入(最新版のみ残す)
│   └── deploy_solution_yyyymmdd_NN.ps1      # pac CLIによるSolution展開(最新版のみ残す)
├── solution/                    # pac CLIでunpackしたフロー定義(初回構築後に生成)
└── docs/
    ├── FLOW_LOGIC_SPEC.md        # フローのアクション順序・式(コピペ用)
    ├── MANUAL_STEPS.md           # 削減できない手作業チェックリスト
    ├── GATE_STATUS.md            # 実現可能性ゲートの状態
    └── REVIEW_*.md (リポジトリdocs/) # 前提となった構想の精査レポート
```

## セットアップ手順(概要)

詳細は `docs/MANUAL_STEPS.md` を参照。おおまかな流れ:

1. `pac` CLIと`PnP.PowerShell`をインストール
2. `scripts/provision_sharepoint_*.ps1（最新版）` を実行し、SharePointリストを構築
3. `config/members.example.json` を実際のメンバー情報で複製した
   `config/members.json`(コミットしない)を作成し、再度スクリプトを実行してデータ投入
4. `docs/FLOW_LOGIC_SPEC.md` の通りにDEV環境で3フローを1回だけ構築
5. Gate B(Teamsアクションの実挙動)を1回検証
6. `scripts/deploy_solution_*.ps1（最新版）` でTEST/PRODへ展開

## スコープ(P1: このPoCで作るもの)

- 手動トリガーによる安否確認の起動(`EQ06_Manual_Drill`)
- 個人ごとの安否確認カード送信・回答受付・SharePoint保存
- 被災者があれば上司へ即時通知
- 未回答者・被災者の定期集計

自動地震検知(気象庁XMLの自動取込)は、標準コネクタのみでは実現できない見込みが
高いため(Gate C、レビュー参照)、このPoCには含めない。P1の運用開始後、
別途P2として判断する。

## 関連ドキュメント

- `docs/REVIEW_earthquake_safety_system_0730_02.md`(リポジトリ直下の`docs/`) —
  当初のPower Automate構想(GPT設計)に対する精査レポート。判定ロジックの欠陥、
  Gate Cの見立て、非同期アーキテクチャへの修正提案を含む。
