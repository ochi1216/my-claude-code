# CHANGELOG — rss_organizer

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

## [20260801_01] - 2026-08-01

**追加ファイル:** `rss_organizer_20260801_01.py`（`20260708_02`からのコピー＋変更。旧版はそのまま残置。VERSION定数 `"20260801_01_01"`）
**変更ファイル:** `README.md`

ユーザーより「AI最先端フィード（Tab3）分が毎回大量に読み込まれてしまうので、ソースを限定したい」との要望があり対応:

- `AI_FEED_URLS` を20フィードから14フィードに削減。カテゴリごとに重複性・網羅性の低いソースを間引いた:
  - 英語メディア（5→3）: The Verge AI, Wired AIを除外（AI以外の一般テック記事の比率が高いため）。TechCrunch AI, VentureBeat AI, MIT Technology Reviewは維持
  - AI企業・研究機関ブログ（6→6、変更なし）: OpenAI/Anthropic/DeepMind/Meta/Hugging Face/DeepLearning.AIの一次情報源は元々高シグナルなためそのまま維持
  - 論文・研究（5→3）: arXiv cs.CL, arXiv cs.CVを除外（arXiv cs.AI/cs.LGと内容が重複しやすいため）。arXiv cs.AI, arXiv cs.LG, Papers with Codeは維持
  - 日本語メディア（4→2）: Publickey, テクノエッジを除外（AI専門ではない一般テックメディアのため）。ITmedia AI+, Ledge.aiは維持
- `AI_FEED_ARXIV_MAX`（arXiv 1フィードあたりの取得上限）を15件→8件に削減。残したarXiv 2フィード分の流入量も併せて抑制
- 除外したフィードの選定はClaude Codeによる判断（重複性・AI専門度合いを基準に選定）。ユーザーの実際の好みと異なる場合は、`AI_FEED_URLS` の該当カテゴリに戻す/追加するだけで調整可能

## [20260708_02] - 2026-08-01（リポジトリ初回登録）

**追加ファイル:** `rss_organizer_20260708_02.py`（ユーザー提供のベースライン。VERSION定数 `"20260708_02_01"`）, `README.md`, `CHANGELOG.md`

RSS オーガナイザー開発プロジェクトをこのリポジトリに新規登録。既存の3タブ構成（キーワード探索／フォローnote／AI最先端フィード）と `-auto` ステルス実行モードを含む、S01開始時点の最新版をそのままベースラインとして取り込んだ。コード変更は行っていない。
