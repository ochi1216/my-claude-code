# Session History

## Session Index

| Session | Title | Date | Status | Main Files |
| ------- | ----- | ---- | ------ | ---------- |
| S01 | 緊急連絡ツールの開発 S01 - 自動送信機能を持たせる | 2026-07-29〜2026-07-31 | 完了 | `CLAUDE.md`, `docs/*.md`, `emergency_alert_tool/*`, `power_automate_safety_checkin/*` |

## S01 - 緊急連絡ツールの開発 S01 - 自動送信機能を持たせる (2026-07-29〜2026-07-31)

### 概要

新規プロジェクトの初回セッション。管理ファイルの初期導入と、緊急連絡・安否確認
ツールの自動送信機能の実装を行った。セッション途中で、Python + Microsoft Graph API版から
Power Automate版へ実装方式を転換している（理由は下記「判断した内容」参照）。

### 管理ファイルの初期導入

`CLAUDE.md`（セッション管理ルール・開発ルール）、`docs/PROJECT_STATUS.md`、
`docs/SESSION_HISTORY.md`、`docs/NEXT_TASK.md` をリポジトリ直下に新規作成した。

### 実作業内容

**前半: Python + Microsoft Graph API版（`emergency_alert_tool/`）**

- 緊急地震速報（大分県・大阪府・東京都、震度5弱以上）のトリガー判定ロジックを実装
- P2P地震情報API想定のパーサーを実装（実データスキーマは未検証）
- Microsoft Graph API（MSAL, app-only）による18名への通知送信を実装
- 3項目（無事/被災、職場/自宅、出社可能/出社不可能）クリック選択の回答フォーム（Flask）を実装
- 回答送信時の上司3名への即時通知を実装
- ダッシュボード（`/dashboard/<alert_id>`）を実装
- pytestによる自動テスト21件を作成・全件合格を確認
- Windows実機で動作確認（バッチファイル起動、依存関係インストール、
  dry-runモードでのE2E確認）。この過程で以下を修正:
  - バッチファイルの文字コード起因の起動不能（UTF-8とShift-JISコンソールの不一致）を修正
  - `config.json`未作成時に`config.example.json`から自動生成する機能を追加
  - dry-runモード（`LoggingNotifier`）と`/internal/test-trigger`エンドポイントを追加し、
    実M365接続なしで全体フローを検証できるようにした
- Azure ADアプリ登録・`Mail.Send`権限への管理者同意が、ユーザー個人の権限では
  完結しないことが実機検証で判明。IT部門への依頼文を作成した（未送付）。

**後半: Power Automate版（`power_automate_safety_checkin/`）**

- ユーザーから提示されたGPT設計のPower Automate構想書
  （`Earthquake_Safety_System_0730_02`）を精査し、`docs/REVIEW_earthquake_safety_system_0730_02.md`
  として報告（詳細は「判断した内容」参照）
- 精査結果を踏まえ、P1（手動トリガー版）のPoCを新規構築:
  - SharePointデータモデル（当初5リスト→後に4リストへ変更）
  - Adaptive Card（チャネル通知用・個人回答用）
  - フローロジック仕様（`docs/FLOW_LOGIC_SPEC.md`、コピペで組める粒度）
  - SharePoint自動プロビジョニングPowerShellスクリプト（PnP.PowerShell）
  - pac CLIによるDEV→TEST→PROD展開スクリプト
  - Windows起動用バッチランチャー
- 実機検証で以下の問題を発見・解決:
  - PnP.PowerShell 3.x系はWindows PowerShell 5.1非対応、PowerShell 7が必須
  - 古いPowerShellGet（1.0.0.1）による`Install-Module`失敗（更新して解決）
  - 実行ポリシー制限（`-Scope Process`で回避）
  - モジュール自動読み込みの不具合（`Import-Module`明示化で解決）
- PnP.PowerShellでのSharePoint接続に、Entra IDアプリ登録（委任アクセス）が必要と判明。
  ユーザーのアカウントでは登録権限がなく（`Insufficient privileges`）、Python版と
  同種の壁に直面。IT部門への依頼文を作成したが、ユーザー判断により保留。
- ユーザー判断: SharePointリスト作成はPowerShell自動化を諦め、**Excel一括アップロード**
  による手動作成に切替え。5リスト分（後に4リストへ変更）のExcelファイルを生成・送付。
- ユーザー指摘を受け、`EQ_Config_Sites`をSharePointリストから廃止し、拠点情報
  （大分・大阪・東京、震度閾値）をフロー内のSwitchアクションへ固定値として
  持たせる設計に変更。`EQ_Config_Members`の管理者ID命名を`boss01/02/03`から
  `mgr01`/`mgr02`/`admin01`に変更。

### 変更したファイル

新規作成・主要ファイルのみ記載（詳細は各フォルダの`CHANGELOG.md`参照）。

- `CLAUDE.md`（新規）: セッション管理ルール、ファイル命名規約（`.ps1`にも拡大）、
  バッチファイルの文字コード規約を追加
- `docs/PROJECT_STATUS.md` / `docs/SESSION_HISTORY.md` / `docs/NEXT_TASK.md`（新規）
- `docs/REVIEW_earthquake_safety_system_0730_02.md`（新規）: Power Automate構想の精査レポート
- `emergency_alert_tool/`（新規フォルダ、複数リビジョン）: Python + Graph API版一式
- `power_automate_safety_checkin/`（新規フォルダ、複数リビジョン）: Power Automate版一式
- `.gitignore`: 両ツールのローカル設定・秘密情報ファイルを除外する行を追加

### 確定した仕様

- 監視対象: 大分県・大阪府・東京都、震度5弱以上
- 回答項目: 4択（安否×出社可否の組み合わせ）
- 通知先: スタッフ18名（PoCスコープ、将来的に日本支社40名へ拡大想定）＋管理者3名
  （`mgr01`, `mgr02`, `admin01`）
- 拠点情報はSharePointリストではなくフロー内固定値
- 非同期アーキテクチャ（カード投げ切り＋応答トリガー分離）
- 本仕組みは、会社の有料安否確認サービス導入までの暫定措置・PoC

### テスト結果

- `emergency_alert_tool/`: pytest 21件全PASS。Windows実機でdry-run E2E確認済み
  （トリガー→18名通知ログ→回答フォーム送信→上司通知ログ、まで動作確認）。
- `power_automate_safety_checkin/`: PowerShellスクリプトはAST構文検証のみ
  （PSScriptAnalyzer・実PnP接続によるテストは、セッション環境がPowerShell Galleryや
  対象テナントへ到達できないため未実施）。Power Automateフロー自体は未構築のため未テスト。

### 未確認事項

- Power Automate版のGate B（Teamsカードアクションの実際の名称・応答JSON構造）
- Power Automate版のGate D（SharePoint列内部名）
- SharePointへの4リストのExcelアップロードが完了したか（セッション終了時点で未確認）
- Python版の実M365テナントへのメール送信可否（Azure AD管理者同意待ち）
- 社内の既存安否確認手段の有無についての正式な部門間確認

### 次回作業

`docs/NEXT_TASK.md` のS02セクションを参照。

---

<!--
以降のセッションはこの形式で追記する。同一セッション中には途中更新せず、終了時に1件としてまとめる。
-->
