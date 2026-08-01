# NEXT_TASK

## Project Name
RSS オーガナイザー開発

## Current Session
S01（継続中）

## Current Session Title
RSS オーガナイザー開発 S01 - 読み込みフィードのシンプル化

## Current Objective
Tab3「AI最先端フィード」の読み込み過多に対応する。ユーザー指示により英語メディア(5)・AI企業ブログ(6)・日本語メディア(4)は件数維持で確定。残る論文・研究フィード構成と`AI_FEED_ARXIV_MAX`は、過去の実際の投稿数実績データを見た上で判断する方針。

## Background
`rss_organizer_20260801_01.py` は現状、ベースライン(`20260708_02.py`)とコメントを除き同じ設定（`AI_FEED_URLS`全20件、`AI_FEED_ARXIV_MAX`=15）に戻っている。論文・研究カテゴリ（arXiv cs.AI/cs.LG/cs.CL/cs.CV, Papers with Code）だけが唯一の未確定事項。

過去実績データの取得を試みたが以下の理由で本セッションでは取得不可だった:
- リポジトリ内に`ai_feed_history.json`等の実行履歴ファイルなし（Windows実機側でGit管理対象外として生成される仕様）
- 本セッション環境のネットワークポリシーでarXiv/Papers with Codeへの直接アクセスがブロックされている（`rss.arxiv.org`宛CONNECTが403）

一般的傾向（未検証・参考値）として提示済み: arXiv cs.AI/cs.LG/cs.CVは1日あたり新着100件超、cs.CLは50〜100件程度、Papers with Codeはトレンド抽出のため相対的に少数。

## Scope
- 論文・研究フィードの構成（現状5件を維持するか、一部除外するか）
- `AI_FEED_ARXIV_MAX`（現状15）を実績に応じてどう設定するか

## Files That May Be Changed
- `rss_organizer/rss_organizer_20260801_01.py`（`AI_FEED_URLS`の「論文・研究」および`AI_FEED_ARXIV_MAX`のみ）
- `rss_organizer/README.md`
- `rss_organizer/CHANGELOG.md`
- `docs/PROJECT_STATUS.md` / `docs/SESSION_HISTORY.md`（決定後、最終状態を反映）

## Files That Must Not Be Changed
- `rss_organizer/rss_organizer_20260708_02.py`（旧バージョンとして保持、削除・上書き禁止）
- `AI_FEED_URLS`の英語メディア・AI企業ブログ・日本語メディア（件数維持で確定済み）
- 他プロジェクト（`rtocs_organizer/`, `youtube_summary_list_*.py`, `po_database_organizer/`, `shareflex_dashboard/`）は無関係のため変更しない

## Task
ユーザーから過去の実際の投稿数実績（`ai_feed_history.json`の中身、または直近のHTMLレポート等）の提供を受けたら、それを基に論文・研究フィード構成と`AI_FEED_ARXIV_MAX`を確定し、`rss_organizer_20260801_01.py`に反映する。

## Completion Criteria
- 論文・研究フィード構成が確定していること（ユーザー合意済み）
- `AI_FEED_ARXIV_MAX`の値が確定していること（ユーザー合意済み）
- 既存機能に意図しない影響がないこと
- 必要なテストを実施すること

## Required Tests
- Python構文チェック（`python -m py_compile`）
- 変更箇所の静的ロジック確認（GUI実機テストは本セッション環境では不可のため対象外）

## Known Risks
- 実績データが得られない場合、一般的傾向のみに基づく判断となり精度が落ちる
- 本ツールはWindows+Playwright+Tkinter前提のため、クラウドセッションでは実機動作確認ができない
