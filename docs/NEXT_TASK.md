# Next Task

## Session Management

- Project Name: Youtube Manager 統合開発環境
- Previous Session: S04（会社PC→自宅PC環境移管・全ツール ＋ iPhone公開システム構築）
- Next Session Number: S05
- Recommended Session Title: Youtube Manager 統合開発環境 S05 -（ユーザー指示待ち）

## Objective

**未定。ユーザーから次の指示を受けること。** 推測でタスクを決めないこと。

S04で会社PC→自宅PC移管を全ツールへ拡大して完遂し、iPhoneでの閲覧システム（`youtube-summary-viewer`＋GitHub Pages＋`publish_to_iphone.bat`）も構築・実機確認済み。残る候補はあるが、優先順位は越智さんの判断による。

## Background

- 前回までの完了内容・現状の課題: `docs/PROJECT_STATUS.md`の「5. Current Status」「6. Known Issues」を参照
- 設計判断の根拠・不採用案:
  - `docs/decisions/0001-glasp-batch-trigger-detect-redesign.md`（バッチ2フェーズ化。S03で実装済み）
  - `docs/decisions/0002-google-challenge-detect-and-suspend.md`（確認画面の検知・待機方針）

## 候補（越智さんが選ぶ材料。こちらから着手しないこと）

以下はS04終了時点で把握している未着手項目である。**優先順位は未確定。**

### A. 環境移管の残確認

- `schedule_manager.py --apply`による定時自動実行の登録が自宅PCでまだ未実施・未確認（`schedule.json`の`working_dir`はS04で自宅PCパスへ修正済み）
- OAuth資格情報（`credentials.json`/`token.pickle`・`credentials_project2.json`/`token_project2.pickle`）が`Youtube_List_Setup.py`・`Youtube_Channel_analizer.py`で自宅PC上で実際に機能するかの確認（コピー済みだが機能確認は未完了）
- `wmic os get localdatetime`ベースのログタイムスタンプ生成が、`wmic`廃止済みのWindowsで壊れている（複数BATファイル。ログファイル名が乱れるだけで実行自体は失敗しない。deferred・非ブロッキング）

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
- `google.generativeai`から`google.genai`への移行（旧SDKは更新終了済み。`FutureWarning`抑制が効いていない件もこれで解消見込み）

### D. S04で新たに見えた候補

- `config.json.example`（または同等のスキーマ文書）の追加。`config.json`自体はリポジトリ管理外（秘密情報を含むため意図的）だが、`paths`セクションの期待キー（`output_dir`・`consolidation_batch`）がどこにも自己文書化されておらず、S04では`consolidation_batch`未設定に起因する不具合につながった
- `consolidated_html_summary_manager_20260*.py`（旧版17個）の削除判断。バージョン管理はGitへ移行済みで実害はないが、リポジトリ内の残骸として指摘済み
- `publish_to_iphone.bat`を定時自動チェーンへ組み込むかどうか。現時点では明示的に依頼されておらず、手動トリガー運用のまま（S04では「1クリック化」の依頼のみに対応した）

## Scope

### Files That May Be Changed

- 未定（タスク確定後に決める）

### Files That Must Not Be Changed

- `consolidated_html_summary_manager_20260*.py`（旧版17個。削除するかどうかの判断自体はD.の候補だが、判断が出るまで内容は変更しない）

## Completion Criteria

- 未定（タスク確定後に決める）

## Known Risks

- 本ツールはSelenium+Chrome debugポート+Outlook COM前提のため、**クラウド環境では実動作確認ができない**。構文検証・静的チェック・シミュレーションのみ実施し、実機確認は越智さんのローカル環境に依存する
- S03・S04で判明した落とし穴は`docs/PROJECT_STATUS.md`の「落とし穴カタログ」各項を参照すること（BATから`python`を裸で呼ぶと制御が戻らない、config.jsonがコード既定値に勝つ、PowerShellとcmd.exeの構文非互換、Chromeインストール先の違い、BATのrem/echo行の丸括弧がcmd.exeの構文解析を壊す、for/f＋バックティック＋python -cの入れ子引用符が壊れやすい、JSONの重複キーは後勝ちで前が静かに消える、等）
- `CONSOLIDATION_BATCH`（統合バッチ自動起動）は既定値が空文字で、`config.json`の`paths.consolidation_batch`を設定しないと無言でスキップされる。今後別PCへ再移管する場合はこの設定を移管手順に含めること

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
