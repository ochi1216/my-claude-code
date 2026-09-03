@echo off
rem Document Search Manager 起動用バッチ
rem このバッチが置かれたフォルダへ移動してから実行する（カレントディレクトリ非依存）
cd /d %~dp0
python document_search_manager_20260903_01.py
pause
