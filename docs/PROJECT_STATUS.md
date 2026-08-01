# PROJECT_STATUS — RSS オーガナイザー開発

最終更新: S01一部完了（2026-08-01、論文・研究とAI_FEED_ARXIV_MAXは確認中）

## Project Overview

RSS/Atomフィードを複数ソースから収集し、Gemini APIで要約してHTMLレポートを生成するWindows向けTkinterデスクトップツール。3つのタブ（キーワード探索／フォローnote／AI最先端フィード）から記事を集約し、1本のHTMLレポートとして出力する。

## Repository Structure

```
rss_organizer/
  rss_organizer_20260708_02.py   # ベースライン（S01開始時点でユーザーより提供された最新版, VERSION="20260708_02_01"）
  rss_organizer_20260801_01.py   # S01成果物（AI最先端フィードのソース削減, VERSION="20260801_01_01"）
  README.md
  CHANGELOG.md
docs/
  PROJECT_STATUS.md
  SESSION_HISTORY.md
  NEXT_TASK.md
CLAUDE.md
```

## Current Functions

`rss_organizer_20260801_01.py`（最新版, 約3,356行）内の主要クラス:

- `RSSFeedManager` — キーワード検索（note/Qiita/Zenn）・フォローnote・AI最先端フィードの取得と既読履歴管理
- `NoteFollowingSyncer` — Playwrightでnote.comにログインし、フォロー作者一覧を `followed_note_authors.txt` に同期
- `RSSSummarizer` — Playwrightで記事本文を取得し、Gemini APIで要約（Phase1: タイトル・要旨・キーワード／Phase2: オンデマンドで結論・主なポイント）
- `HTMLReportGenerator` — 収集・要約結果を1本の自己完結HTMLレポートとして出力
- `RSSManagerGUI` — Tkinter GUI本体。3タブ構成:
  - Tab1「🔎 キーワード探索」— `SITE_CONFIG`（note/Qiita/Zenn）× `my_keywords.txt`/`keywords.txt` のキーワードでハッシュタグRSSを横断取得
  - Tab2「👤 フォローnote」— `followed_note_authors.txt` に登録された作者のnote RSSのみ取得
  - Tab3「🤖 AI最先端フィード」— `AI_FEED_URLS` に固定登録された20フィード（英語メディア5／AI企業・研究機関ブログ6／論文・研究5／日本語メディア4）を並列取得。英語メディア・AI企業ブログ・日本語メディアは件数維持が確定。論文・研究（`AI_FEED_ARXIV_MAX`含む）は削減方針を検討中で現状は元の値のまま据え置き
- `-auto` 起動引数でGUIを隠し、Tab2→Tab1→Tab3の順で全タブを自動実行→統合→要約→レポート生成→ブラウザ表示→既読化まで一括実行するステルスモードあり

## Confirmed Specifications

- 記事の表示対象は `ARTICLE_DAYS_LIMIT`（7日）以内の記事のみ
- `BLOCK_DOMAINS` によりX/Twitter、Facebook系、Temuドメインの記事は除外
- 既読履歴はTab1/Tab2共通（`read_history.json`）とAIフィード専用（`ai_feed_history.json`）で分離管理
- HTMLレポート出力先は `C:\Users\nx023836\Nexperia\My Private - Documents\Summary`（`HTMLReportGenerator.folder` にハードコード）
- Gemini モデルは既定 `gemini-2.5-flash`

## Current Status

- ユーザーから提供されたベースライン（`rss_organizer_20260708_02.py`、v20260708_02_01）をリポジトリに初回登録済み。
- ユーザー依頼「AI最先端フィード（Tab3）が毎回大量に読み込まれるのでソースを限定したい」に対応中。`rss_organizer_20260801_01.py`（v20260801_01_01）を作成し、最初はClaude Code独断で20フィード→14フィードに削減したが、ユーザーから「勝手に進めないでください」と指摘を受け訂正。
  - 確定: 英語メディア（5件）・AI企業・研究機関ブログ（6件）・日本語メディア（4件）は元の件数を維持
  - 未確定（要検討）: 論文・研究フィード構成（現状arXiv cs.AI/cs.LG/cs.CL/cs.CV + Papers with Code の5件）と `AI_FEED_ARXIV_MAX`（現状15）。ユーザーは過去の実際の投稿数実績を見て判断したい意向だが、リポジトリ内に実行履歴なし・本セッション環境からarXiv等へ直接アクセス不可のため、実測データを提示できていない。一般的傾向（未検証）の参考値のみ提示済み。判断が出るまで論文・研究とAI_FEED_ARXIV_MAXは元の値のまま。

## Known Issues

- 論文・研究フィードの構成と `AI_FEED_ARXIV_MAX` の最終決定が未了。ユーザーから実際の`ai_feed_history.json`等の実績データ提供を待っている状態。
- 本ツールはWindows+Playwright+Tkinter前提のため、本セッション（クラウド実行環境）ではGUI起動・実ネットワーク経由のフィード取得テストが未実施（構文チェックと静的diff確認のみ実施済み）。本セッション環境のネットワークポリシー上、arXiv/Papers with Code等外部RSSへの直接アクセスも不可（`rss.arxiv.org`宛CONNECTが403で拒否される）。
- `HTMLReportGenerator.folder` および `note` ログイン情報の一部（`nx023836` ユーザー名）がハードコードされている（既存仕様、今回のスコープ外）

## Test and Execution

- 実行環境: Windows + Tkinter + Playwright（Chromium）。本セッション（クラウド実行環境）ではGUI起動・実ネットワーク経由のフィード取得テストは未実施。
- 実施可能なテスト: Pythonの構文チェック（`python -m py_compile`）、静的なロジック確認、必要であれば軽量な単体関数のドライラン。

## Important Restrictions

- APIキー・パスワード・認証情報はコミットしない（`config.json` 等は `.gitignore` 対象。RSSオーガナイザー用の設定ファイルも同様に扱う）
- 既存の未関係な機能・UIを無関係に変更しない
- 旧バージョンファイルは削除・上書きしない
