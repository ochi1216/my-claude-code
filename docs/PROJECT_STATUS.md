# PROJECT_STATUS.md

最終更新: 2026-09-01 (S02)

## Project Overview

- プロジェクト名: 緊急連絡ツールの開発
- 目的: 緊急地震速報（大分県・大阪府・東京都、震度5弱以上）を検知した際に、
  緊急連絡網のスタッフへ安否確認を送信し、各スタッフが
  「無事/被災」「出社可能/出社不可能」を回答すると、即座に上司（管理者）へ
  通知される仕組みを構築する。
- 位置づけ: Nexperia B.V. 日本支社には現在、緊急連絡網が存在しない。本仕組みは
  会社が有料安否確認サービスを承認・契約するまでの**暫定措置**であり、
  将来は補助的な位置づけに変わる想定。
- スコープ: 日本支社40名（開発部門18名＋ビジネスデベロップメント部門22名）のうち、
  まず開発部門18名を対象としたPoCとして開始する。
- 前提環境: Microsoft 365。

## 採用アプローチの経緯（重要）

S01セッション内で、実装方式を1回転換している。

1. **前半: Python + Microsoft Graph API版**（`emergency_alert_tool/`）を実装。
   ロジック・Webフォーム・通知処理は完成し自動テストも全件合格したが、
   実際にメールを送るには Azure ADアプリ登録＋`Mail.Send`（アプリケーション権限）への
   **管理者同意**が必要と判明。ユーザー（Japan Site Manager）個人の権限では
   完結せず、IT部門への依頼が前提になることが分かった。
2. **後半: Power Automate版**（`power_automate_safety_checkin/`）に転換。
   標準コネクタ（SharePoint・Teams）のみで構成すればIT部門への申請なしで
   構築できるため。ユーザーからGPT側で作成されたPower Automate構想書
   （`Earthquake_Safety_System_0730_02`）が提示され、これを精査
   （`docs/REVIEW_earthquake_safety_system_0730_02.md`）した上で、
   指摘事項を反映したPoC（P1: 手動トリガー版）を新規に構築した。

現時点の主軸は**Power Automate版**。Python版はプロトタイプとして完成・動作確認済み
（dry-runモードでの一連の流れは実機確認済み）だが、実際のメール送信は
Azure AD側の制約で止まっている（IT部門への依頼文は作成済み、未送付）。

## Repository Structure

`my-claude-code` は複数の独立した社内向けツールを `ツール名/` フォルダ単位で
管理するモノレポ。

```
my-claude-code/
├── CLAUDE.md                  # セッション/開発運用ルール（S01で新規作成）
├── README.md                  # リポジトリ全体の開発ルール（バージョン管理規約）
├── docs/                      # プロジェクト管理ファイル（S01で新規作成）
│   ├── PROJECT_STATUS.md
│   ├── SESSION_HISTORY.md
│   ├── NEXT_TASK.md
│   └── REVIEW_earthquake_safety_system_0730_02.md  # Power Automate構想の精査レポート
├── emergency_alert_tool/      # Python + Graph API版（S01前半、現在は非主軸）
├── power_automate_safety_checkin/  # Power Automate版（S01後半、現在の主軸）
├── po_database_organizer/     # 既存ツール（他プロジェクト、本作業では変更しない）
├── rtocs_organizer/           # 既存ツール（他プロジェクト、本作業では変更しない）
├── shareflex_dashboard/       # 既存ツール（他プロジェクト、本作業では変更しない）
├── HANDOVER_analog_ic_scout.md      # 既存の別プロジェクト引継ぎ資料
├── HANDOVER_youtube_summary_list.md # 既存の別プロジェクト引継ぎ資料
└── youtube_summary_list_*.py         # 既存の別プロジェクト成果物
```

既存フォルダ（`po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/` 等）は
本プロジェクトとは無関係の別ツールであり、本プロジェクトでは変更しない。

## Current Functions

- `emergency_alert_tool/`: 詳細は同フォルダの `README.md` / `CHANGELOG.md` を参照。
- `power_automate_safety_checkin/`: 詳細は同フォルダの `README.md` / `CHANGELOG.md` を参照。

## Confirmed Specifications（Power Automate版・現行）

- 監視対象拠点: 大分県・大阪府・東京都、閾値: 震度5弱以上
- 拠点情報（拠点名・閾値・TeamId・ChannelId）は**SharePointリストではなく、
  Power Automateフロー内のSwitchアクション（`CMP_Site_Config`）に固定値として保持**する
  （SharePointの全員閲覧可能なリストに置く必要がないとの判断、ユーザー指示による）。
- スタッフ・管理者の名簿はSharePointリスト`EQ_Config_Members`で管理する。
  管理者役のID命名は `mgr01`, `mgr02`, `admin01`（旧`boss01/02/03`から変更）。
- スタッフの回答項目: 4択（①無事・出社可能／②無事・出社不可／③被災・出社可能／④被災・出社不可）
- 回答が送信されたら、即座に管理者（`mgr01`/`mgr02`/`admin01`）へ通知する。
- アーキテクチャは**待機型＋並列ループ**（S02で変更）。当初は「カード投げ切り＋
  応答トリガー分離」の非同期設計だったが、**このテナントのTeamsコネクタには
  アダプティブカードの応答を受け取るトリガーが存在しない**ことがS02で判明したため、
  `PostCardAndWaitForResponse`（応答を待機するアクション）を`Apply to each`の中で使い、
  ループを並列実行して全員分を同時に待つ方式に変更した。直列ループを避ける
  という当初の要件（1人目の回答まで他メンバーへの送信が止まってはいけない）は
  並列実行で満たしている。
- フローの構築方法は、Power AutomateのGUIでの手組みではなく、**フロー定義（JSON）を
  スクリプトで生成し`pac` CLIでインポートする方式**（S02で変更）。
- 自動地震検知（気象庁XML自動取込）はスコープ外（Gate C不合格見込み）。
  P1は手動トリガーのみ。

## Current Status

- **Power Automate版（主軸）**: **P1のフロー実装は完了し、DEV環境で実機検証済み**（S02）。
  - SharePoint 4リストは作成済み・データ投入済み（開発部門の実名簿19名＋検証用2名）。
  - `EQ06_Manual_Drill_DEV`（手動訓練）と`EQ05_Status_Summary_DEV`（定期集計）の
    2フローがDEV環境で動作している。当初設計の`EQ04b_On_Response_DEV`は、
    応答トリガーが存在しないためEQ06へ統合し廃止した。
  - 検証済みの動作: 閾値判定（未満は正常終了）／`EQ_Events`へのイベント記録／
    Teamsチャネルへの開始通知カード／対象者の抽出／個人カードの送信と回答待機／
    `EQ_Responses`への回答保存／被災回答時の上司通知／未回答（タイムアウト）時の
    正常終了／`EQ05`による集計カードの投稿。
  - フローは`solution/build_flows_*.py`で生成し、`pac solution pack`→`import`の
    3コマンドで再展開できる。GUI操作は接続の作成と動作確認のみ。
- **検証段階の安全弁**: `deploy_config.json`の`testRecipientOverride`が設定されている間、
  個人カード・上司通知の宛先は名簿の内容にかかわらず検証者だけに向く。
  実在拠点の名簿に触れずに試せるよう、架空拠点`NARA`（検証者1名のみ所属）も用意した。
  本番移行時は`testRecipientOverride`を空にする（それが唯一の切替操作）。
- **Python版（非主軸）**: `emergency_alert_tool/` は実装・自動テスト（21件）ともに完了。
  Windows実機でのdry-run動作確認（トリガー→18名通知→回答→上司通知の一連の流れ）も
  完了。実際のM365テナントへのメール送信はAzure AD管理者同意待ちで未検証。

## Known Issues

- **エラー処理（`SCOPE_Try`/`SCOPE_Catch`による`EQ_Received_Items`へのログ記録）が未実装。**
  `EQ_Received_Items`の列内部名も未取得。
- **イベントのクローズ処理が未実装。** `AlertStatus`は`Open`のまま更新されないため、
  EQ05が古いイベントを集計し続ける。
- `TeamId`/`ChannelId`は、検証中のため3拠点＋NARAとも同一のテスト用チャネルを指している。
  拠点ごとの実チャネルは未設定。
- 実在拠点（大分・大阪・東京）での訓練、3名結合テスト、18名訓練はいずれも未実施。
- S02の実機テストで、**実在の同僚2名（東京拠点）へ訓練用の安否確認カードが誤送信された。**
  以後は`testRecipientOverride`により再発しない仕組みにしてあるが、当該2名への
  フォローが必要かはユーザー判断。
- Python版は、Azure ADの`Mail.Send`アプリケーション権限への管理者同意が
  得られていないため、実メール送信は未検証（IT部門への依頼文は作成済み、未送付）。
- 既存の安否確認サービスの有無について、社内所管部門への確認はまだ行っていない
  （ユーザー＝Japan Site Managerが暫定措置と位置づけ済みだが、正式な社内合意の
  記録は未確認）。

## Test and Execution

- `emergency_alert_tool/`: `pytest tests/ -v` で21件全てPASS。実機（Windows、
  dry_runモード）でのE2E確認済み。詳細は同フォルダの`README.md`参照。
- `power_automate_safety_checkin/`: DEV環境（`Nexperia (default)`）で
  `EQ06_Manual_Drill_DEV`・`EQ05_Status_Summary_DEV`の実機動作を確認済み。
  実測値は`evidence/`（Teamsカード応答の構造、SharePoint列内部名・型）に記録。
  再展開の手順は`solution/README.md`を参照。

## Important Restrictions

- 既存の他ツールフォルダ（`po_database_organizer/` 等）は変更しない。
- APIキー・パスワード・クライアントシークレット等の認証情報はコミットしない。
- コミット・Pushはユーザーが明示的に指示した場合のみ行う。
- Power Automateのフロー本体・SharePointの実データ投入など、GUI操作や
  実テナントへの実行が必要な作業はユーザー自身が行う（Claude Codeはこのセッション
  環境から対象テナントへ直接操作できない）。
