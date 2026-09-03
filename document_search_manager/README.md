# Document Search Manager

社内のドキュメント管理システムを、**同一キーワードで横断検索**するツール。

| 選択肢 | 対象 | 状態 |
|---|---|---|
| `0. All` | 有効な全系統を並列検索（既定） | ✅ 稼働（現在はSharePointのみ） |
| `1. SharePoint` | 社内SharePoint全社横断検索 | ✅ **Phase 1で実装済み** |
| `2. Nexus` | Shareflex品質文書サイト（SF_QualityDocumentsProd） | ⏳ Phase 2で実装予定 |
| `3. Enovia` | 3DEXPERIENCE / ENOVIA | ⏳ Phase 3で実装予定 |

未実装の系統は、UI上に「Phase 2で実装予定」と明示されます（黙って0件を返しません）。

## 必要要件

- Python 3.9以上
- 対象SharePointへの閲覧権限（**新規のEntra ID権限申請は不要**）

## 認証について（重要）

本ツールは **`po_database_organizer` と同一のEntra IDアプリ登録をそのまま流用**します。
要求スコープは **`Sites.Read.All` のみ**で、新規のGraph権限申請は一切発生しません。

- `config.json` の `tenant_id` / `client_id` を空のままにしておくと、
  `../po_database_organizer/config.json` から自動的に借用します（**読むだけ**で書き換えません）。
- トークンキャッシュは本フォルダ内の `token_cache.json` に分離して保存します
  （`po_database_organizer` と同時に起動しても競合しません）。そのため初回だけ、
  本ツール用のデバイスコード認証が1回必要です。

## セットアップ手順

1. 依存パッケージをインストールする。

   ```
   pip install -r requirements.txt
   ```

2. `config.example.json` を `config.json` にコピーする（中身は編集不要でそのまま動きます）。

   ```
   copy config.example.json config.json
   ```

3. 起動する。`run_document_search_manager.bat` をダブルクリックするか、次を実行する。

   ```
   python document_search_manager_20260903_01.py
   ```

   初回はターミナルにDevice Code Flowの認証コード（URLとコード）が表示されるので、
   表示されたURLをブラウザで開いてサインインする。

4. `http://127.0.0.1:5020` が自動で開く。キーワードを入力して「検索」を押す。

> `run_document_search_manager.bat` は先頭で `cd /d %~dp0` を実行するため、
> ショートカットや別フォルダから起動しても正しく動作します。

## 画面の使い方

- **検索欄**にキーワードを入力し、Enter または「検索」ボタン。
- **検索対象**を `0. All` 〜 `3. Enovia` から選択（既定は `0. All`）。
- **取得件数**は上位 50 / 100 / 200 / 500 件から選択（既定100件）。
  無制限取得は行いません（体感速度を優先しているため）。
- **疎通診断**ボタンで、各系統が利用可能かを確認できます。
- **Excel出力 / CSV出力**で結果を `exports/` フォルダに保存します。

### 系統別ステータスの見方

| 表示 | 意味 |
|---|---|
| 🟢 | 検索成功（1件以上ヒット） |
| 🟡 | 検索は成功したが0件 |
| 🔴 | エラー（メッセージに理由を表示） |
| ⚪ | 未実装（Phase 2 / Phase 3で実装予定） |

1つの系統がエラーになっても、他の系統の結果は必ず表示されます（部分成功方式）。

## トラブルシューティング

### 疎通診断で「権限不足」と出る

Graphの `/search/query` が `Sites.Read.All` では拒否された場合です。
**権限を追加申請する必要はありません。** `config.json` の `fallback_site_urls` に
検索したいサイトのURLを列挙すると、サイト単位検索モードに切り替わります。

```json
"fallback_site_urls": [
  "https://nexperia.sharepoint.com/sites/JapanDesign",
  "https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd"
]
```

### 検索結果の「開く」リンクが開けない

社内ブラウザが `.mcas.ms`（Microsoft Defender for Cloud Apps）経由でないと
アクセスできない場合があります。`config.json` の以下を `true` にしてください。

```json
"rewrite_host_to_mcas": true
```

### `tenant_id / client_id が特定できませんでした` と出る

`po_database_organizer/config.json` が存在しない環境です。
本ツールの `config.json` に、既存ツールと同じ `tenant_id` / `client_id` を直接記入してください。

## 設定項目（`config.json`）

| キー | 既定値 | 説明 |
|---|---|---|
| `tenant_id` / `client_id` | 空 | 空なら `po_database_organizer/config.json` から借用 |
| `graph_scopes` | `["...Sites.Read.All"]` | 要求スコープ。**変更すると新規権限申請が必要になるため、原則変更しない** |
| `flask_port` | `5020` | 画面のポート（既存ツールの5000/5010と衝突しない値） |
| `default_max_results` | `100` | 既定の取得件数 |
| `hard_max_results` | `500` | 取得件数の上限 |
| `provider_timeout_sec` | `30` | 1系統あたりのタイムアウト秒数 |
| `nexus_site_url` / `nexus_folder_path` / `nexus_list_id` | Nexus用 | Phase 2で使用（Phase 1では未使用） |
| `dedupe_nexus_from_sharepoint` | `false` | Nexusサイト配下の文書をSharePoint結果から除外するか。**Phase 2で `true` にする** |
| `rewrite_host_to_mcas` | `false` | リンクを `.mcas.ms` 経由に書き換えるか |
| `fallback_site_urls` | `[]` | 全社検索が使えない場合のサイト単位検索対象 |

## 生成物とGit管理

以下は `.gitignore` で除外しており、リポジトリにはコミットされません。

- `config.json`（テナントID等を含む）
- `token_cache.json`（認証トークン）
- `cache/`, `exports/`（検索キーワードや結果を含む）

コミット対象は `config.example.json` のみです。

## 既知の制限（Phase 1のスコープ外）

- Nexus検索・Enovia検索は未実装（Phase 2 / Phase 3）。
- 検索結果に**本文スニペットは含めない**（一覧表示までが今回のスコープ）。
- Graph `/search/query` が `Sites.Read.All` で通るかは、会社PCでの実機確認が必要
  （通らない場合はサイト単位検索へ自動フォールバックする）。
- 検索結果のランキングはGraphの返却順に従う。SharePoint画面の並び順とは
  一致しない場合がある。

## 開発計画（全体像）

| Phase | 内容 | 状態 |
|---|---|---|
| Phase 1 | SharePoint全社検索 MVP | ✅ 完了（v20260903_01） |
| Phase 2 | Nexus検索追加（Graph Searchを `nexus_folder_path` に限定）＋重複排除の有効化 | 未着手 |
| Phase 3 | Enovia検索追加（実装方式は調査後に確定） | 未着手 |
| Phase 4 | 3系統統合の磨き込み（名寄せ・検索履歴・お気に入り） | 未着手 |
