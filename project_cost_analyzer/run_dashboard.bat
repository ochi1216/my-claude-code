@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "LATEST="
for /f "delims=" %%f in ('dir /b /a-d /o-n "project_cost_analyzer_*.py" 2^>nul') do (
    if not defined LATEST set "LATEST=%%f"
)

if not defined LATEST (
    echo [ERROR] project_cost_analyzer_*.py が見つかりません。このバッチファイルを project_cost_analyzer フォルダ内に置いてください。
    pause
    exit /b 1
)

echo 起動するファイル: %LATEST%
streamlit run "%LATEST%"

pause
