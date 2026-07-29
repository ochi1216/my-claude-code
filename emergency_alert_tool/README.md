# 緊急連絡ツール（emergency_alert_tool）

緊急地震速報で **大分県・大阪府・東京都** に **震度5弱以上** の速報が出た場合に、
緊急連絡網のスタッフ18名へ安否確認を自動送信し、各スタッフが

1. 安否：無事 / 被災
2. 場所：職場 / 自宅
3. 出社可否：出社可能 / 出社不可能

の3項目をクリックで回答すると、即座に上司3名へ通知するツール。
Microsoft 365環境（Microsoft Graph API）を前提とする。

## 全体の流れ

1. `EarthquakeEEWClient` が緊急地震速報フィードを定期的にポーリングする。
2. 大分県・大阪府・東京都のいずれかで震度5弱以上を検知したら
   (`judge_trigger`)、`AlertService` がアラートを発行し、18名の
   スタッフへ個別の回答リンク付きメールを送信する（Microsoft Graph
   `sendMail`, app-only / client credentials フロー）。
3. スタッフはメール内のリンクから回答フォーム（`/respond/<token>`）を開き、
   3項目をクリックで選択して送信する。
4. 送信されると即座に上司3名へ、回答内容を記載した通知メールが送信される。
5. `/dashboard/<alert_id>` で、18名の回答状況（回答済み/未回答、回答内容）を
   一覧で確認できる。

## ファイル構成

| ファイル | 内容 |
| --- | --- |
| `emergency_alert_tool_20260729_01.py` | 本体（判定ロジック・Graph通知・Flaskアプリ・ポーリング） |
| `config.example.json` | 設定ファイルのサンプル（実運用時は `config.json` としてコピーし、秘密情報以外を記入） |
| `requirements.txt` | 依存パッケージ |
| `tests/test_emergency_alert_tool.py` | pytestによる自動テスト |
| `CHANGELOG.md` | 変更履歴 |

## セットアップ

### 1. 依存パッケージのインストール

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Azure ADアプリ登録（Microsoft 365テナント側の作業）

1. Azure Portal で新規アプリ登録を作成する。
2. **APIのアクセス許可** で Microsoft Graph の **アプリケーションの許可**
   （委任ではない）から `Mail.Send` を追加し、管理者の同意を行う。
3. **証明書とシークレット** でクライアントシークレットを発行する。
4. テナントID・アプリケーション(クライアント)ID・クライアントシークレットを控える。
5. メール送信元となるメールボックス（共有メールボックス推奨）のUPNを控える。

> 本ツールは app-only（アプリケーション権限）でメールを送信する構成のため、
> 特定ユーザーのサインインは不要。ただし `Mail.Send` はテナント内の
> 任意のメールボックスから送信可能な強い権限のため、
> [アプリケーションアクセスポリシー](https://learn.microsoft.com/graph/auth-limit-mailbox-access)
> で送信元メールボックスを限定することを推奨する。

### 3. 設定ファイルの作成

```bash
cp config.example.json config.json
```

`config.json` を編集し、以下を設定する。

- `tenant_id`, `client_id`: Azure ADアプリ登録の値
- `sender_upn`: 送信元メールボックスのUPN
- `staff`: 緊急連絡網のスタッフ18名（id, name, email）
- `supervisors`: 通知先の上司3名（id, name, email）
- `target_prefectures`, `intensity_threshold`: 既定値は
  `["大分県", "大阪府", "東京都"]` / `"5弱"`
- `quake_api_url`: 緊急地震速報フィードの取得先URL（**要検証**、下記「既知の制約」参照）
- `response_base_url`: スタッフ向け回答フォームを公開するURL
  （社内公開用のFQDN等。ローカル動作確認時は `http://localhost:5000`）

クライアントシークレットは **`config.json` に書かず**、環境変数
（既定では `EMERGENCY_ALERT_CLIENT_SECRET`。`config.json` の
`client_secret_env` で変更可）で渡すこと。

```bash
export EMERGENCY_ALERT_CLIENT_SECRET="<クライアントシークレット>"
```

### 4. 実行

Webサーバ（回答フォーム・ダッシュボード）と、地震速報フィードの
ポーリングを同時に起動する場合:

```bash
python emergency_alert_tool_20260729_01.py --config config.json --mode web --port 5000
```

ポーリングのみを別プロセスで実行する場合:

```bash
python emergency_alert_tool_20260729_01.py --config config.json --mode poll
```

手動で1回だけ判定を実行したい場合（動作確認用）:

```bash
curl -X POST http://localhost:5000/internal/check
```

## テスト

```bash
pip install pytest
pytest tests/ -v
```

震度判定ロジック、緊急地震速報データのパース、18名への通知送信、
回答フォーム〜上司3名への即時通知、重複トリガー防止、ダッシュボード表示について、
Microsoft Graph API呼び出しをテスト用ダブルに置き換えたテストを実施している
（実際のM365テナントへの疎通は行っていない）。

## 既知の制約・本番導入前に確認すべきこと

- **緊急地震速報フィードの実データスキーマは未検証**:
  `parse_p2pquake_eew` はP2P地震情報API (`https://api.p2pquake.net/v2/`)の
  緊急地震速報(警報, code=556)を想定した実装だが、本セッション環境からは
  外部API仕様ドキュメントへアクセスできなかったため、既知情報を基にした
  想定実装であり、実データでの検証が必要。本番導入前に実際のAPIレスポンスで
  フィールド名・震度コードの対応を確認すること。また、可用性・信頼性の観点で
  公式の気象庁DPFや商用EEW受信サービスの利用も検討すること。
- **回答リンクはトークン方式**: URLに含めるワンタイムトークンで
  スタッフを識別しており、Azure AD等によるサインイン認証は行っていない。
  なりすまし・URL漏洩のリスクがあるため、本番運用前にSSO化や
  トークンの有効期限設定などの強化を検討すること。
- **実際のM365テナントでの送信確認は未実施**: このセッションでは
  ロジック・Flaskルートの自動テストのみ実施しており、実際のGraph API
  疎通（アプリ登録・権限・管理者同意・実際のメール送受信）は未確認。
- **永続化はSQLite**: 単一ホストでの利用を想定した簡易実装。
  複数インスタンスでのスケールアウトが必要な場合は別のデータストアを検討すること。
