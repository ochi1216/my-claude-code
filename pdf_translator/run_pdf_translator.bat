@echo off
rem PDF Gemini Translator - launcher script.
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

rem Script files follow pdf_translator_yyyymmdd_NN.py naming (old versions
rem are kept side by side on upgrade), so pick the newest one by sorting
rem filenames in descending order (works because the date/seq are
rem fixed-width, so name order == chronological order).
set "TARGET_SCRIPT="
for /f "delims=" %%f in ('dir /b /o-n "pdf_translator_????????_??.py" 2^>nul') do (
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

if "%GEMINI_API_KEY%"=="" goto :warn_no_api_key

:run_tool
echo Starting PDF Gemini Translator...
python "%TARGET_SCRIPT%"
if errorlevel 1 goto :run_failed

goto :end

:no_script
echo [ERROR] No file matching pdf_translator_yyyymmdd_NN.py was found.
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

:warn_no_api_key
echo.
echo [WARNING] The GEMINI_API_KEY environment variable is not set.
echo The tool will show an error immediately after it starts.
echo Example: setx GEMINI_API_KEY "your-api-key"
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
