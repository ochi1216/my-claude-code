# Next Task

## Session Management

- Project Name: 会議録画文字起こし・要約ツール開発（meeting-recording-transcription）
- Previous Session: S01
- Next Session Number: S02
- Recommended Session Title: 会議録画文字起こし・要約ツール開発 S02 - （セッション目的に応じて決定）

## Objective

- 本セッション（S01）がそのまま継続する場合: 文字起こしエンジン・話者分離・出力形式についてユーザーへ確認し、要件を確定させたうえで設計・実装を開始する。
- 新しいセッションから着手する場合: ユーザーから次のタスク指示を受ける。

## Background

- S01では、会議録画（.mkv）の文字起こし・要約ツールの構想整理を開始し、リポジトリの既存慣習（Python製、フォルダ単位、Gemini API利用、バージョン管理命名規則）を確認した。
- 文字起こしエンジン（Gemini API／ローカルWhisper／両対応）、話者分離の要否、出力形式（Markdownのみ／構造化データ併用）についてユーザーへ確認する予定だったが、ツールエラーにより中断している。
- あわせて、セッション管理用の管理ファイル（`CLAUDE.md`, `docs/PROJECT_STATUS.md`, `docs/SESSION_HISTORY.md`, `docs/NEXT_TASK.md`）の初期セットアップを実施し、その後プロジェクト名の誤り（誤って「Outlookオーガナイザー開発」としていた点）を訂正した。
- 本プロジェクト本体の要件定義・設計・実装はすべて未着手。
- リポジトリには既存の無関係な他プロジェクト（`po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/`, `youtube_summary_list_*.py`）が存在するが、いずれも本プロジェクトとは独立している。

## Scope

### Files That May Be Changed

- 未定（要件確定後、本プロジェクト専用の新規フォルダ・ファイルを作成する見込み。既存ファイルへの変更は想定していない）

### Files That Must Not Be Changed

- `po_database_organizer/` 配下一式
- `rtocs_organizer/` 配下一式
- `shareflex_dashboard/` 配下一式
- `youtube_summary_list_*.py`, `HANDOVER_youtube_summary_list.md`
- （上記は本プロジェクトと無関係な既存プロジェクトのため、明示的指示がない限り変更しない）

## Task

1. 文字起こしエンジン（Gemini API／ローカルWhisper／両対応）についてユーザーへ確認する。
2. 話者分離の要否・精度レベルについてユーザーへ確認する。
3. 要約の出力形式（Markdownのみ／構造化データ併用）についてユーザーへ確認する。
4. 上記が確定した後、実装方針を設計し、実装を開始する。

## Completion Criteria

- 未定（要件確定後に定める）

## Required Tests

- 未定（実装内容確定後に定める）

## Known Risks

- 文字起こしエンジン・話者分離・出力形式が未確認であり、推測で実装を進めるべきではない。
- 画面キャプチャー録画（.mkv）はファイルサイズが大きくなりやすく、音声抽出・分割処理の設計が必要になる可能性がある。

## Start Prompt

会議録画文字起こし・要約ツール開発を再開します。`CLAUDE.md`, `docs/PROJECT_STATUS.md`, `docs/SESSION_HISTORY.md`, `docs/NEXT_TASK.md` を確認しました。文字起こしエンジン・話者分離・出力形式について確認させてください。
