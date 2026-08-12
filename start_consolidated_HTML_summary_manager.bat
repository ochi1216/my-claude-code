@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
set PYTHONIOENCODING=utf-8

rem ========================================
rem Consolidated Summary Manager Auto Runner
rem Target: consolidated_html_summary_manager.py
rem Version is tracked in Git, not in this file.
rem
rem [20260808] Changes:
rem   - The previous version searched with
rem       dir /b /o-n consolidated_html_summary_manager_*.py
rem     Note the trailing underscore: it only matches dated file names such
rem     as consolidated_html_summary_manager_20260805_04.py. After the file
rem     was renamed to the fixed consolidated_html_summary_manager.py the
rem     pattern stopped matching, the script was never found, and the batch
rem     exited with code 1. Now the fixed file name is referenced directly.
rem   - Every line used to be redirected into the log file, so that failure
rem     looked exactly like "nothing happened" on screen. Output now goes to
rem     the console AND the log.
rem   - cd /d "%~dp0" so the batch works regardless of the caller's working
rem     directory (Task Scheduler "Start in" is often different).
rem ========================================

cd /d "%~dp0"

set "LOG_DIR=logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

rem [S04] wmic is removed on current Windows builds. When it is missing,
rem the datetime variable stays empty and TIMESTAMP expands to a literal
rem string containing a colon, which is not a legal Windows filename.
rem The log redirect then fails, the target script never runs at all, and
rem the batch still reports success. Resolve the timestamp with PowerShell,
rem which is locale independent, and fall back to a fixed safe name so a
rem failure here can never produce an unusable filename again.
set "TIMESTAMP="
for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "TIMESTAMP=%%I"
if not defined TIMESTAMP set "TIMESTAMP=notimestamp"
set "LOG_FILE=%LOG_DIR%\auto_summary_manager_log_%TIMESTAMP%.log"
set "TMP_OUT=%LOG_DIR%\auto_summary_manager_%TIMESTAMP%.tmp"

echo =========================================
echo Consolidated Summary Manager
echo Start: %date% %time%
echo Working Directory: %CD%
echo Log: %LOG_FILE%
echo =========================================
echo.

rem ========================================
rem Step 1: Resolve target script
rem ========================================
echo [1/2] Resolving target script...

set "TARGET_SCRIPT=consolidated_html_summary_manager.py"

if not exist "!TARGET_SCRIPT!" (
    echo   ERROR: !TARGET_SCRIPT! was not found in %CD%
    echo   Copy consolidated_html_summary_manager.py next to this .bat file.
    goto :fail
)
echo   OK: !TARGET_SCRIPT!
for %%A in ("!TARGET_SCRIPT!") do echo   Script timestamp: %%~tA

rem ========================================
rem Step 2: Execute
rem ========================================
echo [2/2] Running...
echo.

python "!TARGET_SCRIPT!" > "%TMP_OUT%" 2>&1
set "EXIT_CODE=!ERRORLEVEL!"

rem [S04] If the redirect target could not be created, the script above never
rem ran at all. That happened for real: a broken timestamp produced a filename
rem containing a colon, the redirect failed, nothing executed, and this batch
rem still printed "Completed successfully" four times a day. Treat a missing
rem output file as a failure so that case can never look like success again.
if not exist "%TMP_OUT%" (
    echo ERROR: could not create "%TMP_OUT%" - the script did not run.
    set "EXIT_CODE=1"
    goto :report
)

rem Show on screen, then keep a copy in the log.
type "%TMP_OUT%"
type "%TMP_OUT%" >> "%LOG_FILE%"
del "%TMP_OUT%" >NUL 2>&1

:report

echo.
echo =========================================
if !EXIT_CODE! EQU 0 (
    echo Completed successfully.
) else (
    echo FAILED with exit code !EXIT_CODE! - see messages above.
)
echo Script: !TARGET_SCRIPT!
echo End: %date% %time%
echo =========================================

echo Script: !TARGET_SCRIPT! >> "%LOG_FILE%" 2>&1
echo Exit Code: !EXIT_CODE! >> "%LOG_FILE%" 2>&1
echo End Time: %date% %time% >> "%LOG_FILE%" 2>&1

exit /b !EXIT_CODE!

:fail
echo.
echo Aborted. See messages above.
echo Aborted at %date% %time% >> "%LOG_FILE%" 2>&1
exit /b 1

endlocal
