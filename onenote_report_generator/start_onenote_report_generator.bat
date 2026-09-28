@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
set PYTHONIOENCODING=utf-8

rem ========================================
rem OneNote Report Generator Runner (Log Version)
rem VERSION: 20260727_02 (PowerShell/Tee-Object廃止・cmd標準リダイレクトのみに変更)
rem 変更点(20260928_04): コードファイルをapp\フォルダへ移動したため、
rem 最新スクリプトの検索・実行パスをapp\配下に変更した。
rem config.json/token_cache.bin/bookmarks.json/logs/reportsは従来どおり
rem このバッチと同じonenote_report_generator直下に置く。
rem ========================================

rem 作業フォルダに移動
cd /d %~dp0

rem ログファイル設定
set "LOG_DIR=logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

rem 日付・時刻を取得してログファイル名を生成
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set "TIMESTAMP=%datetime:~0,8%_%datetime:~8,6%"
set "LOG_FILE=%LOG_DIR%\auto_onenote_log_%TIMESTAMP%.log"

echo ==========================================
echo OneNote Report Generator Execution
echo Start: %date% %time%
echo ==========================================

rem ========================================
rem Step 1: 最新スクリプト検索
rem ========================================
echo [1/2] Searching for latest generator script...

set "LATEST_SCRIPT="
for /f "delims=" %%f in ('dir /b /o-n app\onenote_report_generator_*.py 2^>nul') do (
    set "LATEST_SCRIPT=%%f"
    goto :found
)

:found
if not defined LATEST_SCRIPT (
    echo ERROR: No onenote_report_generator script found!
    pause
    exit /b 1
)

echo Latest script found: !LATEST_SCRIPT!

rem ========================================
rem Step 2: Python実行
rem 変更点(20260727_02): PowerShell + Tee-Object 経由での実行が原因不明の
rem 即終了を起こしていたため廃止。cmd標準のリダイレクト( >> と 2>&1 )のみで
rem ログファイルへ出力する方式に変更し、直接 "python script.py" を実行した
rem ときと同じ挙動になるようにした（動作の確実性を優先）。
rem   ※トレードオフ：実行中の出力はコンソールにリアルタイム表示されず、
rem     ログファイル（%LOG_FILE%）にのみ記録される。
rem     ブラウザは従来どおり自動で開く。ウィンドウはPythonが終了する
rem     （Flaskサーバーを止める）まで開いたままになる。
rem ========================================
echo [2/2] Executing Python script...
echo (出力はコンソールには表示されません。ログファイルに記録されます: %LOG_FILE%)
echo (ブラウザが自動で開きます。終了するにはこのウィンドウで Ctrl+C を押してください)

python "%CD%\app\!LATEST_SCRIPT!" >> "%LOG_FILE%" 2>&1

set "EXIT_CODE=%ERRORLEVEL%"

rem ========================================
rem 実行結果サマリー
rem ========================================
echo.
echo =========================================
echo Execution Summary
echo =========================================
echo Script: !LATEST_SCRIPT!
echo Exit Code: !EXIT_CODE!
echo End Time: %date% %time%
echo Log File: %LOG_FILE%
echo =========================================

if !EXIT_CODE! neq 0 (
    echo 実行中にエラーが発生しました（コード: !EXIT_CODE!）。ログファイルをご確認ください。
    pause
)

exit /b !EXIT_CODE!
endlocal
