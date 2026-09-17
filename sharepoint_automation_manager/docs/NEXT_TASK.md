# NEXT_TASK.md

## 最優先タスク（Phase0：ガバナンス確認）
1. IT/セキュリティ部門へ、App登録スコープ・シークレット保管方式について
   事前相談を行う

**Phase0の受け入れ基準（この3点が揃うまでPhase3着手不可）：**
- ① App登録スコープ（Sites.Read.All／Mail.Send／Notes.ReadWrite.All等）
  について承認を得ている
- ② Azure AD Conditional Access等のアクセス制限が、GitHub Actions実行
  環境（社外IP）からのアクセスをブロックしないことを確認している
- ③ シークレット保管方式（GitHub Actions Secrets利用）についてセキュ
  リティ部門の同意を得ている

## Phase2（Architecture Audit）で実施すべき項目
1. Caracalシートの実際のセルレンジ・列構成を確認し、取得範囲を確定する
2. GitHub Actions と Azure Functions/Automation のコスト・保守性・障害
   通知手段を比較検討する
3. 既存のSharePoint Portal／OneNote Report GeneratorのMSAL実装を、本
   プロジェクトでどう再利用するか設計する
4. 障害検知ロジック（API失敗・シート構造変更検知・GitHub Actions実行
   失敗）の具体的な実装方式を検討する
5. KPI（効果測定指標）を1つ以上、具体的な数値目標込みで確定する
6. 属人化対策として残す引継ぎドキュメントの最終フォーマットを決める
   （本SSOT三点セット＋本ファイルで十分か検討）

## 保留（今回は着手しない）
- 汎用YAML駆動タスクエンジン化
- 他KPIシートへの水平展開
- Teams通知・Outlook ToDo連携

## Claude Codeセッションでの進め方
- 上記「最優先タスク（Phase0）」が完了するまでは、コード実装（Phase3）
  を開始しないこと
- Phase2の議論結果は本ファイルおよびSESSION_HISTORY.mdに追記していくこと
- コード生成は越智さんの明示的承認（「３．承認します」）後のみ実施する
  ことを厳守する

---
文書オーナー：越智さん（Nexperia Japan Site Manager）
最終更新：2026-09-17
次回更新予定：Phase2着手時
