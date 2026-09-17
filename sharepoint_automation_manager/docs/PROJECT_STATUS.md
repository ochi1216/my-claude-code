# PROJECT_STATUS.md

最終更新：2026-09-17（Claudeチャットセッションからの引継ぎ時点）

## 現在の状態
- フェーズ：Phase1（設計提案）改訂版 — 完了・採用
- Phase2（Architecture Audit）：未着手
- Phase0（ガバナンス確認）：未実施 ★最優先の未完了事項

## 承認済み事項（Phase1改訂版の結論）
- データ取得方式：Microsoft Graph APIの `workbook/usedRange`（または
  `range`）APIを使用し、Excelアプリを一切開かずにセル値を直接取得する
- 実行基盤：GitHub Actionsのスケジュールワークフロー（cron）を軸とする
  （Windows Task Scheduler・Power Automateは不採用、Azure Functionsは
  Phase2で再比較）
- スコープ：Caracalシート1件・木金17:00の定点取得＋Outlook通知に限定
  したMVP構成（汎用エンジン化はPMレビューを受けて延期）
- ガバナンス：IT/セキュリティ部門への事前確認をPhase3実装前の必須ゲート
  （Phase0）とする

## 未解決・要確認事項
1. IT/セキュリティへのApp登録スコープ（Sites.Read.All等）の確認・承認
   取得（未着手、NEXT_TASK.md参照）
2. **Azure AD Conditional Accessポリシーの適用有無**（GitHub Actions
   実行環境＝社外IPからのアクセスがブロックされないかの確認。Phase0に
   含める、未確認）
3. Caracalシートの具体的なセルレンジ・データ構造の特定（未着手、シート
   を直接確認する必要あり）
4. KPI（効果測定指標）の具体的な数値目標（候補は提示済み、確定値は未定）
5. GitHub Actions vs Azure Functionsの詳細コスト・保守性比較（Phase2で
   実施予定）
6. 障害検知時の通知先・エスカレーションルールの具体的な文面・条件
   （設計方針のみ確定、詳細は未定）

## 関連する既存資産
- SharePoint Portal（R19_site_organizer）：Graph API + MSAL Device Code Flow
- OneNote Report Generator：Graph API、青文字検出＋Gemini要約
- 対象ファイル：Power_MAG_2026_KPI_Standup_Checklists-Rev0.9-09-11-26.xlsx
  （SharePoint上、Caracalシート）

---
文書オーナー：越智さん（Nexperia Japan Site Manager）
最終更新：2026-09-17
次回更新予定：Phase2着手時
