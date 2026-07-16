# Project Status

## 1. Project Overview

* プロジェクト名: Outlook オーガナイザー開発
* プロジェクトの目的: Microsoft Outlook（win32com経由のローカルOutlookクライアント）のメールを解析し、対応が必要なアクション項目をダッシュボード化するツール（`outlook_total_organizer`）の継続開発。
* 主な利用者: 未確認
* 実行環境: Windows上のローカルOutlookクライアント＋Python（`win32com`使用のためWindows専用）。Gemini API（`google-genai`）でメール内容を解析。

## 2. Repository Structure

* 主要ファイル（リポジトリ直下）
  * `README.md`: リポジトリ全体の概要と、各ツールの開発ルール（バージョン管理・命名規則）を記載
  * `CLAUDE.md`: Claude Code Web セッション運用ルール
  * `HANDOVER_youtube_summary_list.md`: YouTube Summary List ツールの引継ぎ資料
  * `youtube_summary_list_20260703_01.py`, `youtube_summary_list_20260711_01.py`: YouTube Summary List ツール本体（バージョン別）
* 主要フォルダ
  * `po_database_organizer/`: PO Database Organizer（SharePoint の PO フォルダをカタログ化するツール）
  * `rtocs_organizer/`: BBT RTOCS Organizer（RTOCS トレンドダッシュボード・戦略レポート生成）
  * `shareflex_dashboard/`: Shareflex Document Dashboard（Nexus 品質ドキュメントサイト向けダッシュボード）
  * `outlook_total_organizer/`: Outlook オーガナイザー本体（本セッションで既存コードをリポジトリへ取り込み）
    * `outlook_total_organizer_20260713_03_01.py`: S02開始時にユーザーから提供されたベースライン（このリポジトリ外で既に開発されていた既存バージョン。開発履歴は`CHANGELOG.md`に2026-05-07分から記録あり、ファイル自体は最新版のみ本リポジトリに保持）
    * `outlook_total_organizer_20260716_01_01.py`: S02で追加。「R19Proj以外」フィルタボタンを追加したバージョン
    * `outlook_total_organizer_20260716_02_01.py`: 本セッション（S03）で追加。アクションタブの対象期間に「3週間」「1ヶ月」を追加したバージョン
    * `CHANGELOG.md`: ツールの変更履歴（ユーザー提供のバージョン履歴を元に本セッションで整備。2026-05-07〜）
  * `docs/`: セッション引継ぎ管理ファイル
    * `PROJECT_STATUS.md`: 本ファイル。プロジェクトの現状スナップショット
    * `SESSION_HISTORY.md`: セッションごとの作業履歴
    * `NEXT_TASK.md`: 次セッションで実施するタスク定義

## 3. Current Functions

`outlook_total_organizer_20260716_01_01.py`（約7,500行）内の主なクラス（詳細な内部仕様は今回のセッションでは全面確認していないため一部未確認）:

* `OutlookMailManager`: win32com経由でOutlookのメールを検索・取得
* `MailSummarizer`: Gemini APIでメール内容を解析・要約（アクションダッシュボード用の`summarize_action_dashboard`を含む）
* `HTMLReportGenerator`: 解析結果を静的HTMLダッシュボードとして生成（`generate_action_dashboard_report`など）
* `MailManagerGUI`: tkinterベースのデスクトップGUI
* `OutlookRequestHandler` / `start_local_server`: ローカルHTTPサーバー（ダッシュボードHTMLからのAJAX更新受け口、`/update_action_status`など）

アクションタブ（GUI, `_ui_action_tab`）の機能:

* 「対象期間:」プルダウンで、アクション抽出対象とするメール受信期間を選択（`_get_action_days`で日数に変換し`get_relevant_mails_for_period`に渡す）
* 選択肢: 「24H」「今日」「3日間」「1週間」「2週間」「3週間」「1ヶ月」（**「3週間」「1ヶ月」は本セッションS03で新規追加**。日数換算はそれぞれ21日・30日で、他タブ（コックピット等）の「1ヶ月」=30日換算と統一）

アクションダッシュボード（`generate_action_dashboard_report`が生成するHTML）の機能:

* スレッド単位でアクションをカード化して表示。カード内の各アクション項目ごとに進捗（未着手/進行中/完了/無視）・優先度（—/★優先/★★最優先）・コメントを設定可能
* 進捗・優先度フィルタ、並び替え（優先度順/進捗順/時系列順）
* Outlookの「R19Proj」カテゴリタグが付いたスレッドを自動判定し、カードに🧩マーク表示
* 「🧩 R19Proj」ボタン: R19Proj案件のみに絞り込み
* 「🚫 R19Proj以外」ボタン（S02で新規追加）: R19Proj以外の案件のみに絞り込み。上記R19Projボタンとは排他的に動作（片方をONにするともう片方は自動OFF）

## 4. Confirmed Specifications

* 確定済みの仕様:
  * アクションダッシュボードのR19Projフィルタは、内部的に`r19FilterMode`（`'all'` / `'only'` / `'exclude'`）という3状態で管理する（S02時点、確認済み）
  * バージョンファイル命名規則は`outlook_total_organizer_yyyymmdd_NN_01.py`（同日複数回更新時はNNを増やす。ホットフィックス時は末尾の`_01`部分を`_02`等に増やす例がCHANGELOG.md内に存在）。リポジトリ直下README.mdの命名規則（`ツール名_yyyymmdd_連番.py`）とは形式が異なるが、本ツールはリポジトリ外で既にこの独自の命名規則の下で開発履歴があるため、本セッションでは既存の命名規則を踏襲した。
* 維持すべき設計方針:
  * バージョンアップ時に旧ファイルを削除・上書きしない（ユーザー提供のCHANGELOG.mdの運用そのもの）
  * 各バージョンのCHANGELOGエントリに「変更しないこと（宣誓）」を明記し、無関係な既存機能への影響がないことを保証する

## 5. Current Status

* 完了済み:
  * S01: 引継ぎ管理ファイル（`CLAUDE.md`, `docs/PROJECT_STATUS.md`, `docs/SESSION_HISTORY.md`, `docs/NEXT_TASK.md`）の初期セットアップ
  * S02: ユーザーから提供された既存の`outlook_total_organizer`ソースコード（v20260713_03_01）とCHANGELOGをリポジトリに取り込み。アクションダッシュボードに「🚫 R19Proj以外」フィルタボタンを追加（v20260716_01_01として新規ファイル追加）
  * S03: アクションタブの「対象期間」プルダウンに「3週間」「1ヶ月」を追加（v20260716_02_01として新規ファイル追加）
* 作業中: なし
* 未着手:
  * `README.md` / `requirements.txt`（他ツールと同様の体裁で整備するかどうかは未確認。今回のタスク範囲外のため作成していない）
  * ダッシュボード以外の機能（コックピット・プロジェクト俯瞰・スタッフ俯瞰など、CHANGELOG.md内で言及がある機能）の詳細レビュー

## 6. Known Issues

* 既知の問題: 未確認
* 暫定対応: なし
* 技術的リスク:
  * 本ツールはWindows専用（`win32com`, `pythoncom`使用）かつOutlookデスクトップクライアント・Gemini APIキーに依存するため、本セッションの実行環境（Linuxコンテナ）では実機起動テストができなかった。S02の変更箇所（HTML/JS）は、生成されるHTML断片を切り出しPlaywrightで独立検証済み。S03の変更箇所（tkinterのコンボボックス選択肢・日数変換辞書）はPythonネイティブGUIのため同様の代替検証手段がなく、`ast.parse`による構文チェックと目視でのdiff確認のみ実施（後述）。

## 7. Test and Execution

* 起動方法: 未確認（GUIアプリのため、Outlookインストール済みWindows環境での起動が前提と推測されるが、`config.json`等のセットアップ手順は未確認）
* テスト方法:
  * S02では、`generate_action_dashboard_report`が出力するHTML/CSS/JS部分（コントロールバーのフィルタボタンとJSロジック）のみを抽出し、Playwrightのヘッドレスブラウザで以下を検証した:
    * 初期状態は全カード表示
    * 「🧩 R19Proj」クリックでR19案件のみ表示、ボタンがactive化
    * 「🚫 R19Proj以外」クリックで非R19案件のみ表示に切り替わり、R19Projボタンは自動的に非active化
    * 同じボタンを再クリックすると全件表示に戻る
  * S03（`outlook_total_organizer_20260716_02_01.py`）では以下を実施:
    * `ast.parse`によるPython構文チェック（エラーなし）
    * `diff`により、`_20260716_01_01.py`との差分が意図した2箇所（コンボボックスの`values`、`_get_action_days`の日数変換辞書）のみであることを確認
    * tkinter GUIのため、Playwright等のブラウザ検証は対象外（本ツールが依存するtkinter/win32comはLinuxコンテナ上で実行不可のため未実施）
  * Outlook実データ・Gemini API・tkinter GUIを含むエンドツーエンドの実機テストは未実施（実行環境の制約）
* 必要な環境変数: 未確認
* 外部サービスへの依存: Microsoft Outlook（win32com経由のローカルクライアント）、Gemini API（`google-genai`）

## 8. Important Restrictions

* 変更禁止事項:
  * 本プロジェクトと無関係な既存プロジェクト（`po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/`, `youtube_summary_list_*.py` など）は変更しない
  * `outlook_total_organizer`内の既存バージョンファイル（`_20260713_03_01`, `_20260716_01_01`）は削除・上書きしない
* セキュリティ上の注意:
  * 秘密情報、APIキー、パスワード、認証情報はコミットしない（`json/mail_manager_config.json`等の設定ファイルはコード内で参照されるが、本セッションでは設定ファイル自体は追加していないため該当なし）
* 後方互換性に関する注意:
  * `r19FilterActive`（真偽値）から`r19FilterMode`（3状態文字列）への変更は、生成HTML内のJS変数名変更のみであり、Python側のデータ構造（`is_r19`フラグ等）には影響しない
