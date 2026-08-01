# NEXT_TASK

## Project Name
RSS オーガナイザー開発

## Previous Session
S01 - 読み込みフィードのシンプル化（完了）

## Next Session
S02（候補）

## Next Session Title（候補）
RSS オーガナイザー開発 S02 - AI企業・研究機関ブログのフィード疎通確認

## Background
S01でTab3「AI最先端フィード」の読み込み過多に対応し、`ai_feed_history.json`（直近1週間・606件）の分析を通じて以下が確定した。

- 論文・研究カテゴリ: arXiv4フィード（全体の57%を占めていた）・Papers with Code（フィード自体がSSLハンドシェイク失敗で機能停止）とも取得停止、0件に確定
- 英語メディア(5)・AI企業ブログ(6)・日本語メディア(4)は件数維持
- 最終構成: 計15フィード（`rss_organizer_20260801_01.py`）

分析の過程で副次的に判明した点として、AI企業・研究機関ブログ6フィードのうちOpenAI(11件)以外（Anthropic, Google DeepMind, Meta AI, Hugging Face, DeepLearning.AI Batch）が過去1週間で1件も取得されていなかった。S01のスコープ外のため未調査のまま。

## Candidate Scope（次セッション開始時にユーザーへ確認）
- Anthropic/DeepMind/Meta/Hugging Face/DeepLearning.AI Batchの各フィードURLが生きているか確認（Papers with Codeと同様に`feedparser.parse()`で`bozo`/例外を確認する方法が使える）
- 生きていないフィードがあれば、正しいURLへの差し替え or 取得停止を検討
- その他、ユーザーからの新規依頼（実際に運用してみての追加調整など）

## Files That May Be Changed
- `rss_organizer/rss_organizer_20260801_01.py` の後続バージョン（例: `rss_organizer_YYYYMMDD_01.py`、新規作成・旧版は残置）
- `rss_organizer/README.md`
- `rss_organizer/CHANGELOG.md`

## Files That Must Not Be Changed
- `rss_organizer/rss_organizer_20260708_02.py`, `rss_organizer_20260801_01.py`（旧バージョンとして保持、削除・上書き禁止）
- 他プロジェクト（`rtocs_organizer/`, `youtube_summary_list_*.py`, `po_database_organizer/`, `shareflex_dashboard/`）は無関係のため変更しない

## Task
セッション開始時にユーザーへ「AI企業ブログの疎通確認を行うか」「他に調整したい点はあるか」を確認し、対応する。

## Completion Criteria
- 未確認（ユーザー確認後に確定）

## Required Tests
- Python構文チェック（`python -m py_compile`）
- 変更箇所の静的ロジック確認（GUI実機テストは本セッション環境では不可のため対象外。フィード疎通確認はユーザーにWindows実機での`feedparser.parse()`実行を依頼する方式が有効）

## Known Risks
- 本ツールはWindows+Playwright+Tkinter前提のため、クラウドセッションでは実機動作確認ができない
- 本セッション環境からは arxiv.org・paperswithcode.com 等の外部RSS URLへ直接アクセスできない（ネットワークポリシーでブロック）。同様のブロックが他ドメインでも起こりうるため、疎通確認はユーザーのWindows実機に依頼する前提で計画する
