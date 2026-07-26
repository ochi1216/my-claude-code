@echo off
chcp 65001 > nul
setlocal

echo =========================================================
echo [Step 1/3] run_youtube_channel_remove_auto.bat を実行します
echo =========================================================
call run_youtube_channel_remove_auto.bat
echo [Step 1] 完了. 終了コード: %ERRORLEVEL%
echo.

echo ---------------------------------------------------------
echo 次の処理まで 5秒間 待機します...
echo ---------------------------------------------------------
timeout /t 5 /nobreak >nul

echo =========================================================
echo [Step 2/3] run_youtube_List_auto_setup.bat を実行します
echo =========================================================
call run_youtube_List_auto_setup.bat
echo [Step 2] 完了. 終了コード: %ERRORLEVEL%
echo.

echo ---------------------------------------------------------
echo 次の処理まで 5秒間 待機します...
echo ---------------------------------------------------------
timeout /t 5 /nobreak >nul

echo =========================================================
echo [Step 3/3] run_youtube_summary_auto.bat を実行します
echo =========================================================
call run_youtube_summary_auto.bat
echo [Step 3] 完了. 終了コード: %ERRORLEVEL%
echo.

echo =========================================================
echo 全てのタスクが完了しました。
echo =========================================================
pause
exit /b