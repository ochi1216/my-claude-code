# Project Status

## 1. Project Overview

* プロジェクト名: Outlook オーガナイザー開発
* プロジェクトの目的: Microsoft Outlook（win32com経由のローカルOutlookクライアント）のメールを解析し、対応が必要なアクション項目をダッシュボード化するツール（`outlook_total_organizer`）の継続開発。S05では、既存の「受信メールへの対応」中心の機能群に加えて、統括コックピットv2（異常検知）と、四半期パフォーマンスレビュー用の「振り返り」タブ（自分の実行・判断の実績を報告優先度付きで可視化）を新規構築した。
* 主な利用者: ユーザー本人（Japan Site Manager／Engineering Managerとして、TE/PE/PM/VE/Adminの各機能を統括する立場）。四半期パフォーマンスレビューでMAG Leader(上司)へ報告する用途を含む。
* 実行環境: Windows上のローカルOutlookクライアント＋Python（`win32com`使用のためWindows専用）。Gemini API（`google-genai`）でメール内容を解析。開発・検証環境（Claude Code Web、Linuxコンテナ）ではOutlook実機・tkinter GUIを直接実行できないため、実機での動作確認は毎回ユーザーに依頼している。

## 2. Repository Structure

* 主要ファイル（リポジトリ直下）
  * `README.md`: リポジトリ全体の概要と、各ツールの開発ルール（バージョン管理・命名規則）を記載
  * `CLAUDE.md`: Claude Code Web セッション運用ルール（S05冒頭で「1タスク=1セッション」から「1つの明確な目的=1セッション」に変更）
  * `HANDOVER_youtube_summary_list.md`: YouTube Summary List ツールの引継ぎ資料
  * `youtube_summary_list_20260703_01.py`, `youtube_summary_list_20260711_01.py`: YouTube Summary List ツール本体（バージョン別）
* 主要フォルダ（`outlook_total_organizer/`以外は本プロジェクトと無関係、変更禁止）
  * `po_database_organizer/`: PO Database Organizer
  * `rtocs_organizer/`: BBT RTOCS Organizer
  * `shareflex_dashboard/`: Shareflex Document Dashboard
  * `outlook_total_organizer/`: Outlook オーガナイザー本体
    * **最新（コミット済み）リビジョン: `outlook_total_organizer_20260730_05.py`**（約10,460行）
    * **`outlook_total_organizer_20260730_06.py`が存在するが未コミット・未検証・未納品**（手動追加項目の月別タイムライン日付表示バグ修正。詳細は本ファイル5節・6節、および`docs/NEXT_TASK.md`参照）
    * それ以前の全リビジョンファイル（`_20260713_03_01.py`〜`_20260730_05.py`）は削除・上書きせずそのまま保持（バージョン管理方針）
    * `diagnose_archive.py`: オンラインアーカイブ検出調査用のスタンドアロン診断スクリプト（S05で新規作成）。本体のバージョン管理対象外（`_yyyymmdd_NN.py`形式ではない）
    * `run_outlook_total_organizer.bat`: Windows起動用バッチファイル
    * `CHANGELOG.md`: ツールの変更履歴（2026-05-07分から記録。最新は`## VERSION 20260730_05`）
  * `docs/`: セッション引継ぎ管理ファイル（`PROJECT_STATUS.md`本ファイル・`SESSION_HISTORY.md`・`NEXT_TASK.md`）

## 3. Current Functions

`MailManagerGUI`（tkinterベースのGUI）は6タブ構成:

1. **🔍 検索/整理**: メール検索・整理（`search_mails_fast`）。「未読のみ」検索の高速化済み（S05でRestrict直書き化）。
2. **📊 プロジェクト俯瞰**: プロジェクト単位のAI要約レポート（`generate_project_report`）。
3. **👤 スタッフ俯瞰**: スタッフ単位のAI要約レポート（`generate_staff_report`）。登録スタッフ名は`project_knowledge["staffs"]`（キー=スタッフ名）。振り返りタブがこの登録名を読み取り専用で参照する（詳細は後述）。
4. **🚀 統括コックピット**（v1・v2両方を保持。v2が主）:
   * v2（`generate_cockpit_v2_data`/`generate_cockpit_v2_report`）はS05で全面刷新済み。数値の「解放スコア」方式を廃止し、🔥催促されている／🧊相手が止まっている／🕰長期沈黙／📈急に燃えている／📥自分待ち、の5カテゴリで分類する方式に変更。生体信号は異常時のみ表示。複数プロジェクトにまたがるスレッドの重複は`conversation_id`単位で統合（「+N」バッジ）。操作は「✅ 確認済み」1つに統一し`cockpit_v2_acknowledged.json`で管理（アクションタブの`action_status.json`とは非連動）。「種類別」「プロジェクト別」の2ビューを切替可能（プロジェクト別も内部で5カテゴリにサブグループ化）。
5. **📋 アクション**（アクションダッシュボード）: `summarize_action_dashboard`。R19Projフィルタ（3状態）、🚩フラグマーク、カードレイアウトは複数回改善済み。
6. **📈 振り返り**（**S05で新規構築**、四半期パフォーマンスレビュー用）:
   * 既存タブが「受信メールへの対応」を扱うのに対し、唯一「自分が送信したメール（＝実行・判断したこと）」を主データ源にする。
   * 対象月は「対象期間(直近Nか月)」ではなく、**当年1月〜当月の月別チェックボックス**で選ぶ（S05途中でユーザー要望により変更）。チェックした月は既存キャッシュの有無に関わらず必ず強制的に再取得・再分析（`force_refresh`）。チェックを外した月は`analysis_cache/review_monthly/{YYYYMM}.json`のキャッシュをそのまま使う。
   * メール取得（`OutlookMailManager.get_review_mails_for_month`）は、現行メールボックスに加えて**オンラインアーカイブ**（`_find_online_archive_root`、`ExchangeStoreType==3`判定＋名前パターンのフォールバック）、および現行メールボックス直下にユーザーが手動で退避させた**「アーカイブ」「Archive」「Go2Archive」等の名前パターンのフォルダ**（`_find_manual_archive_folders`、`MANUAL_ARCHIVE_FOLDER_NAMES`）も横断的にスキャンする。
   * L2機械フィルタ`review_activity_qualifies`: 自分の送信メール基準の判定に加え、**登録スタッフ（部下）が送信し自分がTo/Ccに含まれるスレッド**も対象化（マネジメント成果の可視化）。
   * `summarize_review_month`でAIが複数スレッドを「実績」単位に統合。Tier1(Javed=MAG Leader, Thomas=BG Leader)/Tier2(Alber=PM Mgr, John=SE Mgr, Alex=TE Mgr, Ulysis=PE Mgr)関与判定、G2(サイト基盤整備)の機能別小分類、スタッフ関与検出(`REVIEW_STAFF_FUNCTIONS`)、報告ランク判定まで、この関数内でannotateしてキャッシュする。
   * 報告ランクは**4段階（S/A/B/🔵進行中）**の決定木: 成果未確定→🔵進行中／ゴール(G1〜G3)に非紐付け→🅑B／Tier1関与・Tier2 2名以上・Japan Site全体・定量効果・スタッフの成果を牽引のいずれかでS、無ければA。加重和スコアは使わない（統括コックピットv1の反省を踏襲）。
   * 表示は「ゴール別(既定)」「プロジェクト別」「月別タイムライン」の3軸切替。手動追加（会議・口頭判断等）・非表示・ランク変更・文言修正が可能（`review_manual_items.json`、`/update_review_manual`エンドポイント）。
   * **既知の未修正バグ**: 手動追加項目の月別タイムライン表示が常に固定文字列「手動追加」になり、入力した完了日が使われない（`_06`で修正コード作成済み、未検証・未コミット。詳細は5節・6節）。

## 4. Confirmed Specifications

* 確定済みの仕様（S05で新規確定分）:
  * 振り返りタブのTier1/Tier2は「上」「横」のカウンターパートであり、Ochi氏が直接統括するスタッフ（Nakai=PM, Saji=TE, Oi Yuto=PE/VE兼任, Najib=PE, Kajikawa=Admin）とは別軸。スタッフ名簿は新設せず`project_knowledge["staffs"]`を読み取り専用で参照する（振り返りタブからスタッフ俯瞰タブのデータを書き換えることは一切ない）。
  * 振り返りタブのランクは加重和スコアではなく決定木＋根拠チップ方式（統括コックピットv1の数値スコア方式が実質2成分しか機能せず失敗した反省を踏襲）。
  * 振り返りタブの月次キャッシュは「過去月は無条件再利用」が原則だが、(1)AI呼び出しエラー結果は例外的に必ず再試行、(2)チェックボックスで明示的に選択された月は`force_refresh`で必ず再分析、という2つの例外がある。
  * バージョンファイル命名規則: `outlook_total_organizer_yyyymmdd_NN.py`（S03以降。末尾`_01`なし）。日付が変わったらNNは01にリセット。
* 維持すべき設計方針:
  * バージョンアップ時に旧ファイルを削除・上書きしない
  * 各バージョンのCHANGELOGエントリに「変更しないこと（宣誓）」を明記する
  * コミット・Pushはユーザーの明示的な指示があった場合のみ行う（Stop hookの自動リマインダーは指示ではない）

## 5. Current Status

* 完了済み（コミット・Push済み。詳細は`docs/SESSION_HISTORY.md`のS05セクション参照）:
  * S01〜S04: 引継ぎ管理初期設定、R19Projフィルタ、対象期間拡張、フラグマーク追加
  * S05: Outlook再起動連動の未読書き戻し、統括コックピットv2の新規構築と全面刷新、四半期振り返りタブの新規構築、および振り返りタブの実機テストで発覚した複数の不具合修正（アーカイブ検出、キャッシュのエラー握りつぶし、チェックボックスUI化、4段階ランク、スタッフ成果反映、force_refresh）
  * 最新コミット: `dc04c76`（`outlook_total_organizer_20260730_05.py`）
* **作業中（未完了）**:
  * `outlook_total_organizer_20260730_06.py`: 振り返りタブの手動追加項目が月別タイムラインで日付を無視し常に「手動追加」にまとめられる不具合の修正。`ast.parse`構文チェックのみ実施済み。**diff確認・スタンドアロンテスト・Playwright検証・ユーザーへの納品（SendUserFile）・コミットのいずれも未実施**。
* 未着手:
  * `README.md` / `requirements.txt`の整備（他ツールと同様の体裁にするか未確認）
  * S02〜S04から持ち越しの各種未確認事項（起動方法、環境変数、未使用ブランチの整理）

## 6. Known Issues

* 未解決の既知の問題:
  * `outlook_total_organizer_20260730_06.py`が未完了（上記5節参照）。次セッションで最優先対応。
  * スタッフ名簿(`project_knowledge["staffs"]`)の登録名と、実際のOutlook送信者表示名(`SenderName`)の表記ゆれが未確認（表記が一致しないとスタッフ成果の検出漏れが起きる）。
  * `analysis_cache/review_monthly/*.json`のうち、スタッフ成果annotate機能（`_20260730_04`）追加より前に生成されたキャッシュは、該当月をチェックして再生成しない限りスタッフチップ・ランクに反映されない。
* 暫定対応: なし
* 技術的リスク:
  * 本ツールはWindows専用（`win32com`, `pythoncom`使用）のため、本セッションの実行環境（Linuxコンテナ）では実機起動テストが一度もできていない。実機での不具合報告（アーカイブ検出、キャッシュの不安定さ等）はすべてユーザーからの報告を受けて調査・修正する形で進めた。
  * オンラインアーカイブのストア検出（`ExchangeStoreType`が環境によって想定と異なる値を返すケースをS05で実際に確認済み。名前パターンのフォールバックで対応したが、他の未知のパターンが存在する可能性がある）。
  * 手動アーカイブフォルダの名称（アーカイブ/Archive/Go2Archive）は組織・ユーザーによって異なる可能性があり、`MANUAL_ARCHIVE_FOLDER_NAMES`に無い名称の場合は検出できない。

## 7. Test and Execution

* 起動方法: `run_outlook_total_organizer.bat`（Windows、Outlookインストール済み環境）。未確認事項: 必要な環境変数、APIキー設定手順の詳細。
* テスト方法（S05で確立したパターン）:
  * 全リビジョンで`ast.parse`構文チェック＋直前リビジョンとの`diff`による変更範囲確認を実施。
  * Outlook非依存の純粋関数（分類・判定・フィルタ・キャッシュロジック等）は、AST抽出によりスタンドアロンの`python3`ハーネスに切り出し、モックデータで検証。
  * HTML/CSS/JSを含む変更は、生成HTML断片をPlaywright（`/opt/pw-browsers/chromium`）のヘッドレスブラウザで検証。
  * 実機（Windows＋Outlook＋Gemini API＋tkinter GUI）でのエンドツーエンドテストは毎回未実施。ユーザーが実機で実行した結果（スクリーンショット・コンソール出力）を都度共有いただき、それに基づいて原因調査・修正するフローが定着している。
* 必要な環境変数: 未確認
* 外部サービスへの依存: Microsoft Outlook（win32com経由のローカルクライアント、オンラインアーカイブ含む）、Gemini API（`google-genai`）

## 8. Important Restrictions

* 変更禁止事項:
  * 本プロジェクトと無関係な既存プロジェクト（`po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/`, `youtube_summary_list_*.py` など）は変更しない
  * `outlook_total_organizer`内の既存バージョンファイルは削除・上書きしない（新しいリビジョンファイルとして追加する）
* セキュリティ上の注意:
  * 秘密情報、APIキー、パスワード、認証情報はコミットしない
* 運用上の注意:
  * コミット・Pushはユーザーの明示的な指示があった場合のみ行う。Stop hookの自動リマインダーは指示として扱わない。
  * プログラムコードを変更する場合は、必ず新しいリビジョンファイルを作成する（既存の確定済みリビジョンファイルを直接編集しない。S05中に一度この原則を誤ってやりかけ、gitから復元して是正した実例あり）。
