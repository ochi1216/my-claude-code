@echo off
setlocal enabledelayedexpansion

rem run_dashboard.bat
rem
rem Finds the analog_ic_se_strategy_organizer_YYYYMMDD_NN.py with the
rem newest date/sequence number in this folder and launches it with
rem streamlit. When a newer dated version is added later, this launcher
rem does NOT need to be edited - it always picks the latest one.
rem
rem Place this file directly inside the analog_ic_se_strategy_organizer
rem folder, next to the tool's .py files and requirements.txt.
rem
rem NOTE: this file intentionally contains only ASCII text (no Japanese)
rem to avoid character-encoding (mojibake) problems that can make
rem Windows cmd.exe misparse the script on some systems.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo ============================================================
echo  Analog IC SE Strategy Organizer - Launcher
echo ============================================================
echo.

if "%GEMINI_API_KEY%"=="" (
    echo [WARNING] Environment variable GEMINI_API_KEY is not set.
    echo           Run:  setx GEMINI_API_KEY "your-api-key-here"
    echo           then close this window and open a new one before
    echo           launching again. The dashboard will still open
    echo           without it, but analysis steps will fail.
    echo.
)

rem List matching files newest-name-first, take the first one.
set "LATEST="
for /f "delims=" %%F in ('dir /b /o-n "analog_ic_se_strategy_organizer_????????_??.py" 2^>nul') do (
    if not defined LATEST set "LATEST=%%F"
)

if not defined LATEST (
    echo [ERROR] Could not find any analog_ic_se_strategy_organizer_YYYYMMDD_NN.py
    echo         file in this folder. Place run_dashboard.bat directly inside
    echo         the analog_ic_se_strategy_organizer folder, next to the
    echo         tool's .py files.
    echo.
    pause
    exit /b 1
)

echo Launching version: %LATEST%
echo.

streamlit run "%LATEST%"

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start streamlit. If dependencies are not installed
    echo         yet, run the following command first, then try again:
    echo.
    echo             pip install -r requirements.txt
    echo.
)

pause
