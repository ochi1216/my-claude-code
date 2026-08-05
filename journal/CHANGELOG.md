# CHANGELOG

## v1.0.1 - ポップアップに「📊 DB」ボタンを追加し、3ボタンを均等幅に変更
- 症状: ポップアップからダッシュボードを開く手段が無く、別途手動で
  `dashboard.py`を起動する必要があった
- 対応: 「✅ 登録」「❌ キャンセル」の並びに「📊 DB」ボタンを追加し、
  クリックでダッシュボードを`Toplevel`として開くようにした
  - `_open_dashboard()`: 既にダッシュボードが開いていれば前面化のみ行い、
    多重起動しないようにした（`_show()`の既存パターンを踏襲）
  - `dashboard`モジュールは関数内で遅延importし、`BG_COLOR`等の同名定数が
    モジュールレベルで衝突しないようにした
- 3ボタンの幅を、`pack(expand=True, fill="x")`から`grid`の`uniform`カラムに
  変更し、テキスト長に関わらず完全に均等な幅になるようにした
  （`pack`の`expand`だけでは、ボタンごとの自然サイズの差が残ってしまうため）

## v1.0.0 - popup_ui.pyを日付連番ファイル名に変更し、固定名ランチャーを導入
- 今後、入力ポップアップ本体のファイル名を`daily_journal_yyyymmdd_NN.py`形式で
  バージョン管理する方針に変更。`popup_ui.py`を`daily_journal_20260805_01.py`に
  リネーム（git mvで履歴を保持）
  - ファイル内の自己参照（起動時ログの表示など）を`os.path.basename(__file__)`
    経由に変更し、以後ファイル名が変わってもコード修正不要にした
- `run_latest.py`を新規追加。`daily_journal_*.py`をファイル名の文字列比較で
  検索し、最も新しいものを動的にimportして`run()`を呼び出す固定名の
  ランチャー。バッチファイル側はこのファイルだけを指定しておけば、
  新しいバージョンのファイルを追加するだけで、バッチファイルの修正なしに
  常に最新版が起動する
- `RunConsole.bat`の起動対象を`popup_ui.py`から`run_latest.py`に変更
- `scheduler.py`の`write_startup_batch_file()`/`register_startup_task()`の
  既定の起動対象パスを`popup_ui.py`から`run_latest.py`に変更（本体のファイル名が
  今後変わっても、これらの既定値は変更不要になる）
- 注意: Windowsのスタートアップフォルダに既に配置済みの
  `LearningJournalAutoStart.bat`は、このリポジトリでは管理していない
  ローカルファイルのため、`run_latest.py`を指すよう手動で更新が必要

## v0.9.1 - 起動直後に一度ポップアップを自動表示するように変更
- 症状: Windowsスタートアップから自動起動しても、次の定時リマインド（毎時）まで
  何も画面に出てこないため、朝8時過ぎに出社してPCを立ち上げても9時まで
  基準点（本日最初のチェックイン）を促されない
- 対応: `popup_ui.run()`内で、`start_scheduler_loop()`呼び出し後に
  `queue_popup_trigger()`を1回呼び、起動直後にポップアップを自動表示するように
  変更した。既存の定時リマインドと同じトリガー機構（`_trigger_queue`）を
  再利用しているため、追加のロジックは不要だった

## v0.9.0 - 学びの1行メモをLKPT(Learned/Keep/Problem/Try)の4項目に拡張
- アジャイルのふりかえり手法を参考に、「今日の学び」の1行メモを
  L(Learned)/K(Keep)/P(Problem)/T(Try)の4つの独立した1行入力欄に拡張した
- `storage.py`:
  - `ENTRIES_HEADER`を`["日付","タグ","メモ"]`から
    `["日付","タグ","L","K","P","T"]`に変更
  - `_ensure_lkpt_columns(wb)`を新規追加。既存ブック（メモ1列の旧形式）を
    開いた際、メモ列をそのまま「L」列として読み替え、K/P/T列を自動追加する
    自己修復を行う。既存のメモの値は列の移動をせずそのまま残るため、
    データはそのままLとして統合される
  - `record_check_in()`の引数を`memo: str`から`l/k/p/t: str`の4つに変更
- `popup_ui.py`:
  - 見出しラベル・ウィンドウタイトルバーをともに「今日の学び」から
    「LKPT」に変更
  - 単一のメモ入力欄を、L/K/P/Tそれぞれのラベル＋1行入力欄（4行）に置き換え
  - ウィンドウ高さの見積もりを、入力欄が1→4行に増えた分だけ拡大
- `dashboard.py`:
  - `load_entries()`をL/K/P/Tの4列を読むよう変更（旧3列形式のファイルを
    移行前に開いても壊れないよう安全に読み取る）
  - 記録一覧の表示を、入力されているフィールドだけ「L:xxx K:xxx」のように
    連結して表示するよう変更

## v0.8.0 - タイムログ機能を追加（学び機能とは独立した作業時間トラッキング）
- WorkingHours的な「直前のチェックポイントから今まで、何をしていたか」を
  自己申告するタイムトラッキング機能を追加。設計の概要は下記の通り
  （詳細は `/root/.claude/plans/logical-giggling-quokka.md` の設計コンセプト参照）
  - タグ選択＝前回チェックポイントから今までの作業申告。メモは任意
  - 本日最初のチェックインは基準点マーカー（開始=終了=now、所要時間0分）を
    記録するのみで、作業記録は作らない
  - 前回チェックポイントからの経過が2時間(`MAX_TIMELOG_GAP_HOURS`)を超える
    場合は、記録される作業時間を2時間に打ち切る（長時間放置時の安全弁）
  - メモがあれば従来通りEntriesシートにも「学び」として記録する
- `storage.py`:
  - 新シート`TimeLog`（開始/終了/タグ）を追加。`ensure_workbook_exists()`が
    新規作成時にこのシートも作る。既存ブックには`_ensure_timelog_sheet()`で
    自己修復的に追加する
  - `record_check_in(tag, memo, path, now)`を新規追加。TimeLogとEntriesへの
    追記を1回のload/saveにまとめ、部分成功のリスクを避けた
- `popup_ui.py`:
  - 「✅ 登録」ボタンを追加（メモ空でも明示的に登録できるように）
  - `_submit()`のバリデーションをタグ選択のみに変更（メモは任意に）
  - 登録後、「✅ 基準点を記録しました」または「✅ ○○として記録しました(1h05m)」を
    一瞬表示してからポップアップを閉じる
  - Escapeキーが`_cancel()`を経由するよう統一
- `dashboard.py`:
  - 既存の期間切替ボタンと同じ見た目で「学び/時間」のモード切替ボタンを追加
  - `load_time_log_entries()` / `aggregate_time_by_tag()`を追加
  - 「時間」モードでは、同じCanvas領域を左右に分割し、棒グラフ（左）＋円グラフ
    （右、`create_arc`による手描き、追加ライブラリ導入なし）を表示する
  - 記録一覧は「[開始-終了] [タグ] (所要時間)」形式で表示（基準点マーカー行は
    所要時間0分のため一覧に表示しない）

## v0.7.4 - scheduler.py 定時リマインドを8:00〜18:00の毎時発火に変更
- 症状: これまでの定時リマインドは12:00と17:30の2回のみで、結局触らずに
  忘れてしまうとのフィードバックがあった
- 対応: `REMINDER_TIMES`を8:00〜18:00の正時11回（08:00, 09:00, ..., 18:00）に
  変更した。`check_reminders()`/`start_scheduler_loop()`のロジックは
  リストの要素数に依存しない実装のため変更なし

## v0.7.3 - 横幅の最小リサイズ幅を現在の2/3まで許容
- 症状: `resizable(True, True)`にしたが、`minsize(width, height)`の`width`が
  初期幅(300)そのものだったため、横方向には実質縮小できなかった
- 対応: `minsize`に渡す幅だけ`int(width * 2 / 3)`（=200）に変更し、横方向は
  現在の2/3まで縮小できるようにした。高さの最小値は変更なし

## v0.7.2 - ウィンドウ高さ見積もりの修正（キャンセルボタンの窮屈さ解消）
- 症状: v0.7.1で選択中バッジのフォントを大きく・太字にした結果、ウィンドウ高さの
  見積もり定数`chrome_height`が古いまま（170）で、実際に必要な高さより窓が
  小さくなり、下部のキャンセルボタンが窮屈に(潰れて)表示されていた
- 対応: `chrome_height`を170→210に、最小フォールバック高さを220→260に修正し、
  バッジの拡大分を反映した

## v0.7.1 - 選択中バッジの強調＋ウィンドウのリサイズ対応
- 症状: v0.7.0の背景色連動は、「選択中: ○○」ラベルまで薄色に染まってしまい、
  周囲に溶け込んで目立たなかった
- 対応: `selected_label`を一括テーマ切替(`_apply_theme`)の対象から外し、
  `_select_tag`内でタグの生の色（薄めていない元の色）を直接背景に設定するよう
  変更。文字も専用フォント(`Yu Gothic UI`, 13pt, 太字)＋パディングでバッジ状に
  強調した
- ウィンドウを`resizable(False, False)`から`resizable(True, True)`に変更し、
  ドラッグで縦横に自由にリサイズできるようにした
  - 内容が欠けないよう`minsize()`で最小サイズを保証
  - タグリスト部分(`tag_frame`)とメモ入力欄(`entry`)が拡大縮小に追従するよう
    `fill`/`expand`を追加

## v0.7.0 - popup_ui.py タグ選択を縦型リスト化＋選択色で背景が変わるように変更
- タグ選択UIを、横並びの塗りつぶしボタンから「色付きドット●＋タグ名」を
  縦に並べたリスト形式に変更
  - 行数（タグ件数）に応じてウィンドウの高さを自動計算するようにした
    （Excel側のタグ数が増減しても対応できる）
- タグを選択すると、ポップアップ全体の背景がダークネイビー(`#1a1a2e`)から、
  選択したタグ自身の色を白方向に薄めた色（同系色のパステルトーン）に
  切り替わるようにした。今どのタグを選んでいるかが背景色で一目で分かる
  - `_lighten_color(hex_color, factor)`: 色コードを実行時に薄める関数を追加。
    ハードコードした配色ではなく、Excel由来のタグ色から動的に計算するため、
    タグが何色・何件追加されても自動的に対応する
  - `_register_themed()` / `_apply_theme()`: 背景色・文字色をタグ選択に
    追従させたいウィジェットをまとめて管理する仕組みを追加
  - 色付きドット自体の色（タグ固有色）と、入力欄・キャンセルボタンの配色は
    テーマ切替の対象外とし、常に固定のまま
- 見出しラベルのテキストを「今日の気づき・学び」から「今日の学び」に統一
  （ウィンドウタイトルバーの表記と揃えた）
- `self.tag_buttons`（`tk.Button`の辞書）を`self.tag_rows`（行Frameの辞書）に変更

## v0.6.1 - RunConsole.bat 追加（コンソール表示付き起動用）
- `RunConsole.bat` を新規作成
  - `python.exe`（`pythonw.exe`ではなくコンソール表示あり）で`popup_ui.py`を
    起動し、終了時は`pause`でウィンドウを閉じずに残す
  - 診断用に毎回手動でコマンドプロンプトを開いてコマンドを打つ手間を省くための
    ダブルクリック起動用ファイル
  - 注意: `LearningJournalAutoStart.bat`経由の常駐プロセスと同時に実行すると、
    RegisterHotKeyは同じ組み合わせを2重登録できないため、後から起動した側は
    「❌ ホットキー登録に失敗しました」エラーコード1409になる。これは異常では
    なく、常駐側が先にホットキーを掴んでいる証拠。単体で切り分けたい場合は
    先に常駐プロセスを終了してから使う

## v0.6.0 - popup_ui.py ホットキー実装をWindows RegisterHotKey APIへ全面置き換え
- 症状: `Ctrl+Shift+J`によるポップアップ起動が、スタートアップ経由(pythonw.exe)の
  常駐プロセスでは機能しない。コンソールで手動実行した場合のみ動作していた
- 調査: 定時リマインド(scheduler.py、root.after()ベース)は問題なく動き続けており、
  keyboardライブラリの監視スレッドのみが機能していないと推測される状況だった。
  同一PCで動いていた別のAutoHotkeyスクリプト(`launch_launcher.ahk`)も確認したが、
  そちらは`Ctrl+Shift+L`で別スクリプトを起動するものであり、無関係と判明
- 対応: `keyboard`ライブラリへの依存を廃止し、Windows標準の`RegisterHotKey` API
  (`ctypes`経由)に置き換えた
  - `_hotkey_listener_loop()`: 専用スレッドで`RegisterHotKey`を登録し、
    `GetMessageW`でWM_HOTKEYメッセージを待ち受ける
  - `_parse_hotkey()`: `"ctrl+shift+j"`形式の文字列を修飾キーフラグと
    仮想キーコードに変換する簡易パーサーを追加
  - 登録に失敗した場合（他アプリが同じキーの組み合わせを登録済み等）は
    エラーコードを明示的にログ出力するようにした（従来は無言で失敗していた）
  - トリガーをキューに入れてTkinterメインスレッドでポーリングする既存の
    設計(`_trigger_queue` / `poll_trigger_queue`)はそのまま維持
- 依存削除: `keyboard`（`pip install keyboard`は不要になった）

## v0.5.4 - タグ配色を彩度の高いトーンに再調整
- `storage.py`: `DEFAULT_TAGS`をv0.5.3のパステルトーンから、指定の色見本
  （マゼンタ/ゴールド/グリーン/オレンジ）に近い、より発色の良い配色へ変更
  - R19 `#f6b8c8`→`#d9ae23`（ゴールド） / JP Site `#aed4ec`→`#2fa84f`（グリーン） /
    NPI `#b9e3c6`→`#c2399e`（マゼンタ） / その他 `#d7c6ea`→`#e08830`（オレンジ）
  - 注意: 既存のjournal_data.xlsxには自動反映されないため、
    TagMasterシートの「色コード」列を手動更新する必要あり（v0.1.1・v0.5.3と同様）
- `popup_ui.py`: タグボタンの文字色を`BUTTON_TEXT_COLOR`（濃紺）から`TEXT_COLOR`
  （白）に戻した。背景の彩度が上がったため白文字の方が視認性が高いため
- キャンセルボタン・期間切替ボタン・`ACCENT_COLOR`はv0.5.3のパステル配色のまま変更なし

## v0.5.3 - ボタン配色をパステルカラーに変更
- `storage.py`: `DEFAULT_TAGS`の色コードをパステルトーンに変更
  - R19 `#c96a7c`→`#f6b8c8` / JP Site `#3d6d99`→`#aed4ec` /
    NPI `#4d8b7c`→`#b9e3c6` / その他 `#7a5c99`→`#d7c6ea`
  - 注意: 既存のjournal_data.xlsxには自動反映されないため、
    TagMasterシートの「色コード」列を手動更新する必要あり（v0.1.1と同様）
- `popup_ui.py` / `dashboard.py`: `ACCENT_COLOR`をパステルローズ`#f4a6b8`に変更
  - パステル背景に白文字では視認性が落ちるため、ボタン文字色として
    濃紺の`BUTTON_TEXT_COLOR`(`#2b2b40`)を新設し、タグボタン・キャンセル
    ボタン・期間切替ボタンに適用
  - `popup_ui.py`のキャンセルボタン背景は`BG_COLOR`（背景に同化）から
    パステルグレーの`CANCEL_BTN_BG`(`#d8d8e6`)に変更し、ボタンとして
    視認できるようにした
  - `dashboard.py`の期間切替ボタン（未選択時）の背景は`PANEL_BG`（濃紺）から
    パステルブルーの`PERIOD_BTN_BG`(`#dfeaf5`)に変更
- ウィンドウ背景・入力欄・一覧表示（ダークテーマ）は変更なし

## v0.5.2 - scheduler.py 新機能（スタートアップフォルダ方式）
- 症状: `register_startup_task()`（schtasks方式）が「アクセスが拒否されました」で失敗
- 原因: 社内ポリシーによりコマンドラインからのタスクスケジューラ登録がブロックされていると推測
- 追加: `get_startup_folder()` / `write_startup_batch_file()` / `remove_startup_batch_file()`
  - 個人プロファイル内のスタートアップフォルダにバッチファイルを配置する方式に変更
  - 管理者権限・タスクスケジューラ権限が不要なため、より確実に動作する見込み

## v0.5.1 - scheduler.py 改善（ログオン時起動をコンソール非表示化）
- `register_startup_task()`が、同フォルダ内の`pythonw.exe`を自動検出して
  優先使用するよう変更
- 目的: ログオン時にコンソール画面が表示・点滅する違和感を解消するため

## v0.5.0 - dashboard.py 新規実装（全4モジュール完成）
- `dashboard.py` を新規作成
  - `load_entries()` / `load_tag_colors()`: Excelから記録・タグ色を読込
  - `filter_entries_by_period()` / `aggregate_by_tag()`: 日次/週次/月次/四半期/年次の絞込＋タグ別集計
  - `DashboardWindow`: 期間切替ボタン＋Canvasバーチャート＋記録一覧（ダークテーマ）
  - `run()`: 単体起動用エントリポイント
- 追加の外部ライブラリ導入なし（openpyxl・tkinter標準機能のみで実装）
- これにより storage.py / popup_ui.py / scheduler.py / dashboard.py の4モジュールが完成

## v0.4.0 - scheduler.py / popup_ui.py 重大バグ修正（二重import問題）
- 症状: 定時リマインド発火ログは出るが、ポップアップ表示処理(show())が
  一切呼ばれない（新規追加した検知ログ・例外ログも出ない）
- 原因: `python popup_ui.py`実行時、当該ファイルは`__main__`として動作するが、
  `scheduler.py`が`from popup_ui import queue_popup_trigger`を行うと
  同ファイルが別モジュール`popup_ui`として二重に読み込まれ、
  モジュール変数`_trigger_queue`が2系統に分裂していた
- 修正: `scheduler.py`から`popup_ui`のimportを完全に削除。
  `check_reminders()` / `start_scheduler_loop()`が`trigger_callback`を
  引数として受け取る方式に変更し、`popup_ui.py`の`run()`が
  自モジュールの`queue_popup_trigger`を直接渡すよう変更
- 影響: `scheduler.check_reminders()`および`scheduler.start_scheduler_loop()`の
  呼び出しシグネチャが変更（第一引数にtrigger_callbackが追加）

## v0.2.6 - popup_ui.py バージョン表示追加（ファイル更新有無の切り分け用）
- 起動時に「📦 popup_ui.py version: 0.2.5」を表示するよう変更
- 目的: 新しいログ（show()呼び出し検知、例外捕捉等）が全く出ない状況で、
  「コードが更新されていない」可能性と「更新されているが動作しない」可能性を切り分けるため

## v0.2.5 - popup_ui.py / scheduler.py 防御的ログ追加（原因切り分け用）
- 症状: 定時リマインド発火ログは出るが、以降何も起きず、エラーも表示されない
- 対応: 以下の箇所にtry/exceptと詳細ログを追加し、次回発生時に真因を特定できるようにした
  - `poll_trigger_queue()`: 例外発生時もログ出力しループを継続
  - `show()`: 呼び出し検知ログを追加、`get_tag_master()`失敗時のエラー捕捉を追加
  - `start_scheduler_loop()`: 例外発生時もログ出力しループを継続
- これによりエラーが起きた場合は必ずコンソールに表示されるようになった

## v0.2.4 - popup_ui.py バグ修正（定時リマインド時に前面表示されない問題）
- 症状: 定時リマインド発火のログは出るが、ポップアップが画面に表示されない
- 原因: Windowsのフォアグラウンド制限により、直前のユーザー入力が無い
  タイマー発火時は`focus_force()`が無効化されていた
- 修正: `show()`末尾を`_force_foreground()`に変更。topmost属性の解除→
  再設定を挟むことでWindowsの制限を回避

## v0.3.0 - scheduler.py 新規実装
- `scheduler.py` を新規作成
  - `check_reminders()`: REMINDER_TIMES（既定 12:00 / 17:30）と現在時刻が一致し、
    本日未発火なら強制ポップアップを発火
  - `start_scheduler_loop()`: root.after()による30秒間隔の監視ループ
  - `register_startup_task()` / `unregister_startup_task()`: schtasksコマンドによる
    ログオン時自動起動タスクの登録／削除
- `popup_ui.py` に公開関数 `queue_popup_trigger()` を追加（外部モジュールからの
  安全なポップアップトリガー用）
- `popup_ui.py` の `run()` 内で `scheduler.start_scheduler_loop()` を呼び出すよう変更
  （循環import回避のため関数内で遅延import）
- 未実装: `dashboard.py`（日次〜年次の集計表示）

## v0.2.3 - popup_ui.py UI調整（配色・操作性改善）
- 「記録する」ボタンを削除。Enterキー押下による記録（既存機能）のみに一本化
- 「↩️ 取消」ボタン→「❌ キャンセル」ボタンに変更
  - 変更前: 直前の保存済み記録をUndo
  - 変更後: 今回の入力を保存せず閉じる（保存済みデータには触れない）
- 未使用となった`undo_last_entry`のインポートを削除

## storage.py v0.1.1 - タグ配色の変更
- R19/JP Site/NPI/その他のデフォルト色をマイルドな配色に変更
  - NPIが背景色と同化していた問題を解消
- 注意: 既存のjournal_data.xlsxには自動反映されないため、
  TagMasterシートの「色コード」列を手動更新する必要あり

## v0.2.2 - popup_ui.py 切り分けテスト用変更
- 症状: Ctrl+Alt+L押下時、ホットキー検知ログ自体が出力されない
- 対応: HOTKEYを一時的に"ctrl+shift+j"に変更し、
  Ctrl+Alt+Lが本スクリプト外（OS/セキュリティソフト）で
  先取りされている可能性を切り分け

## v0.2.1 - popup_ui.py バグ修正（ポップアップ即消滅対策）
- 症状: `Ctrl+Alt+L`押下後、ポップアップが一瞬表示されてすぐ消える
- 原因: 修飾キー（Alt）が押されたままウィンドウがフォーカスを奪おうとし、
  Windowsがシステムメニュー呼び出しと誤認識してウィンドウを背面に送っていた
- 修正1: `poll_trigger_queue()` - ホットキー検知後、`root.after(150, popup.show)`で
  修飾キーの解放を待ってから表示するよう変更
- 修正2: `PopupWindow.show()` - `<Alt-KeyPress>`/`<Alt-KeyRelease>`をbreakで無効化し、
  表示直後に`lift()`＋`focus_force()`を明示実行

## v0.2.0 - popup_ui.py 新規実装
- `popup_ui.py` を新規作成
  - `register_global_hotkey()`: グローバルホットキー（既定 Ctrl+Alt+L）登録
  - `PopupWindow`: タグボタン（TagMasterから動的生成）＋1行入力欄のダークテーマポップアップ
  - `PopupWindow._submit()`: `storage.append_entry()`呼び出し→記録完了後に自動クローズ
  - `PopupWindow._undo()`: `storage.undo_last_entry()`呼び出しによる直近記録の取消
  - `poll_trigger_queue()` / `run()`: 別スレッド（keyboardフック）からのイベントを
    メインスレッドのTkinterに安全に伝搬するポーリング機構
- 依存追加: `keyboard`（グローバルホットキー検知用）
- 未実装: `scheduler.py`（定時リマインド）、`dashboard.py`（集計表示）

## v0.1.0 - storage.py 新規実装
- `storage.py` を新規作成
  - `ensure_workbook_exists()`: 初期ブック作成（Entries / TagMasterシート、初期タグ4種）
  - `append_entry()`: 1行追記（ロック競合時リトライ＋失敗時ローカル退避保存）
  - `undo_last_entry()`: 直近1件の取り消し
  - `get_tag_master()` / `add_tag()` / `remove_tag()`: タグの可変マスタ管理
- 未実装: `popup_ui.py`（入力ポップアップ）、`scheduler.py`（定時リマインド）、`dashboard.py`（集計表示）
