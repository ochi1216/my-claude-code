# CHANGELOG

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
