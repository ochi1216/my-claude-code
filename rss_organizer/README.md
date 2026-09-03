# RSS Organizer

> ## ⚠️ このプロジェクトは移管済みです。ここでは更新しないでください
>
> **移管先: [`ochi1216/home-pc-workspace`](https://github.com/ochi1216/home-pc-workspace) の `rss-organizer/`**
>
> 2026-08-13 に会社PCから自宅PCへ環境移管し、あわせて管理リポジトリを移しました。
> **以後の開発・修正はすべて移管先で行います。このフォルダは移管時点の記録として残しているだけです。**
>
> このフォルダの内容は移管時点で止まっており、以下が**反映されていません**。
>
> - 会社PC依存のハードコードパス3箇所の外部化（出力先Summaryフォルダ、統合バッチ起動パス2箇所）
> - 設定・履歴ファイルのスクリプト位置基準化
> - Playwright がコンソールタイトルの非ASCII文字で起動できない問題への対処
> - noteフォロー同期からのログイン処理の廃止（未ログインで閲覧可能と判明したため）
> - 固定ファイル名＋Gitによるバージョン管理への移行（`rss_organizer.py`）
>
> **このフォルダのコードを新しいPCで動かそうとしないでください。** 会社PCの
> 絶対パスが埋め込まれており、`mkdir(parents=True)` によって実在しないユーザー名の
> フォルダが作られ、エラーも出ないまま誤った場所へHTMLが出力されます。
>
> 移管の詳細・既知の問題・落とし穴は移管先の `rss-organizer/docs/PROJECT_STATUS.md` を参照してください。

---

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
| 🤖 AI最先端フィード (Tab3) | 固定登録されたAI関連フィードを並列取得 | `AI_FEED_URLS`（英語メディア5/AI企業・研究機関ブログ6/論文・研究0/日本語メディア4、計15フィード）。論文・研究はarXiv 4フィード・Papers with Codeとも取得停止（実績データでarXivが全体の57%を占め主要因と判明、Papers with Codeはフィード自体が機能停止していたためユーザー判断で0件に） |

## 既知の制限（今回のスコープ外）

- `HTMLReportGenerator.folder` の出力先パスがユーザー名を含む形でハードコードされている。
- note自動同期（`NoteFollowingSyncer`）はPlaywrightでのログイン操作に依存しており、note側のページ構造変更で動作しなくなる可能性がある。

## バージョン履歴

変更履歴は [`CHANGELOG.md`](CHANGELOG.md) を参照。
