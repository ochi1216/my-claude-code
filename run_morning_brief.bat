@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
set PYTHONIOENCODING=utf-8

rem ========================================
rem Morning Brief Runner
rem Target: morning_brief.py
rem Version is tracked in Git, not in this file.
rem Purpose:
rem   - Send one summary mail every morning (schedule around 06:00)
rem   - Independent from the nightly summary batch: never touches Chrome
rem Note:
rem   [20260808_02] The previous version redirected every line into the log
rem   file, so a failure looked exactly like "nothing happened" on screen.
rem   Output now goes to the console AND the log.
rem ========================================

cd /d "%~dp0"

rem [S05] The previous fixed path (company-PC-specific Python313 install)
rem does not exist on other PCs. Resolve via "where" - the not-found case
rem is handled by the Python check step below.
set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"

set "LOG_DIR=logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set "TIMESTAMP=%datetime:~0,8%_%datetime:~8,6%"
set "LOG_FILE=%LOG_DIR%\morning_brief_%TIMESTAMP%.log"
set "TMP_OUT=%LOG_DIR%\morning_brief_%TIMESTAMP%.tmp"

echo =========================================
echo Morning Brief
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

rem [20260808] Version is managed by Git, not by file name.
rem The previous "dir /b /o-n" search picked the newest name, which
rem would silently prefer a leftover dated copy over this fixed name.
set "LATEST_SCRIPT=morning_brief.py"

if not exist "!LATEST_SCRIPT!" (
    echo   ERROR: !LATEST_SCRIPT! was not found in this folder.
    echo   Copy morning_brief.py next to this .bat file.
    goto :fail
)
echo   OK: !LATEST_SCRIPT!
for %%A in ("!LATEST_SCRIPT!") do echo   Script timestamp: %%~tA

rem ========================================
rem Step 3: Execute
rem ========================================
rem   --hours 24 covers a full day of runs (02:00 / 05:00 / 11:30 / 20:00),
rem   so the morning mail reports everything since the previous morning.
rem   Use --draft instead of --send while checking the layout.
rem   Use no flag at all to only write an HTML preview file.
echo [3/3] Running...
echo.

"%PYTHON_EXE%" "!LATEST_SCRIPT!" --hours 24 --send > "%TMP_OUT%" 2>&1
set "EXIT_CODE=!ERRORLEVEL!"

rem Show on screen, then keep a copy in the log.
type "%TMP_OUT%"
type "%TMP_OUT%" >> "%LOG_FILE%"
del "%TMP_OUT%" >NUL 2>&1

echo.
echo =========================================
if !EXIT_CODE! EQU 0 (
    echo Completed successfully.
) else (
    echo FAILED with exit code !EXIT_CODE! - see messages above.
)
echo End: %date% %time%
echo =========================================

exit /b !EXIT_CODE!

:fail
echo.
echo ========================================= >> "%LOG_FILE%" 2>&1
echo Morning Brief aborted at %date% %time% >> "%LOG_FILE%" 2>&1
echo Aborted. See messages above.
exit /b 1

endlocal
