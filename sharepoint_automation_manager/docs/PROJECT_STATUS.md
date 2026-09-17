# PROJECT_STATUS.md

最終更新：2026-09-17（Claudeチャットセッションからの引継ぎ時点）

## 現在の状態
- フェーズ：Phase1（設計提案）改訂版 — 完了・採用
- Phase2（Architecture Audit）：進行中（6項目中4項目が確定、詳細は下記）
- Phase0（ガバナンス確認）：未実施 ★最優先の未完了事項

## 承認済み事項（Phase1改訂版の結論）
- データ取得方式：Microsoft Graph APIの `workbook/usedRange`（または
  `range`）APIを使用し、Excelアプリを一切開かずにセル値を直接取得する
- 実行基盤：GitHub Actionsのスケジュールワークフロー（cron）を軸とする
  （Windows Task Scheduler・Power Automateは不採用。Azure Functionsとの
  比較はPhase2で実施済み、コスト差は実質ゼロ・保守性でGitHub Actionsが
  優位のため継続採用。ADR-002維持）
- スコープ：Caracalシート1件・木金17:00±30分の定点取得＋Outlook通知に
  限定したMVP構成（汎用エンジン化はPMレビューを受けて延期）
- ガバナンス：IT/セキュリティ部門への事前確認をPhase3実装前の必須ゲート
  （Phase0）とする
- 認証方式：既存ツール（r19_site_organizer／onenote_report_generator）と
  同じMSAL Device Code Flow・委任(Delegated)権限を流用する。初回サイン
  インのみ人手、以降はトークンキャッシュのGitHub Actions Secrets保管＋
  silent refreshで無人運用する（ADR-008）
- 実行タイミングの許容幅：GitHub Actions cronの構造的な遅延を踏まえ、
  「17:00〜17:30の間に届けば正常」と定義する（ADR-009）
- KPI：3指標併用（効率化／信頼性／応答性、数値目標はADR-010参照）

## 未解決・要確認事項
1. IT/セキュリティへのApp登録スコープ（Sites.Read.All／Mail.Send、委任）
   の確認・承認取得（未着手、NEXT_TASK.md参照。スコープ自体は既存承認済み
   ツールと同一だが、GitHub Actions Secretsに有効なリフレッシュトークンを
   保管する点は新規リスクとして明示が必要）
2. **Azure AD Conditional Accessポリシーの適用有無**（GitHub Actions
   実行環境＝社外IPからのアクセスがブロックされないか、および
   sign-in frequency等の再認証ポリシーがsilent refreshを阻害しないかの
   確認。Phase0に含める、未確認）
3. Caracalシートの具体的なセルレンジ・データ構造の特定（未着手、越智さん
   が実データを直接確認する必要あり）
4. 障害検知時の通知先・エスカレーションルールの具体的な文面（設計方針は
   確定済み：API失敗のリトライ＋最終失敗通知、シート構造変更検知、
   「17:30までに成功通知が来なければ異常」という受信側の見張り。文面・
   エスカレーション先はPhase3設計時に確定）

## 解決済み（Phase2）
- KPI数値目標（ADR-010）
- GitHub Actions vs Azure Functions比較（コスト差ほぼ無し、GitHub Actions継続）
- 既存MSAL実装の再利用方針（ADR-008）
- cron実行タイミングの許容幅（ADR-009）

## 関連する既存資産
- SharePoint Portal（R19_site_organizer）：Graph API + MSAL Device Code Flow
- OneNote Report Generator：Graph API、青文字検出＋Gemini要約
- 対象ファイル：Power_MAG_2026_KPI_Standup_Checklists-Rev0.9-09-11-26.xlsx
  （SharePoint上、Caracalシート）

---
文書オーナー：越智さん（Nexperia Japan Site Manager）
最終更新：2026-09-17
次回更新予定：Phase2着手時
