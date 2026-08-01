# RSS Organizer

RSS/Atomフィードを複数ソース（note/Qiita/Zennのキーワード検索、フォロー中のnote作者、AI最先端フィード固定リスト）から収集し、Gemini APIで要約してHTMLレポートを生成するWindows向けTkinterデスクトップツール。

## 必要要件

- Python 3.9以上（Windows）
- Google Chrome（Playwright経由でChromiumを操作）
- Gemini APIキー

## 主な依存パッケージ

```
pip install google-generativeai feedparser playwright deep-translator flask flask-cors keyring
playwright install chromium
```

（`deep-translator` は英語タイトルの自動翻訳、`flask`/`flask-cors` はオンデマンド要約用ローカルAPIサーバー、`keyring` はnote自動同期のパスワード保存に使用。いずれも未インストールでも本体は動作するが、該当機能のみ無効化される。）

## 設定ファイル

初回起動時に以下が自動生成される（Git管理対象外）。

- `rss_manager_config.json` — Gemini APIキー・モデル・note連携設定
- `read_history.json` / `ai_feed_history.json` — 既読履歴
- `keywords.txt` / `my_keywords.txt` — Tab1（キーワード探索）で使うキーワード
- `followed_note_authors.txt` — Tab2（フォローnote）の対象作者URL一覧
- `recommend_config.json` — レコメンド設定

## 起動方法

```
python rss_organizer_20260801_01.py
```

`-auto` 引数を付けるとGUIを表示せず、Tab2→Tab1→Tab3の順に全タブを自動取得→統合→要約→レポート生成→ブラウザ表示→既読化まで一括実行する（ステルスモード）。

## 3タブ構成

| Tab | 内容 | 読み込み元 |
| --- | --- | --- |
| 🔎 キーワード探索 (Tab1) | `my_keywords.txt`/`keywords.txt` のキーワードで note/Qiita/Zenn のハッシュタグRSSを横断取得 | `SITE_CONFIG` |
| 👤 フォローnote (Tab2) | `followed_note_authors.txt` に登録した作者のnote RSSのみ取得 | 作者ごとのRSS |
| 🤖 AI最先端フィード (Tab3) | 固定登録されたAI関連フィードを並列取得 | `AI_FEED_URLS`（英語メディア3/AI企業・研究機関ブログ6/論文・研究3/日本語メディア2、計14フィード。`20260801_01`で20→14に削減。arXivの取得上限 `AI_FEED_ARXIV_MAX` も15→8に削減） |

## 既知の制限（今回のスコープ外）

- `HTMLReportGenerator.folder` の出力先パスがユーザー名を含む形でハードコードされている。
- note自動同期（`NoteFollowingSyncer`）はPlaywrightでのログイン操作に依存しており、note側のページ構造変更で動作しなくなる可能性がある。

## バージョン履歴

変更履歴は [`CHANGELOG.md`](CHANGELOG.md) を参照。
