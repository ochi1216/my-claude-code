@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
set PYTHONIOENCODING=utf-8

rem ========================================
rem Morning Brief Runner
rem Target: morning_brief_yyyymmdd_rr.py
rem VERSION 20260808_02
rem Purpose:
rem   - Send one summary mail every morning (schedule around 06:00)
rem   - Independent from the nightly summary batch: never touches Chrome
rem Note:
rem   [20260808_02] The previous version redirected every line into the log
rem   file, so a failure looked exactly like "nothing happened" on screen.
rem   Output now goes to the console AND the log.
rem ========================================

cd /d "C:\Users\nx023836\Documents\PythonScripts\Youtube"

set "PYTHON_EXE=C:\Users\nx023836\AppData\Local\Programs\Python\Python313\python.exe"

set "LOG_DIR=logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set "TIMESTAMP=%datetime:~0,8%_%datetime:~8,6%"
set "LOG_FILE=%LOG_DIR%\morning_brief_%TIMESTAMP%.log"
set "TMP_OUT=%LOG_DIR%\morning_brief_%TIMESTAMP%.tmp"

echo =========================================
echo Morning Brief  VERSION 20260808_02
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
rem Step 2: Locate the latest morning_brief script
rem ========================================
echo [2/3] Searching for morning_brief_*.py in %CD% ...

set "LATEST_SCRIPT="
for /f "delims=" %%f in ('dir /b /o-n morning_brief_*.py 2^>nul') do (
    set "LATEST_SCRIPT=%%f"
    goto :found
)

:found
if not defined LATEST_SCRIPT (
    echo   ERROR: No morning_brief_*.py found in this folder.
    echo   Copy morning_brief_20260808_01.py next to this .bat file.
    goto :fail
)
echo   OK: !LATEST_SCRIPT!

rem ========================================
rem Step 3: Execute
rem ========================================
rem   --hours 12 covers both the 02:00 and 05:00 runs when scheduled at 06:00.
rem   Use --draft instead of --send while checking the layout.
rem   Use no flag at all to only write an HTML preview file.
echo [3/3] Running...
echo.

"%PYTHON_EXE%" "!LATEST_SCRIPT!" --hours 12 --send > "%TMP_OUT%" 2>&1
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
