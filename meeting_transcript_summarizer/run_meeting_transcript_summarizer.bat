@echo off
REM ================================================================
REM 会議録画 文字起こし・要約ツール 起動バッチ
REM このフォルダ内の meeting_transcript_summarizer_*.py のうち、
REM ファイル名(YYYYMMDD_連番)が最も新しいものを自動的に選んで起動する。
REM バージョンアップ時に本体スクリプトが増えても、このバッチファイル自体は変更不要。
REM ================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "LATEST="
for /f "delims=" %%F in ('dir /b /o-n "meeting_transcript_summarizer_*.py" 2^>nul') do if not defined LATEST set "LATEST=%%F"

if defined LATEST goto :found
echo [エラー] meeting_transcript_summarizer_*.py が見つかりません。
pause
exit /b 1

:found
echo 起動します: %LATEST%

where python >nul 2>nul
if errorlevel 1 goto :try_py
python "%LATEST%"
goto :check_result

:try_py
where py >nul 2>nul
if errorlevel 1 goto :no_python
py "%LATEST%"
goto :check_result

:no_python
echo [エラー] python が見つかりません。Pythonをインストールし、PATHを通してください。
pause
exit /b 1

:check_result
if not errorlevel 1 goto :eof
echo [エラー] ツールの実行中にエラーが発生しました。
pause
