# Next Task

> このリポジトリは複数プロジェクトを1つのリポジトリで管理しているため、
> プロジェクトごとに節を分けて記載する。

---

# Outlook オーガナイザー開発

## Session Management

* Project Name: Outlook オーガナイザー開発
* Previous Session: S06 - 振り返りタブのスタッフ拡張・Geminiプロキシ移行・起動時ウィンドウ自動配置
* Next Session Number: S07
* Recommended Session Title: Outlook オーガナイザー開発 S07 - AIエージェント化

## Objective

* ユーザーより「より今のニーズに合う形にコードを再構築する」との方針が示された（セッション終了処理の指示時に、次セッション名として「AIエージェント化」が指定された）。
* **具体的な要件・スコープ・対象範囲は本セッション終了時点では未確定**。次セッション冒頭でユーザーから詳細を確認すること（推測で進めない原則）。確認すべき論点の例（未確認、ユーザーへの質問候補）:
  * 「AIエージェント化」が指す具体的な姿（例: tkinter GUIを維持しつつ内部処理をエージェント的に再構成するのか、Claude Code／MCP等の外部エージェント基盤と連携させるのか、Gemini側のエージェント機能（function calling等）を活用するのか、GUI自体を対話型インターフェースに置き換えるのか）。
  * 対象範囲（全タブ共通の基盤を再構築するのか、特定タブ（振り返り・コックピットv2・アクション等）から着手するのか）。
  * 既存の挙動・UI・キャッシュ構造・ファイル命名規則（`outlook_total_organizer_yyyymmdd_NN.py`方式）等をどこまで踏襲するか、どこから刷新してよいか。
  * 段階移行か全面刷新か、既存版との並行稼働の要否。

## Background

* 現在の状態: `outlook_total_organizer/`の最新コミット済み・PRマージ済みリビジョンは`outlook_total_organizer_20260821_02.py`（コミット`e71cba1`、`main`へマージ済み）。
* S06で実施した内容の詳細は`docs/PROJECT_STATUS.md`（3節「起動時ウィンドウ自動配置」含む）・4節・`docs/SESSION_HISTORY.md`のS06セクションを参照。要点:
  * 振り返りタブをOchi氏単独からスタッフ全員（Saji/Nakai/Kajikawa/Oi(Yuto)/Najib/Taizo）へ拡張。KPIゴール軸、人物別HTML分割、議事録テーブルの構造化抽出（`parse_review_minutes_table`）。
  * Gemini API直接遮断を受け、共通プロキシフォールバック機構（`gemini_client.py`）へ全6呼び出し箇所を移行。
  * 起動時にメイン画面を左右分割し、左に本ツール・右にOutlookを自動配置する新機能を実装。長期デバッグの末、DPI仮想化による座標二重適用という根本原因を特定・解消（`ThreadDpiAware`、Win32 API直接操作への全面移行）。
  * アクションダッシュボードの表示期間拡張（`expand_from_cache`）、「任意時間(h)」スピンボックスのグレーアウトUI改善。
* 本ツールは現在、全機能がtkinterのGUIイベント駆動＋都度のGemini API呼び出し（要約・分類）という構成。「AIエージェント化」がどの層を指すのか（UI層／処理オーケストレーション層／AIモデルとのやり取りの方式）によって影響範囲が大きく変わるため、着手前の要件確認が特に重要。

## Scope

### Files That May Be Changed

* 未確定（ユーザーからの要件確認後にスコープを定義する）。従来どおり`outlook_total_organizer/`配下が中心になる見込み。

### Files That Must Not Be Changed

* `po_database_organizer/` 配下一式
* `rtocs_organizer/` 配下一式
* `shareflex_dashboard/` 配下一式
* `youtube_summary_list_20260703_01.py`, `youtube_summary_list_20260711_01.py`, `HANDOVER_youtube_summary_list.md`
* `onenote_report_generator/` 配下一式（別プロジェクト、本ファイル後半のOneNote節を参照）
* `outlook_total_organizer/`配下の既存の全リビジョンファイル（`_20260713_03_01.py`〜`_20260821_02.py`）は削除・上書き禁止（再構築であっても新バージョンファイルとして追加する方針を維持するか、ユーザーに確認すること）
* リポジトリ直下 `README.md`（Outlookオーガナイザーの記載を追加する場合を除き、無関係な変更は行わない）

## Task

1. **最優先**: セッション冒頭で、上記Objectiveの論点についてユーザーに要件確認を行う（AskUserQuestion等）。推測で設計・実装に着手しない。
2. 確認した要件に基づき、設計方針を提示し、ユーザーの承認を得てから実装に着手する。
3. 既存のバージョン管理規則（新バージョンファイルとして追加、CHANGELOG.md更新）・テスト方針（スタンドアロンハーネス、Playwright、実機確認依頼）を踏襲するか、再構築に伴い見直すかもユーザーに確認する。

## Completion Criteria

* 未確定。ユーザーから受けた要件に応じて次セッション内で定義する。

## Required Tests

* 未確定（要件確認後に定義する）。既存の踏襲パターン（構文チェック・diff確認・Outlook非依存ロジックのスタンドアロンハーネス・Playwright・実機確認依頼）は参考情報として維持する。

## Known Risks

* 本プロジェクトのコードはWindows専用（`win32com`/`ctypes.windll`依存）のため、本セッション実行環境（Linuxコンテナ）では実機起動テストができない。実機での動作確認は毎回ユーザーに依頼する運用が定着している。「AIエージェント化」の対象によっては、この制約自体が再構築の動機・論点になる可能性がある。
* 振り返りタブの`analysis_cache/review_monthly/*.json`のうち、過去の各修正より前に生成されたキャッシュは、該当月をチェックボックスで選んで再生成しない限り最新のロジックが反映されない。再構築時にキャッシュ構造自体を変更する場合、移行方針の検討が必要。
* スタッフ名簿(`project_knowledge["staffs"]`)の登録名と、実際のOutlook送信者表示名の表記ゆれは未確認。
* 起動時ウィンドウ自動配置機能は、ユーザーの実機（2モニター、メイン3840×2160@150%）でのみ検証済み。再構築の過程でこの機能に触れる場合は、既存の`ThreadDpiAware`設計（本ツール自身はDPI非対応のまま、Outlook操作のみワーカースレッド限定でDPI Aware化）を壊さないよう注意する。

## Start Prompt

```
CLAUDE.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md を読み込んでください。

対象リポジトリ: ochi1216/my-claude-code
対象ブランチ: 未指定（新規ブランチを作成するか、ユーザーに確認すること。前回セッションの作業ブランチは claude/outlook-s06-manual-date-fix-pzvmr9、最終コミット e71cba19903c2b1ffdc160606d52208c36b44b85（短縮: e71cba1）、main へマージ済み）

現在の状態:
- outlook_total_organizer/outlook_total_organizer_20260821_02.py が最新のコミット済み・PRマージ済みリビジョン
- 未コミット・未完了のファイルはなし（S06はクリーンな状態で終了）

セッションタイトル: Outlook オーガナイザー開発 S07 - AIエージェント化

本セッションの目的: 「より今のニーズに合う形へのコード再構築（AIエージェント化）」。具体的な要件は未確定のため、推測で設計・実装に着手せず、まずユーザーに以下を確認すること:
1. 「AIエージェント化」が指す具体的な姿（UI層／処理オーケストレーション層／AIモデルとのやり取りの方式のどれを指すか）。
2. 対象範囲（全体の基盤再構築か、特定タブからの着手か）。
3. 既存のUI・キャッシュ構造・バージョン管理規則をどこまで踏襲するか。
4. 段階移行か全面刷新か。

要件確認後、設計方針をユーザーに提示し承認を得てから実装に着手する。

変更してはいけない範囲: po_database_organizer/, rtocs_organizer/, shareflex_dashboard/, youtube_summary_list_*.py, HANDOVER_youtube_summary_list.md, onenote_report_generator/、outlook_total_organizer配下の既存の全リビジョンファイル、リポジトリ直下README.md（無関係な変更をしない）。

完了条件: 未確定（ユーザーから受けた要件に応じて次セッション内で定義する）。

必要なテスト: 未確定（要件確認後に定義する）。
```

---

# OneNote オーガナイザー開発

## Project Name

Onenote オーガナイザー開発

## Current Session

S01

## Current Session Title

Outlook オーガナイザー開発 S01 - 新規比較差分追加機能
（実体はOneNote Report Generatorの複数サーバー対応検討。プロジェクト名・
セッションタイトルの表記ゆれはユーザー提示のテンプレートをそのまま使用）

## Current Objective

あらたなサーバー上のOneNoteも取り込んで、内容をプロジェクトベースで比較検討する。
引継ぎ資料（`HANDOVER_onenote_report_generator.md`）6章の「次期タスク」と同一の依頼。

## Background

- 現行の認証（MSAL）・`_token`・`_extractor` はグローバル変数で、単一
  Microsoft 365 テナント・単一アカウントを前提とした設計（コード確認済み）。
- 一方、同一テナント内の複数SharePointサイトへの対応は `config.json` の
  `sites` 配列と `/api/sites` エンドポイントで既に実装済み（コード確認済み、
  VERSION 20260512_03_01）。
- 「別のOneNoteサーバー」が何を指すかは、引継ぎ資料で以下3パターンが
  想定されており、越智さんへの確認が必須とされている（推測で進めない原則）。
  1. 同一テナント内の別サイト/別ノートブック（→ 既に対応済みの可能性）
  2. 別のMicrosoft 365テナント（他社・他組織）のOneNote（→ マルチテナント
     認証が必要な大規模設計変更）
  3. 個人アカウント（Microsoftアカウント）のOneNote（→ 別認証フローが必要）

## Scope

- Phase 1（設計提案）：上記1〜3のどれに該当するかを越智さんに確認し、
  該当パターンに応じた設計案を提示する。**この段階ではコード生成を行わない。**
- Phase 2（監査）以降は、越智さんの「●３．承認します」の発言後に着手する。

## Files That May Be Changed

Phase 1では変更なし（設計提案のみ）。Phase 3着手後の想定範囲：

- `onenote_report_generator/onenote_report_generator_20260706_01.py`
  （認証・`_token`・`_extractor` 関連、必要に応じて `/api/sites` 等）
- `onenote_report_generator/templates/index.html`（テナント/サーバー切替UI等、必要な場合）
- `onenote_report_generator/config.example.json`
- `onenote_report_generator/CHANGELOG.md`

## Files That Must Not Be Changed

- 上記以外の全ファイル・全フォルダ（`po_database_organizer/` 等、他ツール一式）
- 依頼範囲外のメソッド・エンドポイント（「ついでに直す」禁止）

## Task

1. AskUserQuestion等で、越智さんに上記1〜3のどれに該当するかを確認する
2. 該当パターンに応じた設計案（A/B/C等）をPhase 1として提示する
3. 越智さんの案選択・承認を待つ（Phase 2監査を経てから実装）

## Completion Criteria

- 上記1〜3のどれに該当するか確定していること
- Phase 1設計提案が越智さんに提示されていること
- 既存機能に意図しない影響がないこと（Phase 3実装時）
- 必要なテストが実施されていること（Phase 3実装時）

## Required Tests

- Phase 3実装時：Python構文チェック、既存エンドポイントの回帰確認
- 越智さんの実機（Windows/Chrome）でのGraph API認証・複数サイト/複数テナント
  切替の実地確認（本リモートセッションでは実施不可）

## Known Risks

- グローバル変数 `_token` / `_extractor` は複数テナント・複数ユーザーの
  同時アクセスに対して競合リスクがある（Phase 2監査で必須の論点）
- `bookmarks.json` は現状「単一サイトのID」を前提としたデータ構造。複数
  サーバー対応時はサーバー識別子/テナント識別子フィールドの追加要否と
  後方互換性の設計判断が必要
