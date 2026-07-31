# PROJECT_STATUS.md

最終更新: 2026-07-31 (S01)

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
- アーキテクチャは非同期（カード投げ切り＋応答トリガー分離）。直列ループでの
  応答待ちは1人目の回答まで他メンバーへの送信が止まるため不採用。
- 自動地震検知（気象庁XML自動取込）はスコープ外（Gate C不合格見込み）。
  P1は手動トリガーのみ。

## Current Status

- **Power Automate版（主軸）**: SharePointリスト設計・Flowロジック仕様・Adaptive Card・
  PowerShell自動化スクリプトまで作成済み。SharePoint（サンドボックスサイト
  `https://nexperia.sharepoint.com/sites/MyPrivate`）へのリスト作成は、
  PnP.PowerShellでの完全自動化を試みたが、Entra IDアプリ登録に管理者権限が必要と
  判明したため断念し、**Excel一括アップロードによる手動作成**に切替えた。
  4リスト分（`EQ_Config_Members`, `EQ_Received_Items`, `EQ_Events`, `EQ_Responses`）の
  Excelファイルは作成・送付済みだが、**ユーザーによるSharePointへのアップロードは未完了**
  （このセッション終了時点で未確認）。
  Power Automate上でのフロー本体（3フロー）の構築は**未着手**。
- **Python版（非主軸）**: `emergency_alert_tool/` は実装・自動テスト（21件）ともに完了。
  Windows実機でのdry-run動作確認（トリガー→18名通知→回答→上司通知の一連の流れ）も
  完了。実際のM365テナントへのメール送信はAzure AD管理者同意待ちで未検証。

## Known Issues

- Power Automate版のGate B（Teamsアダプティブカードアクションの正式名称・応答JSON構造）は
  未実測。実際にフローを構築し1回実行するまで確定しない。
- Gate D（SharePoint列内部名）も、リスト作成後の実測が必要。
- `EQ_Config_Sites`相当の`TeamId`/`ChannelId`（拠点ごとの通知先）は、実際のTeams/
  チャネルが決まるまでプレースホルダのまま。
- Python版は、Azure ADの`Mail.Send`アプリケーション権限への管理者同意が
  得られていないため、実メール送信は未検証（IT部門への依頼文は作成済み、未送付）。
- 既存の安否確認サービスの有無について、社内所管部門への確認はまだ行っていない
  （ユーザー＝Japan Site Managerが暫定措置と位置づけ済みだが、正式な社内合意の
  記録は未確認）。

## Test and Execution

- `emergency_alert_tool/`: `pytest tests/ -v` で21件全てPASS。実機（Windows、
  dry_runモード）でのE2E確認済み。詳細は同フォルダの`README.md`参照。
- `power_automate_safety_checkin/`: PowerShellスクリプトはAST構文検証のみ実施
  （実テナントに対する実行は未検証）。JSON（Adaptive Card・config）は構文検証済み。
  Power Automateフロー自体はまだ未構築のため、フローの動作テストは未実施。

## Important Restrictions

- 既存の他ツールフォルダ（`po_database_organizer/` 等）は変更しない。
- APIキー・パスワード・クライアントシークレット等の認証情報はコミットしない。
- コミット・Pushはユーザーが明示的に指示した場合のみ行う。
- Power Automateのフロー本体・SharePointの実データ投入など、GUI操作や
  実テナントへの実行が必要な作業はユーザー自身が行う（Claude Codeはこのセッション
  環境から対象テナントへ直接操作できない）。
