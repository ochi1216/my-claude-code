@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
set PYTHONIOENCODING=utf-8

rem ========================================
rem Status Check (on-demand)
rem Target: morning_brief.py
rem Version is tracked in Git, not in this file.
rem Purpose:
rem   Send the same status mail as the morning brief, but on demand -
rem   double-click any time (e.g. after lunch, after the 20:00 run) to
rem   see the current state without waiting for the scheduled 06:00 mail.
rem   Uses morning_brief.py's own default window (--hours 12), which is
rem   wide enough to always include the most recent scheduled run
rem   (02:00 / 05:00 / 11:30 / 20:00) regardless of what time of day this
rem   is clicked.
rem   Independent from the nightly summary batch: never touches Chrome.
rem   Output goes to the console AND its own log file, kept separate from
rem   the scheduled morning brief's log so the two are never confused.
rem ========================================

cd /d "%~dp0"

rem [S05] The previous fixed path (company-PC-specific Python313 install)
rem does not exist on other PCs. Resolve via "where" - the not-found case
rem is handled by the Python check step below.
set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"

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
set "LOG_FILE=%LOG_DIR%\status_check_%TIMESTAMP%.log"
set "TMP_OUT=%LOG_DIR%\status_check_%TIMESTAMP%.tmp"

echo =========================================
echo Status Check (on-demand)
echo Start: %date% %time%
echo Working Directory: %CD%
echo Log: %LOG_FILE%
echo =========================================
echo.

rem ========================================
rem Step 1: Python check
rem ========================================
echo [1/3] Checking Python...
if not exist "%PYTHON_EXE%" (
    echo   ERROR: Python not found at %PYTHON_EXE%
    goto :fail
)
echo   OK: %PYTHON_EXE%

rem ========================================
rem Step 2: Resolve target script
rem ========================================
echo [2/3] Resolving target script in %CD% ...

set "TARGET_SCRIPT=morning_brief.py"

if not exist "!TARGET_SCRIPT!" (
    echo   ERROR: !TARGET_SCRIPT! was not found in this folder.
    echo   Copy morning_brief.py next to this .bat file.
    goto :fail
)
echo   OK: !TARGET_SCRIPT!
for %%A in ("!TARGET_SCRIPT!") do echo   Script timestamp: %%~tA

rem ========================================
rem Step 3: Execute
rem ========================================
rem   No --hours flag: uses morning_brief.py's own default (12 hours),
rem   which comfortably spans the gap between any two of the day's
rem   scheduled runs (02:00 / 05:00 / 11:30 / 20:00).
echo [3/3] Running...
echo.

"%PYTHON_EXE%" "!TARGET_SCRIPT!" --send > "%TMP_OUT%" 2>&1
set "EXIT_CODE=!ERRORLEVEL!"

rem Show on screen, then keep a copy in the log.
type "%TMP_OUT%"
type "%TMP_OUT%" >> "%LOG_FILE%"
del "%TMP_OUT%" >NUL 2>&1

echo.
echo =========================================
if !EXIT_CODE! EQU 0 (
    echo Completed successfully. Check Outlook.
) else (
    echo FAILED with exit code !EXIT_CODE! - see messages above.
)
echo End: %date% %time%
echo =========================================

pause
exit /b !EXIT_CODE!

:fail
echo.
echo ========================================= >> "%LOG_FILE%" 2>&1
echo Status check aborted at %date% %time% >> "%LOG_FILE%" 2>&1
echo Aborted. See messages above.
pause
exit /b 1

endlocal
