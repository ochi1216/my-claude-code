@echo off
rem ---------------------------------------------------------------------------
rem run_tool_launcher.bat - starts the my-claude-code tool launcher.
rem
rem Point the desktop shortcut at THIS file. It always picks the newest
rem tool_launcher_yyyymmdd_NN.py in this folder, so it never needs editing
rem when the launcher is upgraded.
rem
rem NOTE: This file intentionally contains ONLY ASCII text. Japanese Windows
rem cmd.exe reads .bat files using the system codepage (Shift-JIS/CP932),
rem not UTF-8. A UTF-8-encoded file mixed with Shift-JIS parsing corrupts
rem multi-byte Japanese bytes together with the ASCII keywords next to them
rem (e.g. "goto" was being mangled into "oto"), causing cryptic
rem "not recognized as an internal or external command" errors and an
rem instant window close. `chcp 65001` does NOT fix this, because it only
rem changes console output/input encoding, not how cmd.exe parses the
rem script's own bytes. Keeping this file pure ASCII avoids the problem
rem entirely, regardless of the Windows locale.
rem ---------------------------------------------------------------------------

setlocal enabledelayedexpansion
cd /d "%~dp0"

rem Old versions are kept side by side on upgrade, so pick the newest one by
rem sorting filenames in descending order (works because the date/seq are
rem fixed-width, so name order == chronological order).
set "TARGET_SCRIPT="
for /f "delims=" %%f in ('dir /b /o-n "tool_launcher_????????_??.py" 2^>nul') do (
    if not defined TARGET_SCRIPT set "TARGET_SCRIPT=%%f"
)
if not defined TARGET_SCRIPT goto :no_script

if not exist "tools.json" goto :no_config

rem Resolve the interpreter with "python" ONLY.
rem
rem Do NOT add a fallback to "py" on this machine. "py" resolves to
rem  ...\Python313\python3.13t.exe  - the experimental free-threading build
rem of Python 3.13.5 - where pywin32 terminates without printing anything and
rem google-genai fails to import (pydantic_core has no free-threaded wheel).
rem "python" resolves to C:\Program Files\Python\python.exe (3.13.3), which
rem has pywin32, google-genai and streamlit installed.
rem
rem "--version" is used instead of "where" on purpose: on Windows a
rem Microsoft Store redirect stub named python.exe can sit on PATH without a
rem real interpreter behind it, and "where" would report a false positive.
python --version >nul 2>nul
if errorlevel 1 goto :no_python

echo Starting %TARGET_SCRIPT% ...
python "%TARGET_SCRIPT%"
if errorlevel 1 goto :run_failed

goto :end

:no_script
echo [ERROR] No file matching tool_launcher_yyyymmdd_NN.py was found in:
echo         %~dp0
echo Run "git pull" in the my-claude-code folder and try again.
pause
exit /b 1

:no_config
echo [ERROR] tools.json was not found in:
echo         %~dp0
echo The launcher reads its tool list from that file.
echo Run "git pull" in the my-claude-code folder and try again.
pause
exit /b 1

:no_python
echo [ERROR] Python was not found.
echo Install Python 3.9 or later, make sure it is on PATH, then try again.
echo (If the Microsoft Store "python" alias is enabled, turn it off under
echo  Settings ^> Apps ^> App execution aliases, and reinstall Python from
echo  python.org.)
pause
exit /b 1

:run_failed
echo.
echo [ERROR] The launcher exited with an error. See the messages above.
pause
goto :end

:end
endlocal
