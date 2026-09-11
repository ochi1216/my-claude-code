@echo off
rem ============================================================
rem Shareflex Document Dashboard 起動バッチ
rem
rem 同じフォルダにある shareflex_dashboard_*.py のうち、
rem ファイル名(日付)が最も新しいものを自動検出して実行する。
rem スクリプトが更新されて別の日付のファイル名に変わっても、
rem このバッチファイル自体は変更不要。
rem
rem 使い方:
rem   1) このバッチファイルにExcelファイルをドラッグ&ドロップする
rem   2) または、このバッチファイルをダブルクリックして、
rem      表示されるプロンプトにExcelファイルのパスを入力する
rem ============================================================

setlocal enabledelayedexpansion
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"

rem ---- 最新の shareflex_dashboard_*.py を検出(ファイル名降順の先頭) ----
set "LATEST_SCRIPT="
for /f "delims=" %%F in ('dir /b /o-n "%SCRIPT_DIR%shareflex_dashboard_*.py" 2^>nul') do (
    if not defined LATEST_SCRIPT set "LATEST_SCRIPT=%%F"
)

if not defined LATEST_SCRIPT (
    echo [エラー] %SCRIPT_DIR% に shareflex_dashboard_*.py が見つかりません。
    pause
    exit /b 1
)

echo 実行するスクリプト: %LATEST_SCRIPT%

rem ---- Pythonコマンドの決定(python優先、なければpyランチャー) ----
set "PYTHON_CMD=python"
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [エラー] Pythonが見つかりません。Pythonをインストールしてください。
        pause
        exit /b 1
    )
    set "PYTHON_CMD=py"
)

rem ---- 入力Excelファイルの決定 ----
if "%~1"=="" (
    set /p "INPUT_FILE=エクスポートしたExcelファイルのパスを入力してください: "
) else (
    set "INPUT_FILE=%~1"
)

if not exist "%INPUT_FILE%" (
    echo [エラー] ファイルが見つかりません: %INPUT_FILE%
    pause
    exit /b 1
)

rem ---- 実行 ----
"%PYTHON_CMD%" "%SCRIPT_DIR%%LATEST_SCRIPT%" "%INPUT_FILE%"
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
echo 完了しました。
pause
