@echo off
rem Word Gemini Translator - launcher script.
rem Double-click this file to set up (first run only: creates a venv and
rem installs dependencies) and start the tool.
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

setlocal enabledelayedexpansion
cd /d "%~dp0"

rem NOTE: the folder is named word_translator but the script files are named
rem word_translation_yyyymmdd_NN.py (the prefix was kept from the original
rem tool). Do not "fix" the wildcard below to word_translator_*.py or nothing
rem will be found. Old versions are kept side by side on upgrade, so pick the
rem newest one by sorting filenames in descending order (works because the
rem date/seq are fixed-width, so name order == chronological order).
set "TARGET_SCRIPT="
for /f "delims=" %%f in ('dir /b /o-n "word_translation_????????_??.py" 2^>nul') do (
    if not defined TARGET_SCRIPT set "TARGET_SCRIPT=%%f"
)
if not defined TARGET_SCRIPT goto :no_script

echo Target script: %TARGET_SCRIPT%

where python >nul 2>nul
if errorlevel 1 goto :no_python

if exist venv goto :venv_ready
echo First-time setup: creating virtual environment...
python -m venv venv
if errorlevel 1 goto :venv_failed

:venv_ready
call venv\Scripts\activate.bat

echo Checking dependencies...
pip install -q -r requirements.txt
if errorlevel 1 goto :pip_failed

rem Since 20260812_01 the Gemini call goes through the shared module
rem gemini_client.py, which falls back to the home-PC proxy when the direct
rem call fails. A proxy-only setup (GEMINI_API_KEY empty but GEMINI_PROXY_URL
rem set) is perfectly valid, so warn only when BOTH are missing. Checking
rem GEMINI_API_KEY alone would stop with a warning + pause on every start.
if not "%GEMINI_API_KEY%"=="" goto :run_tool
if not "%GEMINI_PROXY_URL%"=="" goto :run_tool
goto :warn_no_credentials

:run_tool
echo Starting Word Gemini Translator...
python "%TARGET_SCRIPT%"
if errorlevel 1 goto :run_failed

goto :end

:no_script
echo [ERROR] No file matching word_translation_yyyymmdd_NN.py was found.
pause
exit /b 1

:no_python
echo [ERROR] Python was not found.
echo Please install Python 3.9 or later and add it to PATH, then try again.
pause
exit /b 1

:venv_failed
echo [ERROR] Failed to create the virtual environment.
pause
exit /b 1

:pip_failed
echo [ERROR] Failed to install dependencies.
pause
exit /b 1

:warn_no_credentials
echo.
echo [WARNING] Neither GEMINI_API_KEY nor GEMINI_PROXY_URL is set.
echo The tool will show an error immediately after it starts.
echo Set at least one of them:
echo   setx GEMINI_API_KEY "your-api-key"
echo   setx GEMINI_PROXY_URL "https://xxxx.ngrok-free.dev"
echo (After running setx, you must open a NEW Command Prompt window.)
echo.
pause
goto :run_tool

:run_failed
echo.
echo [ERROR] Something went wrong while running the tool. See the messages above.
pause
goto :end

:end
endlocal
