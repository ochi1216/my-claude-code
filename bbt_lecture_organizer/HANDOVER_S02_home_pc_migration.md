# BBT レクチャーオーガナイザー — S02 自宅PC移管 引継ぎ資料

作成: 2026-10-15 / 作成者: Claude Code（S01） / 対象: S02「BBT レクチャーオーガナイザー S02 自宅PC移管」

> **この資料は自己完結です。** S02 は別リポジトリ（`home-pc-workspace`）で作業するため、
> `my-claude-code` の `docs/` や `CLAUDE.md` は参照できない前提で書いています。
> **推測で埋めていません。不明点は「未確認」「要確認」と明記しています。**

---

## 1. 要点（これだけ読めば状況が分かる）

- BBTサマリは、BBT757から講義トランスクリプトを取り、Gemini で要約して HTML を作るツール。
- S01 で Gemini API をプロキシ経由に対応した（会社PCから直接アクセスが遮断されたため）。
- S02 では、このツールを**自宅PCの `home-pc-workspace` へ移管**する。
- **コードに会社PCの絶対パスが6箇所ある。** そのまま自宅PCで動かすと誤った場所へ出力される恐れがある（5節）。
- 会社PCで起きた強制終了 `Tcl_AsyncDelete` の**原因は未特定**。診断ログを入れて様子見中（3節）。
- 要約履歴 `bbt_summary_history.json`（375件）は Git の外にある。**移さないと全件を再要約する**（6節）。

## 2. S01 の成果

| リビジョン | 内容 | 状態 |
|---|---|---|
| `BBT_lecture_script_getter_20260804_01.py` | claude.ai 時代の最終版（旧SDK `google.generativeai` 直呼び） | 保持 |
| `…_20260817_01.py` | **Gemini プロキシ化**。旧SDK互換シムで `genai` 名前空間ごと差し替え | main にマージ済み（`d1c9b53`） |
| `…_20260817_02.py` | `gc.collect()` 4箇所。Tcl_AsyncDelete の予防措置（**効果は未確認**） | PR #26（未マージ） |
| `…_20260817_03.py` | `faulthandler` 追加。強制終了時に `crash_traceback.log` へ全スレッドのトレースバックを出力 | PR #26（未マージ） |

- PR #26: https://github.com/ochi1216/my-claude-code/pull/26
- ブランチ: `claude/bbt-gemini-proxy-yjyjoi` → `main`
- 場所: `my-claude-code` リポジトリの `bbt_lecture_organizer/`
- 詳細は同フォルダの `CHANGELOG.md` と `README.md`。調査結果は `TOOLSHEET_bbt_lecture_organizer.md`。

### 構造（変更点だけ）

- Gemini の呼び出しは `GeminiAutomator`（L2381〜）に集約。**プロンプトテンプレート3種と要約ロジックは無変更。**
- ファイル冒頭にシム（`_CommonGenerativeModel` 等）。`gemini_client.generate_advanced()` を呼ぶ。
- `gemini_client.py` は `..\common` → `..\..\common` の順に自動探索。環境変数 `GEMINI_COMMON_DIR` で上書き可。
- `GEMINI_API_KEY` と `GEMINI_PROXY_URL` の**どちらか一方があれば**起動する。

## 3. 未確認・未解決（重要）

1. **`Tcl_AsyncDelete: async handler deleted by the wrong thread` の原因は未特定。**
   - 会社PCで `_01` 実行中に発生（`[1/29]` のトランスクリプト抽出直後）。
   - 最小再現では同じエラーで落ちるが、**本物の `run()` → `_run_new()` を実tkinterで動かしても `_01` で再現しなかった。**
   - `_02` の `gc.collect()` が効くかは**未確認**。`_03` の診断ログで次回に特定する。
   - 発生したら `crash_traceback.log` の末尾を見る。落ちたスレッドと行が分かる。
2. **プロキシ経由で Gemini の応答が返るところは、実機で未確認。** 会社PCのログには「プロキシ経由で呼び出します」まで出たが、その後の強制終了で要約まで届いていない。
3. **`_03` の `crash_traceback.log` が実機で作られることは未確認。**
4. 実機（Windows＋Chrome＋Selenium）での動作確認は、Claude Code の環境からはできない。

## 4. 会社PC固有パス（`…_20260817_03.py` の行番号）

| 行 | 対象 | 現在値（会社PC） | 自宅PCでの扱い |
|---|---|---|---|
| L1872 | `SummaryHistoryManager.HISTORY_FILE` | `C:\Users\nx023836\Documents\PythonScripts\bbt\bbt_summary_history.json` | **要決定**（スクリプト位置基準が候補） |
| L2867 | `SimpleIntegrator.CHROME_PATH` | `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe` | **自宅PCの実パスは未確認** |
| L2868 | `CHROME_USER_DATA_DIR` | `C:\Users\nx023836\AppData\Local\ChromeDebugProfile9222` | 要決定。**新しいプロファイルなら BBT に再ログインが必要** |
| L2877 | `output_dirs[0]` | `C:\Users\nx023836\Documents\PythonScripts\bbt\bbt_lecture_summary` | 要決定 |
| L2878 | `output_dirs[1]` | `C:\Users\nx023836\Nexperia\My Private - Documents\Summary` | **ユーザー指定: 自宅PCの `C:\Users\ochi1\OneDrive\ドキュメント\PythonScripts\home-pc-workspace` に相当** |
| L3487 | 資料PDFの移動先 `target_dir` | 同上（Summary） | 同上 |

- 該当なし（移植可能）: L321 と L3486 の `~\Downloads` は `expanduser` なので問題ない。
- `CHROME_DEBUG_PORT = 9222` は共通。

### ⚠️ 最大の落とし穴（RSS Organizer 移管の前例）

会社PCの絶対パスが残ったまま別PCで動かすと、`os.makedirs` が実在しないユーザー名のフォルダを
作り、**エラーも出ないまま誤った場所へ HTML を出力する。** 本ツールにも `os.makedirs` が3箇所ある
（L1895 履歴、L2675 出力先、L3526 資料PDF移動先）。
**`my-claude-code` 側のコードを自宅PCで直接動かさないこと。**

## 5. 環境の違いと Gemini の呼び出し方式（S02 で要決定）

- 自宅PCは Gemini API に**直接つながる見込み**（プロキシ本体が自宅PC側にあるため）。ただし本ツールで**未確認**。
- 現状のコードは `gemini_client.py` が見つからないと**AI呼び出し時に失敗する**（起動はできる）。
- 選択肢（S02 の設計議論で決める）:
  - **A**: シムと `gemini_client.py` を維持する。移管先に共通モジュールの置き場所が必要。
  - **B**: 自宅PCでは直接呼び出しだけにし、シムを外して単純化する。
- 判断材料: 会社PCでも使い続けるか（8節 Q5）。使い続けるなら A の方が両対応で安全。

## 6. 引き継ぐデータ（Git の外）

| ファイル | 内容 | 注意 |
|---|---|---|
| `bbt_summary_history.json` | 要約済み program_id（**375件**） | 無いと全件再要約。要約済み3件連続での早期終了も効かない |
| `bbt_lecture_summary\` と `…\Summary\` の HTML | 過去の要約レポート | 移すかは要判断 |

- **リポジトリにコミットしない。** 業務データの扱いは移管先のルールに従う。
- 履歴が空だと、要約済み3件連続での早期終了が働かず、**全ページをスキャンする**（全件が未要約扱いになる）。

## 7. 運用ルール（BBT移管資料 §4 から継続）

- **3フェーズ**: Phase1 設計提案（コード生成禁止）→ Phase2 監査（承認待ち）→ Phase3 実装（Change Manifest・diff・完全版関数）。
- 承認済みスコープ外が必要になったら「Change Request」として提示し、承認を待つ。
- UI規約: ダークテーマ（bg `#1a1a2e` / accent `#e94560`）、絵文字は Unicode 直書き、ログは日本語＋絵文字。
- 過去の重大バグ: `ContentListScraper` と `SearchResultScraper` は同名メソッドを持ち、手動パッチで中身が入れ替わる事故が2回あった。**AST でメソッド構成を機械検証する。**
- `.py` は完全ファイルで確認する。diff だけで判断しない。
- 移管先リポジトリに独自の `CLAUDE.md` があれば、**最初にそれを読み、優先する。**

## 8. S02 冒頭で越智さんに確認すること（未確認）

| # | 質問 | 背景 |
|---|---|---|
| Q1 | 移管先は `home-pc-workspace` で正しいか | 依頼文に `home-pc-workplace` と `home-pc-workspace` が混在。前例（RSS）は `ochi1216/home-pc-workspace` |
| Q2 | 自宅PCのクローンフォルダの実パスは | 依頼文は `C:\Users\nx023836\Documents\PythonScripts\my-claude-code` だが、`nx023836` は会社PCのユーザー名（自宅は `ochi1`）。Summary の移管先 `C:\Users\ochi1\OneDrive\ドキュメント\PythonScripts\home-pc-workspace` がクローン自体かも要確認 |
| Q3 | 移管先のフォルダ名は | RSS の前例は `rss-organizer/`（ハイフン）。`bbt-lecture-organizer/` か |
| Q4 | バージョン管理は | RSS は固定ファイル名＋Git に移行した。BBT も同様か、`_yyyymmdd_NN` を続けるか |
| Q5 | 会社PCでも使い続けるか | 続けるなら `my-claude-code` 側の扱いと、5節の A/B 判断に影響 |
| Q6 | 履歴・過去HTMLの引継ぎ方法 | 6節 |
| Q7 | Gemini 呼び出しは A か B か | 5節 |
| Q8 | Tcl_AsyncDelete の調査を S02 に含めるか | 自宅PCで再現するかも未確認 |
| Q9 | 自宅PCの Chrome パスと、デバッグ用プロファイルの場所 | 4節 |
| Q10 | PR #26 を先にマージするか | 移管元の最終状態が確定する |

## 9. 作業の進め方（推奨）

1. 移管先の `CLAUDE.md` と `docs/` を読む。RSS の移管記録（`rss-organizer/docs/PROJECT_STATUS.md`）を前例として確認する。
2. 8節の質問を一括で確認する。
3. **Phase1**: 移管先の構成案（フォルダ・パスの外部化方式・履歴の置き場・Gemini の A/B）を提示する。
4. **Phase2**: 4節の6箇所と `os.makedirs` 3箇所のリスクを監査し、承認を得る。
5. **Phase3**: 実装。**パスの外部化は、スクリプト位置基準か設定ファイルかを承認後に決める。**
6. `my-claude-code` 側に「移管済み」の注記を残す（RSS の前例に倣う）。

## 10. 持ち込むファイル

- `BBT_lecture_script_getter_20260817_03.py`（最新版。ただし PR #26 未マージなら `my-claude-code` のブランチから取得）
- 本資料、`CHANGELOG.md`、`README.md`、`TOOLSHEET_bbt_lecture_organizer.md`
- `test_gemini_proxy_20260817_01.py`（Gemini 関連 77〜79項目のテスト）
- 共通ガイド `HANDOVER_gemini_proxy_common.md`（Gemini プロキシの背景。5節の判断に必要）
- 会社PCから: `bbt_summary_history.json`

## 11. S02 開始プロンプト

```
BBT レクチャーオーガナイザー S02 自宅PC移管 を始めます。

まず、移管先リポジトリ（ochi1216/home-pc-workspace）の CLAUDE.md と docs/ を読んでください。
次に、添付の HANDOVER_S02_home_pc_migration.md を最後まで読み、8節の質問（Q1〜Q10）を
一括で私に確認してください。推測で進めないでください。

進め方は3フェーズ厳守です。Phase1（設計提案）ではコードを生成しません。
「●３．承認します」と明示するまで、コードを生成しないでください。

前提:
- 対象ツール: BBT レクチャーオーガナイザー（BBT_lecture_script_getter_20260817_03.py）
- 会社PCの絶対パスが6箇所あります（資料4節）。自宅PCでそのまま動かさないでください。
- 要約履歴 bbt_summary_history.json（375件）は Git の外にあります。
- 実機（Windows＋Chrome＋Selenium）の動作確認は私が行います。
```
