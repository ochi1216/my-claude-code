# CHANGELOG — emergency_alert_tool

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

## [20260729_05] - 2026-07-29

**変更ファイル:** `emergency_alert_tool_20260729_01.py`, `config.example.json`, `README.md`, `tests/test_emergency_alert_tool.py`

- Azure ADアプリ登録・クライアントシークレットが未準備の状態でも、
  トリガー〜18名への通知〜回答フォーム〜上司3名への即時通知の一連の
  流れを検証できるよう、`dry_run` モードを追加。
  - `config.json` に `"dry_run": true` を設定すると、実際のメール送信の
    代わりにコンソールへ送信内容をログ出力する `LoggingNotifier` が使われる。
  - 本物の地震を待たずに動作確認できる `/internal/test-trigger`
    エンドポイント（動作確認専用、外部非公開推奨）を追加。
- 上記についてpytestのテストを5件追加し、全件パスを確認（計21件）。

## [20260729_04] - 2026-07-29

**変更ファイル:** `run_emergency_alert_tool.bat`

- `config.json` が存在しない場合、これまではエラーで終了するだけだったが、
  同じフォルダの `config.example.json` から自動的に `config.json` を
  作成し、編集が必要な旨を案内するように変更（初回セットアップの手間を軽減）。

## [20260729_03] - 2026-07-29

**変更ファイル:** `run_emergency_alert_tool.bat`

- `run_emergency_alert_tool.bat` 実行時に、Windowsのコンソールコードページ
  （Shift-JIS等）とファイルの文字コード（UTF-8）の不一致により、
  日本語メッセージが文字化けしてコマンドとして誤認識され、実行時エラーに
  なる不具合を修正。バッチファイル内の表示メッセージを全て英数字(ASCII)に
  置き換え、改行コードもCRLFに統一した。

## [20260729_02] - 2026-07-29

**追加ファイル:** `run_emergency_alert_tool.bat`
**変更ファイル:** `README.md`

- Windows用の起動バッチファイル `run_emergency_alert_tool.bat` を追加。
  同じフォルダに配置して実行すると、仮想環境の作成・依存パッケージの
  インストール・`config.json`/環境変数の存在チェックを行った上で、
  Webサーバ（回答フォーム・ダッシュボード・ポーリング）を起動する。
- README.md にWindows（バッチファイル）での起動手順を追記。

## [20260729_01] - 2026-07-29

**追加ファイル:** `emergency_alert_tool_20260729_01.py`, `config.example.json`, `requirements.txt`, `README.md`, `tests/test_emergency_alert_tool.py`

- 緊急地震速報（大分県・大阪府・東京都、震度5弱以上）を検知したら、緊急連絡網の
  スタッフ18名へ安否確認メールを自動送信するツールの初版。
- スタッフは「安否（無事/被災）」「場所（職場/自宅）」「出社可否（出社可能/出社不可能）」の
  3項目をクリックで回答するWebフォーム（`/respond/<token>`）を実装。
- 回答が送信されると、即座に上司3名へGraph API経由で通知する処理を実装。
- `/dashboard/<alert_id>` に、18名の回答状況を一覧できる簡易ダッシュボードを実装。
- Microsoft Graph API（app-only, client credentials フロー, MSAL）でのメール送信を実装
  （`po_database_organizer` のMSAL活用実績を踏襲）。
- 緊急地震速報フィードはP2P地震情報APIを想定したパーサ (`parse_p2pquake_eew`) を実装
  （実データスキーマは未検証、README参照）。
- pytestによる自動テスト16件を作成し、全件パスを確認（Graph API呼び出しはテスト用ダブルに置き換え）。
