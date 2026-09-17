# CLAUDE.md（sharepoint_automation_manager/ プロジェクト専用）

このファイルは、`sharepoint_automation_manager/`フォルダ内の「SharePoint KPIシート
自動取得・通知プロジェクト」に限定して適用される、Claude Code Webセッション間の
作業引継ぎルールです。リポジトリの他のフォルダ・他のプロジェクトにはこのルールを
適用しません（リポジトリ全体のGit運用・コミット規約は、リポジトリルートの
`CLAUDE.md`に従います。両者が矛盾しない限り、本ファイルはそれに追加するルールです）。

## プロジェクト概要

- 目的：Nexperia社内SharePoint上のExcelファイル
  「Power_MAG_2026_KPI_Standup_Checklists-Rev0.9-09-11-26.xlsx」内の
  “Caracal”シートを、毎週木曜17:00・金曜17:00に自動取得し、Outlook通知
  （将来的にはOneNote記録）まで自動化する。
- 対象ファイルURL：
  https://nexperia.sharepoint.com/:x:/r/sites/MAGR04/_layouts/15/Doc.aspx?sourcedoc=%7B9D73675F-3852-4C4E-A8AE-BF97579DECB4%7D&file=Power_MAG_2026_KPI_Standup_Checklists-Rev0.9-09-11-26.xlsx
- 責任者：越智さん（Nexperia Japan Site Manager）
- 開発体制：越智さん個人開発、Claude Code環境で実装

## 現在のフェーズ

- Phase1（設計提案）改訂版：承認済み
- Phase2（Architecture Audit）：進行中（6項目中4項目確定。残りはCaracalシート
  の実データ確認のみ、越智さんの確認待ち）
- Phase0（ガバナンス確認：IT/セキュリティ部門への事前相談）が未完了。
  Phase0が完了するまでPhase3（実装）には着手しない
- 詳細は `sharepoint_automation_manager/docs/PROJECT_STATUS.md` /
  `sharepoint_automation_manager/docs/NEXT_TASK.md` を参照

## 関連ドキュメント

- `sharepoint_automation_manager/docs/PROJECT_STATUS.md` … プロジェクトの現状
- `sharepoint_automation_manager/docs/SESSION_HISTORY.md` … 意思決定履歴（ADR形式）
- `sharepoint_automation_manager/docs/NEXT_TASK.md` … 次回タスクと受け入れ基準
- `sharepoint_automation_manager/CHANGELOG.md` … コード実装開始（Phase3）後に作成
  予定（現時点では未作成。本ファイルとは役割が異なるため内容を不必要に重複させない）

## 厳守ルール（この開発ワークフロー専用ルール）

- 3フェーズ厳守：Phase1設計提案（コード生成禁止）→ Phase2アーキテクチャ監査
  （問題点洗い出し・承認待ち）→ Phase3実装パッチ（diff駆動・最小変更のみ）
- コード生成は越智さんの明示的承認（「３．承認します」）後のみ実施
- コード出力規約：unified diff形式必須、完全版関数を必ず提示（省略・
  「以下同様」禁止）、CHANGELOG.md形式でバージョン宣言、テスト手順は
  コードブロック外に記載
- バージョニング形式：`{toolname}_{YYYYMMDD}_{NN}`
- 日本語ログ出力＋絵文字ステータス表示
- UIを作る場合はダークテーマ統一（bg:#1a1a2e / accent:#e94560）

## 環境制約（重要）

- 実行環境は会社PC運用を想定。外部LLM呼び出しは **Gemini API限定**
  （Claude APIの直接呼び出し不可）
- Git運用：`ochi1216/my-claude-code` リポジトリ、Fine-grained PAT使用、
  company PCでのpull動作は確認済み
- 実行基盤としてGitHub Actions（クラウド実行環境）を軸とする方針のため、
  graph.microsoft.com への外部アクセスがAzure ADの **Conditional Access
  ポリシー**（IPアドレス制限・デバイス準拠要件等）に抵触しないか、
  および **sign-in frequency等の再認証ポリシーが下記のsilent refreshを
  阻害しないか**、Phase0のIT確認時に必ず併せて確認すること
  （★未確認・重要リスク）
- 認証方式（ADR-008で決定）：既存ツールと同じMSAL Device Code Flow・
  委任(Delegated)権限を流用する。Application権限への切替は不要。
  初回サインインのみ越智さんご本人が対話操作で実施し、以降はMSALの
  トークンキャッシュ（リフレッシュトークン含む）をGitHub Actions
  Secretsに保管して`acquire_token_silent`で無人更新し、更新後の
  キャッシュを毎回書き戻す。**保管対象が有効なリフレッシュトークンを
  含むため、単純なAPIキーより漏洩時の影響が大きい点をPhase0でIT/
  セキュリティに明示すること**
- 実行タイミング（ADR-009で決定）：GitHub Actionsのcronはベストエフォート
  で遅延することがあるため、「17:00〜17:30の間に届けば正常」とする
- 既存関連ツール（認証実装の再利用元）：
  - SharePoint Portal（r19_site_organizer）：Graph API + MSAL Device Code Flow
  - OneNote Report Generator（onenote_report_generator）：Graph API、
    青文字検出＋Gemini要約

## 対象外・保留事項（今回のスコープ外）

- 汎用YAML駆動タスクエンジン化 → MVP効果確認後の将来フェーズ（Phase4想定）
- Caracalシート以外のKPIシートへの展開 → 同上
- Teams通知、Outlook ToDo連携 → 将来拡張候補（未着手）

## APIキー・認証情報の扱い

- App登録のクライアントID/シークレット、トークンキャッシュ等は
  `sharepoint_automation_manager/config.json`（Phase3で作成予定、`.gitignore`対象）
  に保持し、コミット対象は `config.example.json` のみとする
  （リポジトリ内の他ツール：`r19_site_organizer/`, `onenote_report_generator/`
  等と同じ方式）

---
文書オーナー：越智さん（Nexperia Japan Site Manager）
最終更新：2026-09-17（リポジトリへの初回取り込み時点）
