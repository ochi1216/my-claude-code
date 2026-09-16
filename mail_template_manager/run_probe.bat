@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ---------------------------------------------------------------
rem Mail Template Manager - M0 probe launcher
rem
rem This file is intentionally written in ASCII only. The Japanese
rem explanation is printed by probe_outlook.py, which writes UTF-8.
rem Putting Japanese text in a .bat file makes it depend on the
rem console code page and it shows up as mojibake.
rem ---------------------------------------------------------------

rem Use UTF-8 in the console so that the Japanese output is readable.
chcp 65001 >nul 2>nul

rem Prefer "python" over the "py" launcher, and verify it actually runs.
rem "where" is not enough: Windows ships a Microsoft Store alias stub on
rem PATH even when Python is not installed, so "where python" succeeds
rem while running it does not. The "py" launcher may also point at a
rem different Python where pywin32 is not registered.
set "PYCMD="

python --version >nul 2>nul
if not errorlevel 1 set "PYCMD=python"

if not defined PYCMD (
    py --version >nul 2>nul
    if not errorlevel 1 set "PYCMD=py"
)

if not defined PYCMD (
    echo [ERROR] Python was not found.
    echo Please install Python and make sure it is on PATH.
    echo.
    pause
    exit /b 1
)

"%PYCMD%" probe_outlook.py
set "RUN_RESULT=%errorlevel%"

if not "%RUN_RESULT%"=="0" (
    echo.
    echo [ERROR] The probe exited with code %RUN_RESULT%.
    echo Please send the message above together with any probe_result_*.txt file.
    echo.
    pause
)

exit /b %RUN_RESULT%
