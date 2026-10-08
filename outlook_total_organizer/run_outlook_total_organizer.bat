@echo off
setlocal enabledelayedexpansion
rem ========================================
rem Outlook Total Organizer launcher
rem Change (20261004_16): code moved to the app\ folder (older revisions: app\old\).
rem This file is pure ASCII on purpose (Japanese text in a .bat can be misparsed by cmd.exe).
rem
rem - Working folder = the folder of this .bat (json\ settings/cache stay here, as before).
rem - Runs the newest app\outlook_total_organizer_*.py (by file name, yyyymmdd_NN).
rem - No need to edit this file when a new revision is added.
rem ========================================
cd /d "%~dp0"

set "LATEST="
for /f "delims=" %%F in ('dir /b /o-n "app\outlook_total_organizer_*.py" 2^>nul') do (
    if not defined LATEST set "LATEST=%%F"
)

if not defined LATEST (
    echo [ERROR] app\outlook_total_organizer_*.py not found.
    echo Put the code files in the app folder next to this batch file.
    echo.
    pause
    exit /b 1
)

echo Starting version: %LATEST%
echo.

rem Check python / py by really running "--version" (a Microsoft Store alias can exist
rem on PATH even when Python is not installed, so "where" is not reliable).
rem "python" is tried first: the "py" launcher can point to another Python on which
rem pywin32 is not installed/registered and crash with an access violation.
set "PYCMD="

python --version >nul 2>nul
if not errorlevel 1 set "PYCMD=python"

if not defined PYCMD (
    py --version >nul 2>nul
    if not errorlevel 1 set "PYCMD=py"
)

if not defined PYCMD (
    echo [ERROR] python not found.
    echo Install Python and make sure it is on PATH.
    echo If the Microsoft Store "python" alias is interfering, turn off the python.exe / python3.exe
    echo app execution aliases in Settings, then install Python from python.org again.
    echo.
    pause
    exit /b 1
)

echo Python command: %PYCMD%
echo.
"%PYCMD%" "app\%LATEST%"
set "RUN_RESULT=%errorlevel%"

echo.
if not "%RUN_RESULT%"=="0" (
    echo [ERROR] The tool exited with an error (exit code: %RUN_RESULT%). Check the messages above.
) else (
    echo Finished.
)
echo.
pause
