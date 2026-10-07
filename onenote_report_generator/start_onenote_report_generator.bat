@echo off
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8

rem ========================================
rem OneNote Report Generator Runner (Log Version)
rem VERSION: 20260727_02 (PowerShell/Tee-Object removed; plain cmd redirection only)
rem Change (20260928_04): code files moved to the app\ folder, so the latest
rem script is now searched for and run under app\.
rem config.json / token_cache.bin / bookmarks.json / logs / reports stay in this
rem onenote_report_generator folder, next to this batch file, as before.
rem Change (20261005_01): this file is now pure ASCII and no longer uses chcp 65001
rem or wmic. Japanese text made cmd.exe misparse the script (UTF-8 bytes read as
rem CP932 broke commands such as "PowerShell" into fragments), and wmic is removed
rem from recent Windows 11 builds, which left the log file name invalid.
rem Details are in CHANGELOG.md.
rem ========================================

rem Move to the working folder
cd /d %~dp0

rem Log file settings
set "LOG_DIR=logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

rem Build the log file name from the current date and time.
rem PowerShell is used because wmic is no longer available on recent Windows 11.
rem Falls back to a fixed name so the log path is always valid.
set "TIMESTAMP="
for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "TIMESTAMP=%%I"
if not defined TIMESTAMP set "TIMESTAMP=unknown"
set "LOG_FILE=%LOG_DIR%\auto_onenote_log_%TIMESTAMP%.log"

echo ==========================================
echo OneNote Report Generator Execution
echo Start: %date% %time%
echo ==========================================

rem ========================================
rem Step 1: Search for the latest script
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
rem Step 2: Run Python
rem Change (20260727_02): running through PowerShell + Tee-Object caused an
rem unexplained immediate exit, so it was removed. Output now goes to the log file
rem with plain cmd redirection only, which behaves like running "python script.py"
rem directly (reliability first).
rem   Trade-off: output is not shown live in this console; it is only written to
rem   the log file. The browser still opens automatically. This window stays open
rem   until Python exits (that is, until the Flask server is stopped).
rem ========================================
echo [2/2] Executing Python script...
echo (Output is not shown in this console. It is written to the log file: %LOG_FILE%)
echo (The browser opens automatically. Press Ctrl+C in this window to stop.)

python "%CD%\app\!LATEST_SCRIPT!" >> "%LOG_FILE%" 2>&1

set "EXIT_CODE=%ERRORLEVEL%"

rem ========================================
rem Execution summary
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
    echo An error occurred during execution - exit code: !EXIT_CODE!. Check the log file.
    pause
)

exit /b !EXIT_CODE!
endlocal
