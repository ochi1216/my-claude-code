# R19 Site Organizer（R19 SharePoint Portal）

Nexperia社のSharePoint Onlineサイトを Flask Webアプリで一元管理するツール。
Graph API + MSAL Device Code Flow でサイトのフォルダ構成を段階的に探索・キャッシュし、
ブラウザ上でツリー表示・個別/一括ダウンロードを行う。

`po_database_organizer` はこのツールの技術基盤（Graph API + MSAL認証部分）を
PO管理用途に転用したもの。認証設定（`tenant_id` / `client_id`）は同一テナント・
同一パーミッション体系のため流用可能。

## 画面構成（3タブ）

- **Tab1: R19 Portal** — Quick Links一覧 + P0*/PS0* 命名規則のサイト一覧
- **Tab2: ICS R19 R&D** — 固定サイト（PSBGRD）のフォルダツリービューワー
- **Tab3: サイト別ツリー** — Tab1で選んだ任意サイトをアコーディオン展開して個別探索

各タブとも「1階層だけ探索（モードB）」と「複数階層を一括で再帰探索（モードA、
SSEストリーミングで進捗表示・一時停止/再開/キャンセル対応）」の2種類の探索方法を持つ。
探索結果は `cache/tree_<サイト名>_lazy.json` に累積保存され、次回起動時も再利用される。

## 必要要件

- Python 3.9以上
- 対象テナントのSharePointサイトへの `Sites.Read.All` 権限（Entra IDアプリ登録・Admin Consent済み）
- ダウンロード先フォルダ選択ダイアログのため、tkinterが利用可能な環境（Windows標準Pythonには同梱）

## セットアップ手順

1. 依存パッケージをインストールする。

   ```
   pip install -r requirements.txt
   ```

2. `config.example.json` を `config.json` にコピーし、環境に合わせて編集する。

   - `tenant_id` / `client_id` は、既存の `po_database_organizer` と同一の値を流用できる。
   - `site_path` は Tab2（ICS R19 R&D）で固定的に探索する対象サイトのパス。
   - `target_page` / `depth_limit` は現行コード内に参照箇所がなく、未使用の可能性が高い
     （移管元から引き継いだレガシーキー。要確認）。

3. サイト一覧マスター・クイックリンクマスターを用意する。

   - `sites_list.example.json` / `quick_links.example.json` を参考に、実データを
     `sites_list_YYYYMMDD.json` / `quick_links_YYYYMMDD.json` として同フォルダに配置する
     （ファイル名の日付部分は任意。複数存在する場合は辞書順で最新のものが自動選択される）。
   - **`sites_list_*.json`（テナント全サイト一覧）の取得方法は現時点で未確認。**
     移管元では手動生成・別スクリプトのいずれかで作成されていたと推測されるが、
     現行コードにはこのファイルを生成する機能が含まれていない。取得方法が判明次第、
     このREADMEおよび必要であれば生成スクリプトを追記する。
   - これらのファイルは実際の内部サイト名・サイトIDを含むため `.gitignore` で除外済み
     （コミット対象は `*.example.json` のみ）。

4. スクリプトを実行する。

   ```
   python r19_site_organizer_20260817_01.py
   ```

   初回はターミナルにDevice Code Flowの認証コード（URLとコード）が表示されるので、
   表示されたURLをブラウザで開いてサインインする。以降は `token_cache.json` に
   キャッシュされ、有効期限内は再認証不要。

   起動後 `http://localhost:5005` が自動でブラウザに開く。

   Tab2（ICS R19 R&D）のキャッシュのみをリセットして起動する場合:

   ```
   python r19_site_organizer_20260817_01.py --reset
   ```

5. ダウンロードは「フォルダ選択ダイアログ（tkinter）→ 選択フォルダ配下にサイト名
   サブフォルダを自動作成 → 保存」の流れで、個別・一括（チェックした複数ファイル）の
   両方に対応する。前回選択したフォルダは `download_prefs.json` に記憶される。

## 主要APIルート

| ルート | メソッド | 説明 |
|--------|---------|------|
| `/` | GET | HTMLテンプレート配信 |
| `/api/tree` | GET | Tab2用キャッシュ取得 |
| `/api/expand` | POST | Tab2の指定パスを1階層探索 |
| `/api/expand_deep` | GET(SSE) | Tab2の再帰探索（3階層固定） |
| `/api/reset` | POST | Tab2キャッシュリセット |
| `/api/portal/links` | GET | Quick Links取得 |
| `/api/portal/sites` | GET | P0*/PS0* サイト一覧取得 |
| `/api/portal/site_tree/<name>` | GET | Tab3サイトキャッシュ取得 |
| `/api/portal/expand/<name>` | POST | Tab3の指定パスを1階層探索 |
| `/api/portal/expand_deep/<name>` | GET(SSE) | Tab3の再帰探索（`depth`=1〜6指定可） |
| `/api/pick-folder` | POST | tkinterフォルダ選択ダイアログ |
| `/api/download/<name>` | GET | ブラウザストリーミングDL |
| `/api/download-to-folder` | POST | ローカルフォルダへ保存（サイト名サブフォルダ自動作成） |

## 既知の制限・未解決事項（移管元から引き継ぎ）

- **drive_id失効時の自動再取得ロジックがない。** 現状はサーバー再起動で復旧する
  （`route_reset()` はリセット前後で `drive_id` を保持するよう対応済みだが、
  起動中に失効した場合の再取得ロジックは未実装）。
- Tab2のリストモード切替ボタン絵文字（`textContent`→`innerHTML`修正、`fix_textcontent.py`
  で全箇所適用済み）は、修正の適用は確認できているが実機（Windows/Chrome）での
  最終見た目確認は移管元で未実施。
- 起動用の `.bat` スクリプト（Windows向け）は今回の移管対象に含めていない
  （元の `.bat` には既知の表示バグがあり、かつ未提供のため）。必要であれば
  `python r19_site_organizer_20260817_01.py` を実行するだけの簡易batを別途作成する。
- `sites_list_*.json` の生成方法が未確認（上記セットアップ手順3を参照）。
