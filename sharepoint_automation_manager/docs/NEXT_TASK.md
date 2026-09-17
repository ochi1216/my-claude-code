# NEXT_TASK.md

## 最優先タスク（Phase0：ガバナンス確認）
1. IT/セキュリティ部門へ、App登録スコープ・シークレット保管方式について
   事前相談を行う

**Phase0の受け入れ基準（この3点が揃うまでPhase3着手不可）：**
- ① App登録スコープ（Sites.Read.All／Mail.Send、委任(Delegated)権限）
  について承認を得ている（既存承認済みツールと同一スコープ。ADR-008に
  より、Application権限への変更は不要になった）
- ② Azure AD Conditional Access等のアクセス制限が、GitHub Actions実行
  環境（社外IP）からのアクセスをブロックしないこと、および
  sign-in frequency等の再認証ポリシーがsilent refresh（無人トークン
  更新）を阻害しないことを確認している
- ③ シークレット保管方式（GitHub Actions Secrets利用）についてセキュ
  リティ部門の同意を得ている。**保管対象が単純なAPIキーではなく、有効な
  リフレッシュトークンを含むMSALトークンキャッシュであることを明示し、
  漏洩時のリスク・アクセス権限の絞り込み方針も併せて相談する（ADR-008）**

## Phase2（Architecture Audit）進捗（6項目）
1. Caracalシートの実際のセルレンジ・列構成の確認：**未確認**（越智さんが
   実データを直接確認する必要あり。Graph Explorerで`workbook/worksheets/
   {id}/usedRange`を一度叩くだけでよい、コード不要）
2. GitHub Actions と Azure Functions/Automation の比較：**済**（コスト差
   実質ゼロ、保守性・障害通知でGitHub Actionsが優位。ただしcronは
   ベストエフォートのため「17:00〜17:30」の許容幅を採用、越智さん承認済み）
3. 既存MSAL実装の再利用方針：**済**（ADR-008。既存ツールと同じDevice
   Code Flow・委任権限を流用、Application権限化は不要と訂正）
4. 障害検知ロジックの具体的な実装方式：**方針確定**（API失敗はリトライ＋
   最終失敗通知、シート構造変更は列見出し突き合わせで検知、実行失敗は
   標準通知＋「17:30までに成功通知が来なければ異常」の見張り。通知文面・
   エスカレーション先はPhase3設計時に確定）
5. KPIの確定：**済**（ADR-010。効率化／信頼性／応答性の3指標を併用）
6. 引継ぎドキュメントの最終フォーマット：**現行のCLAUDE.md＋docs/三点
   セット（`journal/`フォルダと同方式）で十分と判断。Phase3完了時に
   障害対応Runbookを追加することを推奨（将来タスク）**

## 残タスク（Phase2を完了するために必要）
- 項目1（Caracalシートの実データ確認）：越智さんの確認待ち

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
次回更新予定：Caracalシートの実データ確認完了時、またはPhase0着手時
