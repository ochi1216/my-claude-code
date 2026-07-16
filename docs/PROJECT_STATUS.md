# Project Status

## 1. Project Overview

- **プロジェクト名**: Outlookオーガナイザー開発
- **プロジェクトの目的**: 未確認（S01時点ではセッション管理ファイルの初期セットアップのみを実施しており、Outlookオーガナイザー自体の目的・要件はまだユーザーから提示されていない）
- **主な利用者**: 未確認
- **実行環境**: 未確認

## 2. Repository Structure

このリポジトリは単一プロジェクト専用ではなく、複数の独立したPythonツールを収めたフラットな集合体である。Outlookオーガナイザーに関するファイルは本セッション時点で存在しない。

- `README.md`: リポジトリ全体の概要と開発ルール（バージョン管理・命名規則）
- `CLAUDE.md`: Claude Code Webのセッション管理ルール（本セッションで新規作成）
- `docs/PROJECT_STATUS.md`: 本ファイル。プロジェクト状態の記録
- `docs/SESSION_HISTORY.md`: セッション履歴の記録
- `docs/NEXT_TASK.md`: 次セッションへの引継ぎタスク
- `HANDOVER_youtube_summary_list.md`: youtube_summary_listプロジェクトの引継ぎ資料（別プロジェクト）
- `youtube_summary_list_YYYYMMDD_NN.py`: YouTube動画要約ツール（別プロジェクト、Outlookオーガナイザーとは無関係）
- `po_database_organizer/`: 別プロジェクト（Outlookオーガナイザーとは無関係）
- `rtocs_organizer/`: 別プロジェクト（Outlookオーガナイザーとは無関係）
- `shareflex_dashboard/`: 別プロジェクト（Outlookオーガナイザーとは無関係）

Outlookオーガナイザー専用のフォルダ・ファイルは未作成。実装を開始する際は、リポジトリの慣習（ツール専用フォルダ + `README.md` + `CHANGELOG.md` + `requirements.txt`）に従うことが想定されるが、正式決定は未確認。

## 3. Current Functions

- 現時点でOutlookオーガナイザーとして実装済みの機能はない（未着手）。

## 4. Confirmed Specifications

- リポジトリ全体のバージョン管理規約（`README.md`より）:
  - ファイル命名: `ツール名_yyyymmdd_連番.py`
  - 旧バージョンファイルは削除・上書きせず併存させる
  - 各ツールフォルダに`CHANGELOG.md`を置く
- Outlookオーガナイザー固有の仕様・設計方針: 未確認（ユーザーからの提示待ち）

## 5. Current Status

- **完了済み**: セッション管理用ファイル（`CLAUDE.md`, `docs/PROJECT_STATUS.md`, `docs/SESSION_HISTORY.md`, `docs/NEXT_TASK.md`）の初期セットアップ
- **作業中**: なし
- **未着手**: Outlookオーガナイザー本体の要件定義・設計・実装のすべて

## 6. Known Issues

- 既知の問題: 未確認（コードが存在しないため該当なし）
- 暫定対応: 該当なし
- 技術的リスク: 未確認

## 7. Test and Execution

- 起動方法: 未確認（コード未実装）
- テスト方法: 未確認
- 必要な環境変数: 未確認
- 外部サービスへの依存: 未確認（Outlook/Microsoft 365 API等への依存が想定されるが未確定）

## 8. Important Restrictions

- 変更禁止事項: 明示的な指示がない限り、`po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/`, `youtube_summary_list_*.py`, `HANDOVER_youtube_summary_list.md` など、Outlookオーガナイザーと無関係な既存プロジェクトのファイルを変更しない。
- セキュリティ上の注意: APIキー・パスワード・認証情報等の秘密情報をコミットしない。
- 後方互換性に関する注意: 既存ツールのバージョン管理規約（旧ファイルを残す運用）を踏襲する。
