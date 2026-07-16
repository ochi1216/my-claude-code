# PROJECT_STATUS.md

学びジャーナル（Journal Manager）の現状を、リポジトリ内のコード・`journal/CHANGELOG.md`・
`git log`から確認できる事実のみに基づいて整理したものです。推測による機能・仕様の追加は
行っていません。確認できない項目は「未確認」と明記しています。

最終更新: S01（セッション引継ぎ管理導入セッション）

## プロジェクト概要

Windows専用の個人用デスクトップアプリ。グローバルホットキー（Ctrl+Shift+J）または
定時リマインドでポップアップを表示し、タグ選択とLKPT（Learned/Keep/Problem/Try）形式の
短いメモを記録する。同時に「チェックイン」ごとの作業時間もタイムログとして記録し、
別ウィンドウのダッシュボードで日次〜年次の集計（学び集計・作業時間集計）を
棒グラフ・円グラフで確認できる。データはローカルのExcelファイル（openpyxl経由）に
保存する。

## 実行環境

- OS: Windows専用（`ctypes.windll`、Windowsのスタートアップフォルダ、`pythonw.exe`を
  前提としたコードのため、Windows以外では動作しない）
- GUI: Tkinter（標準ライブラリ）
- 外部ライブラリ: `openpyxl`（Excel読み書き）。以前は`keyboard`ライブラリを
  ホットキー検知に使用していたが、S01より前の作業でWindows標準の`RegisterHotKey`
  API（`ctypes`経由）に置き換えられ、現在`keyboard`ライブラリへの依存はない
- Pythonバージョン: 未確認（`requirements.txt`等のバージョン指定ファイルはリポジトリ内に
  見当たらない）
- 起動方法: `journal/RunConsole.bat`（コンソール表示ありの手動起動、診断用）、
  または`popup_ui.py`を`pythonw.exe`でWindowsスタートアップフォルダから自動起動
  （バッチファイルの実体はユーザーのローカルPC側にあり、リポジトリには含まれない）

## 主要ファイルと役割

| ファイル | 役割 |
|---|---|
| `journal/storage.py` | Excel(`journal_data.xlsx`)の読み書き。Entries/TagMaster/TimeLogの3シートを管理 |
| `journal/popup_ui.py` | ホットキー起動の入力ポップアップUI（タグ選択＋LKPT入力） |
| `journal/scheduler.py` | 定時リマインドの発火、ログオン時自動起動の登録・解除 |
| `journal/dashboard.py` | 日次〜年次の集計ダッシュボード（学び/時間モード切替、棒グラフ・円グラフ） |
| `journal/RunConsole.bat` | コンソール表示ありで`popup_ui.py`を起動する診断用バッチファイル |
| `journal/CHANGELOG.md` | コード・製品バージョン単位の変更履歴（このファイルとは別に維持） |

## 現在実装済みの機能（`CHANGELOG.md`最新エントリ時点）

- Excelの3シート構成: `Entries`（日付/タグ/L/K/P/T）、`TagMaster`（タグ名/色コード）、
  `TimeLog`（開始/終了/タグ）
- タグ選択UI: 色付きドット＋タグ名を縦に並べたリスト形式。選択すると、選択タグの色を
  白方向に薄めた色（`_lighten_color`で動的計算）がポップアップ全体の背景になる
- 「選択中: タグ名」バッジ: タグの生の色を背景にした太字表示で強調
- LKPT入力: L/K/P/Tそれぞれ1行入力欄（メモは全て任意入力）
- 「✅ 登録」「❌ キャンセル」の2ボタン。登録後は基準点/作業記録の内容を一瞬表示してから閉じる
- グローバルホットキー: `Ctrl+Shift+J`（Windows `RegisterHotKey` API使用、専用スレッドで
  `GetMessageW`により`WM_HOTKEY`を待受）
- 定時リマインド: 8:00〜18:00の毎時（`scheduler.REMINDER_TIMES`）
- タイムログ機能: チェックインのたびに「前回チェックポイントから今まで」を1件の
  作業記録として`TimeLog`シートに記録。本日最初のチェックインは基準点マーカーのみ
  （開始=終了=now、所要時間0分）で作業記録は作らない。前回チェックポイントからの
  経過が`MAX_TIMELOG_GAP_HOURS`（2時間）を超える場合はそこで打ち切る
- ダッシュボード: `PERIODS`（日次/週次/月次/四半期/年次）と`MODES`（学び/時間）の
  組み合わせで集計表示。「時間」モードは同一Canvas領域に棒グラフ（左）＋円グラフ（右）を
  `create_arc`で手描き（追加のグラフ描画ライブラリは導入していない）
- 既存ファイルへの自己修復移行: `_ensure_timelog_sheet()`（TimeLogシートが無ければ追加）、
  `_ensure_lkpt_columns()`（旧「メモ」1列の`Entries`シートを検出したら、メモ列を
  「L」列として読み替え、K/P/T列を追加）

## 確定済みの仕様

- ホットキー: `ctrl+shift+j`（`popup_ui.HOTKEY`定数）
- 定時リマインド時刻: `08:00`〜`18:00`の正時11回（`scheduler.REMINDER_TIMES`）
- タイムログの安全弁: `MAX_TIMELOG_GAP_HOURS = 2`（前回チェックポイントからの経過が
  これを超える場合、記録される作業時間はこの上限で打ち切る）
- Excelファイルパス: `storage.EXCEL_PATH`にハードコードされている
  （`C:\Users\nx023836\Documents\PythonScripts\Journal\journal_data.xlsx`。
  コード内コメントに「越智さんのSharePoint(OneDrive)同期フォルダの実際のパスに
  書き換えてください」というTODOが残っている）
- タグの初期値（`storage.DEFAULT_TAGS`、新規ブック作成時のみ使用）:
  R19(`#d9ae23`)、JP Site(`#2fa84f`)、NPI(`#c2399e`)、その他(`#e08830`)

## 現在の開発状態

直近の変更はLKPT化（`journal/CHANGELOG.md`の最新エントリ、`popup_ui.py`はv0.9.0、
`storage.py`はv0.8.0、`dashboard.py`はv0.7.0、`scheduler.py`はv0.7.4）。
このセッション（S01）中に、Windows専用GUIをこの開発環境（Linux）では直接実行できない
制約があるため、`Xvfb`+`python3.12`（+`openpyxl`）を用いてTkinter/Excel処理の
動作をシミュレーション確認した。最終的な実機（ユーザーのWindows PC）での見た目・
操作感の確認は、一部ユーザーからフィードバックを受けているが、すべての変更について
実機確認済みとまでは確認できていない（詳細は`SESSION_HISTORY.md`のS01を参照）。

## 既知の問題

- ホットキーが長時間稼働中に反応しなくなる不具合が過去に報告され、原因調査の結果
  `keyboard`ライブラリの低レベルフック監視スレッドが停止する可能性を疑い、
  Windows標準の`RegisterHotKey` APIへ置き換えた。置き換え後にユーザーから
  再発の報告はないが、長期運用でのさらなる再発有無は未確認
- タイムログの日付をまたぐケース（深夜作業等）の扱いは未対応（既知の簡略化として
  設計時に許容されている）
- タイムログの「前回チェックポイント」は本日分のTimeLog記録から都度導出する設計のため、
  ユーザーが長時間チェックインしない場合、次回記録時に安全弁（2時間）で打ち切られる
  （意図された仕様だが、ユーザーが体感で違和感を持つ可能性は未確認）

## テスト方法

- 構文確認: `python3 -m py_compile <ファイル>`
- ロジック確認: `openpyxl`を用いてテスト用ワークブックを作成し、`storage.py`の関数を
  直接呼び出して結果を検証（この開発環境で実施可能）
- GUI確認: この開発環境（Linux）にはTkinterが標準では無いため、`python3.12`+
  `pip install openpyxl`（`--break-system-packages`）+ `Xvfb`（`xvfb-run -a`）を
  用いて、実際にTkinterウィンドウを描画し操作をシミュレーションして確認した
- 実機確認: 最終的な見た目・操作感はユーザーのWindows PCで確認する運用
  （ファイルは`SendUserFile`で直接渡すか、GitHubへのpush経由で共有）

## 必要な環境変数

未確認（コード内に環境変数を参照する箇所は見当たらない）

## 外部サービスへの依存

コード上で外部API・外部サービスへの直接通信は見当たらない。Excelファイルの保存先
パスにOneDrive/SharePoint同期フォルダを想定しているとみられるコメントがあるが
（`storage.py`のTODOコメント）、コード自体はローカルファイルパスとして
`openpyxl`で読み書きしているのみで、OneDrive/SharePoint APIとの直接連携は
行っていない

## 変更禁止事項

- `storage.EXCEL_PATH`等、ユーザー固有の環境パスの無断変更
- `journal/CHANGELOG.md`の内容変更（変更が必要な場合は変更案のみ提示する）
- リポジトリ直下の`README.md`の変更

## 後方互換性に関する注意

- 旧「メモ」1列の`Entries`シートを持つ既存の`journal_data.xlsx`は、
  `record_check_in()`呼び出し時に自己修復的にLKPT形式（L/K/P/T4列）へ移行される
  （メモ列の値はそのまま「L」列として読み替えられ、データの移動は発生しない）
- `TimeLog`シートが存在しない既存ファイルも、`record_check_in()`呼び出し時に
  自己修復的に追加される
- これらの移行は`record_check_in()`経由でのみ発生し、`dashboard.py`からの
  読み込み（`load_entries()`等）だけでは移行が実行されない設計になっている
  （読み込み側は旧形式・新形式どちらでも安全に読めるよう列数を都度チェックする
  作りになっている）
