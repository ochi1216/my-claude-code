# NEXT_TASK.md

> このファイルは、セッション終了処理が指示されるまでは「今回（現在進行中）のセッションの作業内容」を記載する。
> 次回セッション用への切り替えは、ユーザーがセッション終了処理を明示的に指示したときにのみ行う。

## Project Name

緊急連絡ツールの開発

## Current Session

S02

## Current Session Title

緊急連絡ツールの開発 S02 - Power AutomateフローのGUI構築とGate B/D検証

## Current Objective

`power_automate_safety_checkin/` のPower Automate版PoC（P1: 手動トリガー版）について、
SharePointリストの準備を完了させ、`docs/FLOW_LOGIC_SPEC.md` の仕様通りに3フロー
（`EQ06_Manual_Drill_DEV`, `EQ04b_On_Response_DEV`, `EQ05_Status_Summary_DEV`）を
Power Automateの画面上でGUI構築し、Gate B（Teamsカードアクション）・Gate D
（SharePoint列内部名）を実測して仕様書を確定値に更新する。

## Background

S01でPower Automate版のPoC一式（SharePointデータモデル、Adaptive Card、
フローロジック仕様、自動化スクリプト）を構築済み。SharePointリスト作成は
PnP.PowerShell自動化がEntra IDアプリ登録の壁に当たったため断念し、Excel
一括アップロードによる手動作成に切替えた。4リスト分のExcelファイル
（`EQ_Config_Members`, `EQ_Received_Items`, `EQ_Events`, `EQ_Responses`）を
ユーザーへ送付済みだが、SharePointサイト
（`https://nexperia.sharepoint.com/sites/MyPrivate`、検証用）への
アップロードが完了したかは、このセッション終了時点で**未確認**。

## Scope

- SharePointへの4リストのアップロード完了確認（未完了なら先に完了させる）
- `docs/FLOW_LOGIC_SPEC.md` に従った3フローのGUI構築（DEV環境）
- `EQ06_Manual_Drill_DEV` の`CMP_Site_Config`アクションへ、大分・大阪・東京の
  拠点情報（`TeamId`/`ChannelId`は実際のTeams/チャネルが決まり次第）を設定
- Gate B（Teamsアダプティブカードアクションの正式名称、非推奨でないことの確認、
  応答トリガーの実際のJSON出力パス）の実測
- Gate D（SharePoint列内部名）の実測、`evidence/sharepoint_internal_names.json`への記録
- `docs/FLOW_LOGIC_SPEC.md` の暫定式（`triggerBody()['SiteCode']`等）を実測値に更新
- 単一ユーザー（越智さん）での手動訓練テスト

## Files That May Be Changed

- `power_automate_safety_checkin/docs/FLOW_LOGIC_SPEC.md`（Gate B/D実測値への更新）
- `power_automate_safety_checkin/docs/GATE_STATUS.md`（Gate状態の更新）
- `power_automate_safety_checkin/evidence/`（新規、実行履歴のサニタイズ済み証拠）
- `power_automate_safety_checkin/CHANGELOG.md`

## Files That Must Not Be Changed

- `po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/` など既存の他ツールフォルダ
- `HANDOVER_*.md`, `youtube_summary_list_*.py` など既存の別プロジェクト成果物
- `emergency_alert_tool/`（S01で完成・パーク済み。指示がない限り変更しない）
- リポジトリ直下の `README.md`（既存の開発ルール自体は変更しない。参照のみ）

## Task

1. SharePointへの4リストアップロード状況をユーザーに確認する。
2. 未完了なら、アップロード手順を再案内する。
3. Power Automateの画面で、`docs/FLOW_LOGIC_SPEC.md` の通りに3フローを構築する
   （実際の画面操作はユーザーが行い、Claude Codeは式・手順の提示とトラブル対応を行う）。
4. `EQ06_Manual_Drill_DEV` を1回実行し、実行履歴からGate Bの実測値を取得する。
5. SharePoint側で列の内部名を確認し、Gate Dを確定させる。
6. 実測値をもとに `docs/FLOW_LOGIC_SPEC.md` の暫定式を更新する。
7. 単一ユーザーでの手動訓練を実施し、結果を確認する。

## Completion Criteria

- SharePoint 4リストが作成され、データが投入されていること
- 3フローがDEV環境に構築されていること
- Gate B・Gate Dが実測により確定していること
- `docs/FLOW_LOGIC_SPEC.md` の式が実測値で更新されていること
- 単一ユーザーでの手動訓練が成功すること
- 既存の他ツール・他機能に意図しない影響がないこと

## Required Tests

- `EQ06_Manual_Drill_DEV` の手動実行（大分/大阪/東京、閾値未満・以上の両パターン）
- 個人カードへの回答〜上司（管理者）への即時通知の一連の流れ
- 同一イベントに対する重複防止（同じ`SiteCode`で複数回実行した場合の挙動）
- `EQ05_Status_Summary_DEV` の集計結果確認

## Known Risks

- Power AutomateのTeamsカードアクションが、ドキュメント上の想定と異なる可能性がある
  （非推奨化、UIの変更等）。Gate Bで実測するまで未確定。
- SharePoint列の内部名が表示名と一致しない場合、OData フィルタークエリの修正が必要になる。
- PnP.PowerShell/pac CLIによる自動化（`scripts/`配下）は、Entra IDアプリ登録の
  権限問題で現状使えない。IT部門の協力が得られない限り、SharePoint関連の変更・
  DEV→TEST→PROD展開は手動対応が必要。
- 社内の既存安否確認手段の有無について、正式な部門間確認がまだ行われていない
  （ユーザー＝Japan Site Managerの判断で暫定措置として進行中）。
