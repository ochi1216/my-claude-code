@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

rem run_dashboard.bat
rem
rem analog_ic_se_strategy_organizer_YYYYMMDD_NN.py のうち、ファイル名が最も新しい
rem （＝日付・連番が最大の）ものを自動的に選んで起動する。
rem バージョンアップ時にファイル名の日付が変わっても、このバッチファイルは
rem 書き換える必要はない（常に最新版を自動選択する）。
rem
rem 配置場所: analog_ic_se_strategy_organizer フォルダ内（コード本体と同じ階層）

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo ============================================================
echo  Analog IC SE Strategy Organizer - 起動スクリプト
echo ============================================================
echo.

if "%GEMINI_API_KEY%"=="" (
    echo [警告] 環境変数 GEMINI_API_KEY が設定されていません。
    echo         setx GEMINI_API_KEY "your-api-key-here" で設定してから、
    echo         新しいターミナル／このバッチファイルを開き直してください。
    echo         （設定しなくても画面は起動しますが、分析の実行はできません）
    echo.
)

rem ファイル名降順（新しい日付・連番が先頭）で一覧し、最初の1件を採用する
set "LATEST="
for /f "delims=" %%F in ('dir /b /o-n "analog_ic_se_strategy_organizer_????????_??.py" 2^>nul') do (
    if not defined LATEST set "LATEST=%%F"
)

if not defined LATEST (
    echo [エラー] analog_ic_se_strategy_organizer_YYYYMMDD_NN.py が見つかりませんでした。
    echo          このバッチファイルは、ツール本体（*.py一式）と同じフォルダに
    echo          置いて実行してください。
    echo.
    pause
    exit /b 1
)

echo 起動するバージョン: %LATEST%
echo.

streamlit run "%LATEST%"

if errorlevel 1 (
    echo.
    echo [エラー] streamlit の起動に失敗しました。依存パッケージが未インストールの
    echo          可能性があります。先に以下を実行してから再度お試しください。
    echo.
    echo              pip install -r requirements.txt
    echo.
)

pause
