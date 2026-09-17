# SESSION_HISTORY.md（ADR形式による意思決定履歴）

## ADR-001: Excelデータ取得方式をGraph API直結に決定
- 日付：2026-09-17
- 状況：SharePoint上のExcelシートを定期的に読み取る必要がある
- 決定：Excelアプリを開かず、Microsoft Graph APIのworkbook/usedRange
  （またはrange）APIで直接セル値を取得する
- 却下した代替案：Excel COM自動化（GUI操作依存、会社PCでの安定性に懸念）、
  Power Automateの表内操作（GUI設定への依存度が高い）
- 理由：GUI操作を完全排除でき、既存のGraph API知見（SharePoint Portal,
  OneNote Report Generator）を流用可能

## ADR-002: 実行基盤をGitHub Actionsのスケジュールワークフローに決定
- 日付：2026-09-17
- 状況：定期実行の仕組みが必要。GUI操作を避け、即座に修正できる自由度が
  求められている
- 決定：GitHub Actionsのcronトリガーを軸とする
- 却下した代替案：Windows Task Scheduler（GUI設定依存、PC起動状態に依存）、
  Power Automate（ビジネスユーザー向けでGUI操作中心）、Azure Functions/
  Automation（Phase2で再比較予定、初期構築コストがやや高い）
- 理由：既存のGit運用実績（ochi1216/my-claude-code）と親和性が高く、
  yml編集のみでスケジュール変更が完結する

## ADR-003: 汎用タスクエンジン化をPhase4以降に延期（PMレビュー反映）
- 日付：2026-09-17
- 状況：当初案はYAML駆動の汎用タスクエンジンを最初から設計する方針だった
- PM指摘：実利用実績ゼロの段階での抽象化は過剰設計（YAGNI違反）のリスクが
  高い
- 決定：MVP（Caracal 1件限定）を先行させ、効果確認後に汎用化する二段階
  ロードマップに変更
- 理由：小さく作って検証し、価値が確認できてから拡張する方がリスクが低い

## ADR-004: MVPスコープをCaracalシート1件・木金17:00に限定（PMレビュー反映）
- 日付：2026-09-17
- 決定：他KPIシート・他プロジェクトへの適用は本MVP範囲外とする
- 理由：スコープを絞ることで、効果測定・障害対応・引継ぎのしやすさを
  確保する

## ADR-005: ガバナンス確認をPhase0として前提条件化（PMレビュー反映）
- 日付：2026-09-17
- PM指摘：個人GitHub PATから会社SharePoint/Outlookへ自動アクセスする
  構成は、IT/セキュリティ承認なしでは「シャドーIT」化するリスクがある
- 決定：IT/セキュリティ部門への事前確認・承認取得をPhase3（実装）着手の
  必須ゲートとする
- 状態：未実施（NEXT_TASK.md参照）

## ADR-006: KPIと障害検知をMVP必須要件に格上げ（PMレビュー反映）
- 日付：2026-09-17
- PM指摘：「動く」だけでなく「効果測定できる」「壊れたら分かる」構成が
  必要
- 決定：最低1つの定量指標の設定、およびAPI失敗・シート構造変更・実行
  失敗の検知＋通知の仕組みをMVPスコープに含める
- 状態：指標の具体的数値・通知フローの詳細はPhase2で確定予定

## ADR-007: Conditional Accessリスクを引継ぎ資料レビューで追加特定
- 日付：2026-09-17
- 状況：引継ぎ資料のPMレビュー（1巡目）にて、GitHub Actions（社外IP）
  からgraph.microsoft.comへアクセスする構成が、Azure ADのConditional
  Accessポリシー（IP制限・デバイス準拠要件等）に抵触する可能性が未検討
  であることが判明
- 決定：Phase0の受け入れ基準にConditional Access確認を追加し、
  CLAUDE.md／PROJECT_STATUS.md／NEXT_TASK.mdの該当箇所を修正
- 状態：反映済み（本引継ぎ資料はこの指摘を反映したバージョン）

---
文書オーナー：越智さん（Nexperia Japan Site Manager）
最終更新：2026-09-17
次回更新予定：Phase2の議論内容をADR-008以降として追記
