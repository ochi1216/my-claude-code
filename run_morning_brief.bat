@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
set PYTHONIOENCODING=utf-8

rem ========================================
rem Morning Brief Runner
rem Target: morning_brief_yyyymmdd_rr.py
rem VERSION 20260808_01
rem Purpose:
rem   - Send one summary mail every morning (schedule around 06:00)
rem   - Independent from the nightly summary batch: this script never
rem     touches Chrome, so it cannot break the 02:00 / 05:00 runs
rem   - Uses the same fixed Python313 path as the other runners
rem ========================================

cd /d "C:\Users\nx023836\Documents\PythonScripts\Youtube"

set "PYTHON_EXE=C:\Users\nx023836\AppData\Local\Programs\Python\Python313\python.exe"

rem ========================================
rem Log setup
rem ========================================
set "LOG_DIR=logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set "TIMESTAMP=%datetime:~0,8%_%datetime:~8,6%"
set "LOG_FILE=%LOG_DIR%\morning_brief_%TIMESTAMP%.log"

echo ========================================= >> "%LOG_FILE%" 2>&1
echo Morning Brief Execution >> "%LOG_FILE%" 2>&1
echo VERSION: 20260808_01 >> "%LOG_FILE%" 2>&1
echo Start: %date% %time% >> "%LOG_FILE%" 2>&1
echo ========================================= >> "%LOG_FILE%" 2>&1

rem ========================================
rem Step 0: Python check
rem ========================================
if not exist "%PYTHON_EXE%" (
    echo ERROR: Fixed Python executable not found! >> "%LOG_FILE%" 2>&1
    echo Expected: %PYTHON_EXE% >> "%LOG_FILE%" 2>&1
    exit /b 1
)

rem ========================================
rem Step 1: Search latest morning_brief script
rem ========================================
set "LATEST_SCRIPT="
for /f "delims=" %%f in ('dir /b /o-n morning_brief_*.py 2^>nul') do (
    set "LATEST_SCRIPT=%%f"
    goto :found
)

:found
if not defined LATEST_SCRIPT (
    echo ERROR: No morning_brief script found! >> "%LOG_FILE%" 2>&1
    exit /b 1
)

echo Latest script found: !LATEST_SCRIPT! >> "%LOG_FILE%" 2>&1

rem ========================================
rem Step 2: Execute
rem ========================================
rem   --hours 12 covers both the 02:00 and 05:00 runs when scheduled at 06:00.
rem   Change --send to --draft while you are still checking the layout.
"%PYTHON_EXE%" "!LATEST_SCRIPT!" --hours 12 --send >> "%LOG_FILE%" 2>&1

set "EXIT_CODE=!ERRORLEVEL!"

echo. >> "%LOG_FILE%" 2>&1
echo Completed with exit code: !EXIT_CODE! >> "%LOG_FILE%" 2>&1
echo End Time: %date% %time% >> "%LOG_FILE%" 2>&1
echo ========================================= >> "%LOG_FILE%" 2>&1

exit /b !EXIT_CODE!

endlocal
