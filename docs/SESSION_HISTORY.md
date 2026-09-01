# Session History

## Session Index

| Session | Title | Date | Status | Main Files |
| ------- | ----- | ---- | ------ | ---------- |
| S01 | 緊急連絡ツールの開発 S01 - 自動送信機能を持たせる | 2026-07-29〜2026-07-31 | 完了 | `CLAUDE.md`, `docs/*.md`, `emergency_alert_tool/*`, `power_automate_safety_checkin/*` |
| S02 | 緊急連絡ツールの開発 S02 - Power AutomateフローのGUI構築とGate B/D検証 | 2026-09-01 | 完了 | `power_automate_safety_checkin/solution/*`, `power_automate_safety_checkin/evidence/*`, `power_automate_safety_checkin/cards/*`, `power_automate_safety_checkin/docs/*` |

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

## S02 - 緊急連絡ツールの開発 S02 - Power AutomateフローのGUI構築とGate B/D検証 (2026-09-01)

### 概要

Power Automate版PoC（P1: 手動トリガー版）のフロー本体を構築し、DEV環境で動作させた。
当初の計画は「`docs/FLOW_LOGIC_SPEC.md`の通りにGUIで3フローを組む」だったが、
セッション途中で**構築方法そのものを転換**している（下記「判断した内容」参照）。
結果として、P1のフローは2本（EQ06・EQ05）に整理され、両方とも実機で動作確認できた。

### 判断した内容（重要な方針転換）

**1. GUI構築 → JSON生成＋CLIインポートへ転換**

`EQ06_Manual_Drill_DEV`をGUIで組み始めたが、以下の問題に直面した。

- 1フローで30ステップ超のクリック操作が必要
- 「保存」を押す前に画面を再読み込みしたところ、**作りかけのフローが丸ごと消失**
- 同じ作業をEQ04b・EQ05でも繰り返す必要がある

ユーザーから「GUIを一切触りたくない」という明確な要望があり、方式を転換した。
クラウドフローの実体はJSON（Logic AppsのWorkflow Definition Language）であり、
Dataverse Solutionとしてインポートできる。ただしSolutionへの格納形式は公開情報
だけでは特定できなかったため、**実テナントに最小フローを作ってエクスポート・
unpackし、形式を実測で確定させた**。

以降、フローは`solution/build_flows_20260901_01.py`が生成し、
`pac solution pack` → `pac solution import` の3コマンドで再展開できる。

**2. EQ04b（応答受信フロー）を廃止し、EQ06へ統合**

当初設計は「カードを投げ切り、応答は別フロー（EQ04b）のトリガーで受ける」非同期方式
だったが、**このテナントのTeamsコネクタのトリガー11種類を全て確認した結果、
アダプティブカードの応答を受け取るトリガーが存在しない**ことが判明した
（紛らわしい「チャットでメッセージに応答があったとき」は`WebhookMessageReactionTrigger`＝
絵文字リアクション用）。

代わりに`PostCardAndWaitForResponse`（応答を待機するアクション）を
`LOOP_Each_Member`の中で使い、**ループを並列実行**して全員分を同時に待つ方式にした。
「直列だと1人目の回答まで他メンバーへ届かない」という当初要件は並列実行で満たしている。

**3. 検証中の誤送信防止を導入（実際に事故が起きたため）**

実機テストで、`EQ_Config_Members`に登録されていた**実在の同僚2名へ訓練用の
安否確認カードが実際に届いてしまった**。しかも当時は個人カードに`【訓練】`表示が
無く、受け取った側は訓練と判断できない状態だった。

再発防止として、`deploy_config.json`の`testRecipientOverride`を設定している間は、
**拠点や`IsTest`の値にかかわらず**個人カード・上司通知の宛先が検証者だけに向く
仕組みを入れた。`IsTest`を条件にしなかったのは、防ぎたいのが人為ミス
（訓練フラグの付け忘れ、拠点の選び間違い）そのものだからである。
あわせて架空拠点`NARA`（検証者1名のみ所属）を用意し、実在拠点の名簿に
触れずに拠点分岐を試せるようにした。個人カードにも`【訓練】`を付けるよう修正した。

### 実作業内容

**SharePoint側**

- 4リストのExcelアップロードを完了（S01からの持ち越し。未着手だった）
- Excelテンプレートがテーブル形式でないとアップロードできないことが判明し、作り直し
- `EQ_Responses.xlsx`に`Title`列（重複判定キー）が抜けていた不整合を発見・修正
- 見本データ無しでアップロードしたため多くの列が**数値型**で作られており、
  `EQ_Events`の5列（SiteCode/OccurredAt/Epicenter/SiteIntensityCode/IsTest）の型を修正

**Gate B（Teamsカードアクション）— 合格**

- 「チャットやチャネルにカードを投稿する」（`PostCardToConversation`、応答を待たない）が
  標準コネクタに存在し、非推奨でないことを実測
- 1:1チャットへの投稿（`location: "Chat with Flow bot"`）も実機で成功
- 待機型（`PostCardAndWaitForResponse`）の応答JSON構造を実測し、
  `evidence/teams_card_response_sanitized.json`へ記録。`data`配下に回答値、
  `responder`配下に**実際に回答した人**が入るため、カード内のIDを詐称されても照合できる

**Gate D（SharePoint列内部名）— 実測完了**

- **Excelアップロードで作ったリストは、内部名が表示名と一致せず`field_1`, `field_2`...
  という連番になる**ことが判明（`Title`のみ標準列）。`item/<列>`や`$filter`では
  内部名を使う必要がある
- 3リスト分の内部名・型を`evidence/sharepoint_internal_names.json`へ記録

**設計上の誤りの発見と修正**

- `outputs('CMP_Site_Config')`のようにSwitchアクション名で結果を参照することは
  できない（Switchは制御構造で出力を持たない）。変数（`varSiteConfig`/
  `varIntensityValue`）経由に変更
- 並列ループ内では変数が全イテレーションで共有されるため使えない。
  安否・出社可否の判定は式で直接計算する形にした
- 未回答（タイムアウト）時にループ全体が失敗する事象を実測。待機アクションの後続を
  `CHK_Responded`という条件1つにまとめることで解決した

**実装したフロー**

- `EQ06_Manual_Drill_DEV`: 閾値判定／イベント記録／チャネル通知／対象者抽出／
  個人カード送信と回答待機（並列）／回答保存／被災時の上司通知／未回答時の正常終了
- `EQ05_Status_Summary_DEV`: `AlertStatus=Open`のイベントごとに対象者数・回答数・
  未回答数・被災者数を集計してチャネルへ投稿

### 変更したファイル

- `power_automate_safety_checkin/solution/build_flows_20260901_01.py`（新規）: フロー定義の生成
- `power_automate_safety_checkin/solution/deploy_config.example.json`（新規）: 設定テンプレート
- `power_automate_safety_checkin/solution/README.md`: 方式・実測仕様・本番切替チェックリスト
- `power_automate_safety_checkin/evidence/`（新規）: Gate B/Dの実測値
- `power_automate_safety_checkin/cards/manager_alert_card.json`（新規）: 被災報告カード
- `power_automate_safety_checkin/cards/status_summary_card.json`（新規）: 集計カード
- `power_automate_safety_checkin/cards/checkin_card.json`: `【訓練】`表示を追加
- `power_automate_safety_checkin/docs/FLOW_LOGIC_SPEC.md` / `GATE_STATUS.md`: 実測値へ更新
- `power_automate_safety_checkin/EQ_*.xlsx`（新規）: SharePointアップロード用テンプレート
- `.gitignore`: `deploy_config.json`・生成物を除外

### 確定した仕様

- 回答の受け取りは**待機型アクション＋並列ループ**（応答トリガーが存在しないため）
- `EQ_Responses.Email`には、カード内のIDではなく`responder.email`（実際の回答者）を記録
- 回答の重複防止（Upsert）は不要。待機型では1実行につき1人1回しか回答を受け取れない
- 未回答はエラーではなく訓練結果の一種として扱い、フローは正常終了する
- フローはJSON生成＋`pac`CLIインポートで管理する（GUIでは組まない）

### テスト結果

DEV環境（`Nexperia (default)`）で以下を実機確認。

| テスト | 結果 |
| --- | --- |
| 閾値未満（震度4） | 成功（`END_Below_Threshold`で正常終了、SharePoint・Teamsとも変化なし） |
| 閾値以上（震度5弱） | 成功（イベント記録・チャネル投稿・個人カード送信まで） |
| 回答あり（被災） | 成功（`EQ_Responses`へ`Affected`で記録、上司へ被災報告カード送信） |
| 未回答（1分タイムアウト） | 成功（フローは正常終了。当初は失敗していたため構造を修正） |
| EQ05の集計 | 成功（チャネルへ集計カード投稿） |

### 未確認事項

- エラー処理（`SCOPE_Try`/`SCOPE_Catch`→`EQ_Received_Items`）は未実装。
  `EQ_Received_Items`の列内部名も未取得
- イベントのクローズ（`AlertStatus`を`Closed`へ更新）は未実装
- 実在拠点（大分・大阪・東京）での訓練、3名結合テスト、18名訓練は未実施
- 拠点ごとの実Team/Channel IDは未設定（現在は全拠点とも検証用の同一チャネル）
- 誤送信した同僚2名へのフォローが必要かはユーザー判断

### 次回作業

`docs/NEXT_TASK.md` のS03セクションを参照。

---

<!--
以降のセッションはこの形式で追記する。同一セッション中には途中更新せず、終了時に1件としてまとめる。
-->
