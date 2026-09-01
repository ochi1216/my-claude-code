# NEXT_TASK.md

> このファイルは、セッション終了処理が指示されるまでは「今回（現在進行中）のセッションの作業内容」を記載する。
> 次回セッション用への切り替えは、ユーザーがセッション終了処理を明示的に指示したときにのみ行う。

## Project Name

緊急連絡ツールの開発

## Current Session

S03

## Current Session Title

緊急連絡ツールの開発 S03 - エラー処理・イベントクローズの実装と実拠点での訓練

## Current Objective

S02でDEV環境に構築・検証した`EQ06_Manual_Drill_DEV`・`EQ05_Status_Summary_DEV`に、
運用に必要な2つの機能（エラー処理、イベントのクローズ）を追加し、検証用の設定を
本番向けに切り替えたうえで、実在拠点での小規模訓練を実施する。

## Background

S02でP1のフロー実装は完了し、DEV環境で以下を実機確認済み。

- 閾値未満／以上の両パターン、イベント記録、チャネル通知、個人カードの送信と回答待機、
  回答の`EQ_Responses`への保存、被災回答時の上司通知、未回答（タイムアウト）時の正常終了
- `EQ05`による集計カードの投稿

フローはGUIで組むのではなく、`solution/build_flows_20260901_01.py`が生成したJSONを
`pac solution pack`→`import`で流し込む方式になっている（3コマンドで再展開できる）。
実測で確定した仕様・本番切替チェックリストは`power_automate_safety_checkin/solution/README.md`
に、Gate B/Dの実測値は`power_automate_safety_checkin/evidence/`にある。

現在は検証段階の安全弁が有効になっており、`deploy_config.json`の
`testRecipientOverride`が設定されている間は、拠点や`IsTest`の値にかかわらず
個人カード・上司通知の宛先が検証者だけに向く。

## Scope

- エラー処理（`SCOPE_Try`/`SCOPE_Catch`→`EQ_Received_Items`へのログ記録）の実装
- イベントのクローズ処理（全員回答またはタイムアウト後に`AlertStatus`を`Closed`へ）の実装
- `EQ_Received_Items`の列内部名の実測と`evidence/`への記録
- 拠点ごとの実Team/Channel IDの設定
- 検証用設定の解除（`testRecipientOverride`を空に、架空拠点`NARA`と検証用メンバーの削除）
- 実在拠点での小規模訓練（まず3名程度）、その後18名訓練

## Files That May Be Changed

- `power_automate_safety_checkin/solution/build_flows_*.py`（新リビジョンを作成）
- `power_automate_safety_checkin/solution/deploy_config.example.json`
- `power_automate_safety_checkin/solution/README.md`
- `power_automate_safety_checkin/evidence/`
- `power_automate_safety_checkin/cards/`
- `power_automate_safety_checkin/docs/FLOW_LOGIC_SPEC.md`, `docs/GATE_STATUS.md`
- `power_automate_safety_checkin/CHANGELOG.md`

## Files That Must Not Be Changed

- `po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/` など既存の他ツールフォルダ
- `HANDOVER_*.md`, `youtube_summary_list_*.py` など既存の別プロジェクト成果物
- `emergency_alert_tool/`（S01で完成・パーク済み。指示がない限り変更しない）
- リポジトリ直下の `README.md`

## Task

1. `EQ_Received_Items`の列内部名を実測し、`evidence/sharepoint_internal_names.json`へ追記する。
2. エラー処理を実装する。フロー全体を`SCOPE_Try`で包み、失敗時に`SCOPE_Catch`で
   `EQ_Received_Items`へ`ProcessingStatus=Error`とエラー内容を記録する。
3. イベントのクローズ処理を実装する。`LOOP_Each_Member`の完了後に`EQ_Events`の
   `AlertStatus`を`Closed`へ更新する（SharePointの更新アクションの`operationId`は未実測のため、
   最小フローで実測してから使う）。
4. 拠点ごとの実Team/Channel IDを取得し、`deploy_config.json`へ設定する。
5. 検証用設定を解除する（`testRecipientOverride`を空に、`sites`から`NARA`を削除、
   `EQ_Config_Members`から`emp98`/`emp99`を削除）。この時点から実名簿へ実際に届くため、
   **解除前に必ずユーザーの明示的な確認を取る**。
6. 実在拠点で3名程度の小規模訓練を実施し、回答〜集計〜上司通知までを確認する。
7. 問題がなければ18名訓練を実施する。

## Completion Criteria

- エラー処理が実装され、意図的に失敗させたときに`EQ_Received_Items`へ記録されること
- イベントが訓練終了後に`Closed`になり、`EQ05`が古いイベントを集計し続けないこと
- 拠点ごとの実チャネルへ通知が飛ぶこと
- 実在拠点での3名訓練が成功すること
- 18名訓練で、対象者数と回答集計が一致すること
- 既存の他ツール・他機能に意図しない影響がないこと

## Required Tests

- エラー処理: 存在しないリストGUIDを指定する等で意図的に失敗させ、`EQ_Received_Items`への
  記録を確認
- クローズ処理: 訓練終了後に`EQ_Events`の`AlertStatus`が`Closed`になっていること、
  その後`EQ05`を実行しても当該イベントが集計されないこと
- 実在拠点での3名訓練（4択それぞれの回答保存、被災時の上司通知）
- 18名訓練（対象者数と回答集計の一致、未回答者の可視化）

## Known Risks

- **本番切替後は実在の社員へ実際にカードが届く。** `testRecipientOverride`を空にする
  操作は、実施前に必ずユーザーの明示的な確認を取ること。S02では、この安全弁が
  無い状態でのテストにより実在の同僚2名へ訓練カードが誤送信された事故が起きている。
- SharePointの「項目の更新」アクションの`operationId`・パラメータ形式は未実測。
  推測で書くとインポート後に検証エラーになるため、最小フローで実測してから使う。
- `EQ05`をオンにすると15分ごとに動く。`Open`のイベントが残っているとその都度
  チャネルへ投稿されるため、クローズ処理の実装前に長時間オンにしない。
- 18名が同時に待機する状態では、`loopConcurrency`（既定20）とPower Automateの
  同時実行上限（50）に注意する。
- 自動地震検知（EQ01/EQ02、Gate C）はP2として引き続きスコープ外。

## 開始プロンプト（次セッション用）

```
緊急連絡ツールの開発 S03 - エラー処理・イベントクローズの実装と実拠点での訓練

対象リポジトリ: ochi1216/my-claude-code
対象ブランチ: claude/power-automate-flow-gui-gates-sulkdg
前回のコミットID: (S02最終コミットのID)

作業開始前に、必ずGitHubの最新状態を取得してください。

## 現在の状態
S02で、Power Automate版P1のフロー2本（EQ06_Manual_Drill_DEV、EQ05_Status_Summary_DEV）を
DEV環境に構築し、実機で動作確認済み。フローはGUIではなく
power_automate_safety_checkin/solution/build_flows_20260901_01.py が生成したJSONを
pac solution pack → import で流し込む方式。Gate B・Gate Dは実測完了し
evidence/ に記録済み。現在は testRecipientOverride による誤送信防止が有効で、
個人カード・上司通知はすべて検証者だけに届く状態。

## 次に行う作業
1. EQ_Received_Items の列内部名を実測する
2. エラー処理（SCOPE_Try/Catch → EQ_Received_Items へのログ記録）を実装する
3. イベントのクローズ処理（AlertStatus を Closed へ更新）を実装する
   ※SharePointの更新アクションのoperationIdは未実測。最小フローで実測してから使う
4. 拠点ごとの実Team/Channel IDを設定する
5. 検証用設定を解除する（実施前に必ずユーザーの明示的な確認を取ること）
6. 実在拠点での3名訓練、その後18名訓練を実施する

詳細は docs/NEXT_TASK.md を参照。

未確認の事項は推測せず、必ず「未確認」と報告してください。
```
