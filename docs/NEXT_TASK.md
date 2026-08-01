# NEXT_TASK

## Project Name
RSS オーガナイザー開発

## Previous Session
S01 - 読み込みフィードのシンプル化（完了）

## Next Session
S02（候補）

## Next Session Title（候補）
RSS オーガナイザー開発 S02 - AI最先端フィードのソース選定調整

## Background
S01でTab3「AI最先端フィード」の固定フィードリスト（`AI_FEED_URLS`）を20件→14件に削減した（`rss_organizer_20260801_01.py`）。除外するフィードの選定基準（AI専門度・他フィードとの内容重複度）はユーザーの明示的な合意を得られないままClaude Codeの判断で実施しており、実際に使ってみて狙いと異なる可能性がある。

除外した6フィード:
- 英語メディア: The Verge AI, Wired AI
- 論文・研究: arXiv cs.CL, arXiv cs.CV
- 日本語メディア: Publickey, テクノエッジ

## Candidate Scope（次セッション開始時にユーザーへ確認）
- 削減後の14フィード構成で実際に運用してみて、まだ多い/少ない、ジャンルが偏っている等の調整依頼があれば対応
- Tab1「キーワード探索」（`SITE_CONFIG`: note/Qiita/Zenn）の絞り込みが必要か確認
- その他、ユーザーからの新規依頼

## Files That May Be Changed
- `rss_organizer/rss_organizer_20260801_01.py` の後続バージョン（例: `rss_organizer_YYYYMMDD_01.py`、新規作成・旧版は残置）
- `rss_organizer/README.md`
- `rss_organizer/CHANGELOG.md`

## Files That Must Not Be Changed
- `rss_organizer/rss_organizer_20260708_02.py`, `rss_organizer_20260801_01.py`（旧バージョンとして保持、削除・上書き禁止）
- 他プロジェクト（`rtocs_organizer/`, `youtube_summary_list_*.py`, `po_database_organizer/`, `shareflex_dashboard/`）は無関係のため変更しない

## Task
セッション開始時にユーザーへ「S01の削減結果で問題ないか、追加調整が必要か」を確認し、対応する。

## Completion Criteria
- 未確認（ユーザー確認後に確定）

## Required Tests
- Python構文チェック（`python -m py_compile`）
- 変更箇所の静的ロジック確認（GUI実機テストは本セッション環境では不可のため対象外）

## Known Risks
- 本ツールはWindows+Playwright+Tkinter前提のため、クラウドセッションでは実機動作確認ができない
- フィード選定はユーザーの実際の情報ニーズに依存するため、S01の判断が最適とは限らない
