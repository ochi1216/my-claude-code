# Next Task

## Session Management

- Project Name: Youtube Manager 統合開発環境
- Previous Session: S04（会社PC→自宅PC環境移管、youtube_summary_list.py単体）
- Next Session Number: S05
- Recommended Session Title: Youtube Manager 統合開発環境 S05 -（ユーザー指示待ち）

## Objective

**未定。ユーザーから次の指示を受けること。** 推測でタスクを決めないこと。

S04でyoutube_summary_list.py単体の会社PC→自宅PC移管が実機で成功した。
残る3ツールの移管・自動実行設定など継続候補はあるが、優先順位は越智さんの判断による。

## Background

- 前回までの完了内容・現状の課題: `docs/PROJECT_STATUS.md`の「5. Current Status」「6. Known Issues」を参照
- 設計判断の根拠・不採用案:
  - `docs/decisions/0001-glasp-batch-trigger-detect-redesign.md`（バッチ2フェーズ化。S03で実装済み）
  - `docs/decisions/0002-google-challenge-detect-and-suspend.md`（確認画面の検知・待機方針）

## 候補（越智さんが選ぶ材料。こちらから着手しないこと）

以下はS04終了時点で把握している未着手項目である。**優先順位は未確定。**

### A. 環境移管の継続

- 残り3ツール（`consolidated_html_summary_manager.py`・`morning_brief.py`・`Youtube_List_Setup.py`）に残存する会社PC依存パス（`nx023836`ハードコード）の外部化
- 自宅PCでのWindowsタスクスケジューラ設定（`schedule_manager.py`経由）。S04では手動起動のみ確認済みで、定時自動実行は未検証
- 自宅PCの`python`コマンドが3.14を指す件の実害確認（現時点では実機テスト1件成功のみ。継続利用で問題が出ないか要観察）

### B. 運用の継続観察（コード変更なし）

- 1巡目クリック廃止後、日によって2巡目の1回目が通らなくなっていないかを数日分の`glasp_measure.log`で確認する
- `python analyze_glasp_measure.py`で集計できる
- 悪化していれば`config.json`の`glasp.round1_click`を`true`に戻す

### C. 残課題の消し込み

- 朝の1通で同じ動画の複数回失敗が「複数本の失敗」として水増しされる問題（動画IDでの重複排除が未実装）
- Glasp起動の失敗が実機で1本残っている（原因未特定、発生率低）
- `except: pass`（39箇所）・裸の`except:`（46箇所）へのログ追加
- 未使用関数（53/223）と、休眠中の重複`process_multiple_playlists`の削除
- `return`文がfinally節内にある3箇所（SyntaxWarning対象、S04で判明）
- `google.generativeai`から`google.genai`への移行（旧SDKは更新終了済み）

## Scope

### Files That May Be Changed

- 未定（タスク確定後に決める）

### Files That Must Not Be Changed

- `consolidated_html_summary_manager_20260*.py`（旧版17個。履歴として残しているのみ、BATからは未参照）

## Completion Criteria

- 未定（タスク確定後に決める）

## Known Risks

- 本ツールはSelenium+Chrome debugポート+Outlook COM前提のため、**クラウド環境では実動作確認ができない**。構文検証・静的チェック・シミュレーションのみ実施し、実機確認は越智さんのローカル環境に依存する
- S03・S04で判明した落とし穴は`docs/PROJECT_STATUS.md`の「落とし穴カタログ」各項を参照すること（BATから`python`を裸で呼ぶと制御が戻らない、config.jsonがコード既定値に勝つ、PowerShellとcmd.exeの構文非互換、Chromeインストール先の違い、等）

## Start Prompt

```text
セッションタイトル：
Youtube Manager 統合開発環境 S05 -（今回の目的をここに記入）

対象：
- Repository: ochi1216/my-claude-code
- Branch: claude/glasp-batch-two-phase-q8r9ff
- Previous commit: （docs更新コミットのID）

作業開始前に、git status／現在のブランチ／リモートとの差分を確認してください。
問題がなければ git fetch 後、git pull --ff-only を実行してください。

最初に以下を読んでください。
- docs/PROJECT_STATUS.md
- docs/NEXT_TASK.md
- （必要な対象ファイルのみ。リポジトリ全体は調査しない）

今回のタスク：
（ここに記入。未記入のまま着手しないこと）

対象ファイル：
（対象ファイルのみ列挙）

変更禁止：
consolidated_html_summary_manager_20260*.py（旧版17個）

完了条件：
（ここに記入）
```
