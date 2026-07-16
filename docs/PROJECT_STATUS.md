# Project Status

## 1. Project Overview

* プロジェクト名: Outlook オーガナイザー開発
* プロジェクトの目的: 未確認（次セッション以降、ユーザーからの指示を受けて確定する）
* 主な利用者: 未確認
* 実行環境: 未確認（本リポジトリ `ochi1216/my-claude-code` 上で開発予定。他プロジェクト同様に Python での実装が想定されるが未確定）

## 2. Repository Structure

* 主要ファイル（リポジトリ直下）
  * `README.md`: リポジトリ全体の概要と、各ツールの開発ルール（バージョン管理・命名規則）を記載
  * `CLAUDE.md`: Claude Code Web セッション運用ルール（本セットアップで新規作成）
  * `HANDOVER_youtube_summary_list.md`: YouTube Summary List ツールの引継ぎ資料
  * `youtube_summary_list_20260703_01.py`, `youtube_summary_list_20260711_01.py`: YouTube Summary List ツール本体（バージョン別）
* 主要フォルダ
  * `po_database_organizer/`: PO Database Organizer（SharePoint の PO フォルダをカタログ化するツール）
  * `rtocs_organizer/`: BBT RTOCS Organizer（RTOCS トレンドダッシュボード・戦略レポート生成）
  * `shareflex_dashboard/`: Shareflex Document Dashboard（Nexus 品質ドキュメントサイト向けダッシュボード）
  * `docs/`: セッション引継ぎ管理ファイル（本セットアップで新規作成）
    * `PROJECT_STATUS.md`: 本ファイル。プロジェクトの現状スナップショット
    * `SESSION_HISTORY.md`: セッションごとの作業履歴
    * `NEXT_TASK.md`: 次セッションで実施するタスク定義
* Outlook オーガナイザー専用のコード・フォルダ: 現時点では存在しない（未着手）

## 3. Current Functions

* 現在実装されている機能: なし（Outlook オーガナイザーとしてのコードは本セットアップ時点で未作成）

## 4. Confirmed Specifications

* 確定済みの仕様: 未確認（次タスクでユーザーから要件を受けて確定する）
* 維持すべき設計方針:
  * リポジトリ全体の命名規則を踏襲する場合、プログラム更新時のファイル名は `ツール名_yyyymmdd_連番.py` とする（`README.md` 記載のルール）
  * バージョンアップ時に旧ファイルを削除・上書きしない（`README.md` 記載のルール）
  * 各ツールフォルダに `CHANGELOG.md` を置き、変更点を記録する（`README.md` 記載のルール）
  * 上記は既存プロジェクトの慣例であり、Outlook オーガナイザーに適用するかは未確認

## 5. Current Status

* 完了済み:
  * 引継ぎ管理ファイル（`CLAUDE.md`, `docs/PROJECT_STATUS.md`, `docs/SESSION_HISTORY.md`, `docs/NEXT_TASK.md`）の初期セットアップ
* 作業中: なし
* 未着手:
  * Outlook オーガナイザー本体の要件定義・設計・実装すべて

## 6. Known Issues

* 既知の問題: 未確認（コードが存在しないため該当なし）
* 暫定対応: なし
* 技術的リスク: 未確認

## 7. Test and Execution

* 起動方法: 未確認（Outlook オーガナイザーのコードが未作成のため）
* テスト方法: 未確認
* 必要な環境変数: 未確認
* 外部サービスへの依存: 未確認（プロジェクト名から Microsoft Outlook / Microsoft Graph API 等との連携が想定されるが未確定）

## 8. Important Restrictions

* 変更禁止事項:
  * 本セットアップと無関係な既存プロジェクト（`po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/`, `youtube_summary_list_*.py` など）は変更しない
* セキュリティ上の注意:
  * 秘密情報、APIキー、パスワード、認証情報はコミットしない
  * `po_database_organizer/config.json` や `token_cache.json` 等、既存の `.gitignore` 対象ファイルの扱いに倣い、Outlook 連携の認証情報も同様にリポジトリへ含めないこと
* 後方互換性に関する注意: 未確認（既存機能なしのため現時点で該当なし）
