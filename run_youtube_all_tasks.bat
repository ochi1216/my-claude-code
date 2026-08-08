@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul

rem ========================================
rem YouTube All Tasks Runner (chained)
rem Version is tracked in Git, not in this file.
rem
rem Usage:
rem   run_youtube_all_tasks.bat        ... interactive (pauses at the end)
rem   run_youtube_all_tasks.bat auto   ... unattended (no pause; for Task Scheduler)
rem
rem [20260808] Changes:
rem   - cd /d "%~dp0" so the chain works regardless of the caller's
rem     working directory (Task Scheduler "Start in" is often different).
rem   - Record each step's exit code and report them together at the end.
rem     Previously a failing step was echoed and then silently ignored,
rem     so a night where a step died looked the same as a healthy one.
rem   - The morning brief is NOT part of this chain: this chain runs
rem     4 times a day (02:00 / 05:00 / 11:30 / 20:00) and the brief
rem     must be sent once, so it is scheduled separately.
rem   - pause only in interactive mode; unattended runs would hang forever.
rem ========================================

cd /d "%~dp0"

rem ========================================
rem Suspend check
rem A previous run may be paused, waiting for a human to clear Google's
rem challenge page. While it waits, this whole chain must do nothing:
rem Step 1 removes videos from the playlists, and running it before the
rem summaries are finished would drop videos that were never summarized.
rem Exit code 1 means suspended. Any other code means the check itself
rem could not run, in which case we deliberately continue as usual.
rem ========================================
python check_suspend_lock.py
set "LOCKRC=!ERRORLEVEL!"
if "!LOCKRC!"=="1" goto :suspended

set "RC1=0"
set "RC2=0"
set "RC3=0"
set "FAILED="

echo =========================================================
echo [Step 1/3] run_youtube_channel_remove_auto.bat を実行します
echo =========================================================
call run_youtube_channel_remove_auto.bat
set "RC1=!ERRORLEVEL!"
echo [Step 1] 完了. 終了コード: !RC1!
if not "!RC1!"=="0" set "FAILED=!FAILED! Step1-remove"
echo.

echo ---------------------------------------------------------
echo 次の処理まで 5秒間 待機します...
echo ---------------------------------------------------------
timeout /t 5 /nobreak >nul

echo =========================================================
echo [Step 2/3] run_youtube_List_auto_setup.bat を実行します
echo =========================================================
call run_youtube_List_auto_setup.bat
set "RC2=!ERRORLEVEL!"
echo [Step 2] 完了. 終了コード: !RC2!
if not "!RC2!"=="0" set "FAILED=!FAILED! Step2-setup"
echo.

echo ---------------------------------------------------------
echo 次の処理まで 5秒間 待機します...
echo ---------------------------------------------------------
timeout /t 5 /nobreak >nul

echo =========================================================
echo [Step 3/3] run_youtube_summary_auto.bat を実行します
echo =========================================================
call run_youtube_summary_auto.bat
set "RC3=!ERRORLEVEL!"
echo [Step 3] 完了. 終了コード: !RC3!
if not "!RC3!"=="0" set "FAILED=!FAILED! Step3-summary"
echo.

echo =========================================================
echo Execution Summary
echo =========================================================
echo   Step 1 remove  : !RC1!
echo   Step 2 setup   : !RC2!
echo   Step 3 summary : !RC3!
echo =========================================================

if defined FAILED (
    echo RESULT: FAILED -!FAILED!
    set "EXIT_CODE=1"
) else (
    echo RESULT: All steps completed successfully.
    set "EXIT_CODE=0"
)
echo =========================================================

rem Pause only when run interactively. A scheduled run passing "auto"
rem must not block on user input.
if /I not "%~1"=="auto" pause

exit /b !EXIT_CODE!

:suspended
echo =========================================================
echo SKIPPED: 前回の実行が確認画面の解除待ちで停止中です。
echo このチェーンは何もせずに終了します。
echo =========================================================
if /I not "%~1"=="auto" pause
exit /b 0

endlocal
