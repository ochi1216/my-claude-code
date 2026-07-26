@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
set PYTHONIOENCODING=utf-8

rem ========================================
rem YouTube Summary Auto Runner
rem VERSION 20260726_01
rem Purpose:
rem   - Use isolated Chrome profile
rem   - Fixed debug port 9222
rem   - Avoid Documents sync/monitoring area
rem   - Avoid killing normal Chrome as much as possible
rem ========================================

cd /d "C:\Users\nx023836\Documents\PythonScripts\Youtube"

rem ========================================
rem Log setup
rem ========================================
set "LOG_DIR=logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set "TIMESTAMP=%datetime:~0,8%_%datetime:~8,6%"
set "LOG_FILE=%LOG_DIR%\run_log_%TIMESTAMP%.log"

echo ========================================= >> "%LOG_FILE%" 2>&1
echo YouTube Summary Auto Execution >> "%LOG_FILE%" 2>&1
echo VERSION: 20260726_01 >> "%LOG_FILE%" 2>&1
echo Start: %date% %time% >> "%LOG_FILE%" 2>&1
echo ========================================= >> "%LOG_FILE%" 2>&1

rem ========================================
rem Settings
rem ========================================
set "DEBUG_PORT=9222"
set "CHROME_PROFILE_NAME=ChromeDebugProfile_20260725"
set "CHROME_USER_DATA=%LOCALAPPDATA%\%CHROME_PROFILE_NAME%"
set "INITIAL_URL=https://www.youtube.com/feed/subscriptions"

echo Chrome User Data: !CHROME_USER_DATA! >> "%LOG_FILE%" 2>&1
echo Chrome Profile Name: !CHROME_PROFILE_NAME! >> "%LOG_FILE%" 2>&1
echo Debug Port: !DEBUG_PORT! >> "%LOG_FILE%" 2>&1
echo Initial URL: !INITIAL_URL! >> "%LOG_FILE%" 2>&1

rem ========================================
rem Step 1: Kill only target Chrome processes
rem ========================================
echo. >> "%LOG_FILE%" 2>&1
echo [1/7] Cleaning up target Chrome processes only... >> "%LOG_FILE%" 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$targets = Get-CimInstance Win32_Process -Filter \"name = 'chrome.exe'\" | Where-Object { ($_.CommandLine -like '*%CHROME_PROFILE_NAME%*') -or ($_.CommandLine -like '*remote-debugging-port=%DEBUG_PORT%*') }; if ($targets) { $targets | ForEach-Object { Write-Output ('Stopping chrome PID=' + $_.ProcessId + ' CMD=' + $_.CommandLine); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } else { Write-Output 'No target Chrome process found.' }" >> "%LOG_FILE%" 2>&1

timeout /t 2 /nobreak >NUL 2>&1

rem ========================================
rem Step 2: Kill ChromeDriver processes
rem ========================================
echo. >> "%LOG_FILE%" 2>&1
echo [2/7] Cleaning up ChromeDriver processes... >> "%LOG_FILE%" 2>&1

tasklist /FI "IMAGENAME eq chromedriver.exe" 2>NUL | find /I "chromedriver.exe" >NUL 2>&1
if not errorlevel 1 (
    echo ChromeDriver process found. Terminating... >> "%LOG_FILE%" 2>&1
    taskkill /F /IM chromedriver.exe /T >> "%LOG_FILE%" 2>&1
    timeout /t 1 /nobreak >NUL 2>&1
    echo ChromeDriver processes terminated. >> "%LOG_FILE%" 2>&1
) else (
    echo No ChromeDriver process found. >> "%LOG_FILE%" 2>&1
)

rem ========================================
rem Step 3: Prepare Chrome profile directory and remove lock files
rem ========================================
echo. >> "%LOG_FILE%" 2>&1
echo [3/7] Preparing Chrome debug profile... >> "%LOG_FILE%" 2>&1

if not exist "!CHROME_USER_DATA!" (
    echo Creating directory: !CHROME_USER_DATA! >> "%LOG_FILE%" 2>&1
    mkdir "!CHROME_USER_DATA!" >> "%LOG_FILE%" 2>&1
) else (
    echo Directory found: !CHROME_USER_DATA! >> "%LOG_FILE%" 2>&1
)

if exist "!CHROME_USER_DATA!\SingletonLock" (
    del /F /Q "!CHROME_USER_DATA!\SingletonLock" >NUL 2>&1
    echo SingletonLock deleted. >> "%LOG_FILE%" 2>&1
)
if exist "!CHROME_USER_DATA!\SingletonSocket" (
    del /F /Q "!CHROME_USER_DATA!\SingletonSocket" >NUL 2>&1
    echo SingletonSocket deleted. >> "%LOG_FILE%" 2>&1
)
if exist "!CHROME_USER_DATA!\SingletonCookie" (
    del /F /Q "!CHROME_USER_DATA!\SingletonCookie" >NUL 2>&1
    echo SingletonCookie deleted. >> "%LOG_FILE%" 2>&1
)
if exist "!CHROME_USER_DATA!\lockfile" (
    del /F /Q "!CHROME_USER_DATA!\lockfile" >NUL 2>&1
    echo lockfile deleted. >> "%LOG_FILE%" 2>&1
)

echo Chrome profile preparation completed. >> "%LOG_FILE%" 2>&1
timeout /t 2 /nobreak >NUL 2>&1

rem ========================================
rem Step 4: Start Chrome with fixed debug port
rem ========================================
echo. >> "%LOG_FILE%" 2>&1
echo [4/7] Starting Chrome in debug mode... >> "%LOG_FILE%" 2>&1

set "CHROME_PATH="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
) else (
    echo ERROR: Chrome not found! >> "%LOG_FILE%" 2>&1
    exit /b 1
)

echo Chrome path: !CHROME_PATH! >> "%LOG_FILE%" 2>&1

start "" "!CHROME_PATH!" ^
  --remote-debugging-port=!DEBUG_PORT! ^
  --user-data-dir="!CHROME_USER_DATA!" ^
  --profile-directory=Default ^
  --no-first-run ^
  --no-default-browser-check ^
  --disable-sync ^
  --disable-features=Translate ^
  --metrics-recording-only ^
  --disable-default-apps ^
  --disable-dev-shm-usage ^
  --disable-gpu ^
  --no-sandbox ^
  --new-window "!INITIAL_URL!"

echo Chrome start command executed. >> "%LOG_FILE%" 2>&1
echo Waiting for Chrome initialization 8 seconds... >> "%LOG_FILE%" 2>&1
timeout /t 8 /nobreak >NUL 2>&1

rem ========================================
rem Step 5: Check debug port
rem ========================================
echo. >> "%LOG_FILE%" 2>&1
echo [5/7] Checking port !DEBUG_PORT!... >> "%LOG_FILE%" 2>&1

netstat -ano 2>NUL | findstr ":!DEBUG_PORT!" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo WARNING: Port !DEBUG_PORT! was not detected by netstat. >> "%LOG_FILE%" 2>&1
) else (
    echo Port !DEBUG_PORT! detected. >> "%LOG_FILE%" 2>&1
)

rem ========================================
rem Step 6: Search latest Python script
rem ========================================
echo. >> "%LOG_FILE%" 2>&1
echo [6/7] Searching for latest script... >> "%LOG_FILE%" 2>&1

set "LATEST_SCRIPT="
for /f "delims=" %%f in ('dir /b /o-n youtube_summary_list_*.py 2^>nul') do (
    set "LATEST_SCRIPT=%%f"
    goto :found
)

:found
if not defined LATEST_SCRIPT (
    echo ERROR: No script found! >> "%LOG_FILE%" 2>&1
    exit /b 1
)

echo Latest script found: !LATEST_SCRIPT! >> "%LOG_FILE%" 2>&1

rem ========================================
rem Step 7: Execute Python
rem ========================================
echo. >> "%LOG_FILE%" 2>&1
echo [7/7] Executing Python script... >> "%LOG_FILE%" 2>&1
echo [DIAG] Python fixed path check:
echo "C:\Users\nx023836\AppData\Local\Programs\Python\Python313\python.exe" "!LATEST_SCRIPT!" --auto --batch-size 10 --playlists V S A B N M >> "%LOG_FILE%" 2>&1
echo ========================================= >> "%LOG_FILE%" 2>&1

echo [DIAG] Python fixed path check:
"C:\Users\nx023836\AppData\Local\Programs\Python\Python313\python.exe" --version
"C:\Users\nx023836\AppData\Local\Programs\Python\Python313\python.exe" -c "import sys; print(sys.executable)"
"C:\Users\nx023836\AppData\Local\Programs\Python\Python313\python.exe" -c "import psutil; print('psutil OK', psutil.__version__)"

"C:\Users\nx023836\AppData\Local\Programs\Python\Python313\python.exe" "!LATEST_SCRIPT!" --auto --batch-size 1 --playlists V S A B N M

set "EXIT_CODE=!ERRORLEVEL!"

echo. >> "%LOG_FILE%" 2>&1
echo Python execution completed with exit code: !EXIT_CODE! >> "%LOG_FILE%" 2>&1

rem ========================================
rem Post-execution cleanup
rem ========================================
echo. >> "%LOG_FILE%" 2>&1
echo ========================================= >> "%LOG_FILE%" 2>&1
echo Post-execution cleanup... >> "%LOG_FILE%" 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$targets = Get-CimInstance Win32_Process -Filter \"name = 'chrome.exe'\" | Where-Object { ($_.CommandLine -like '*%CHROME_PROFILE_NAME%*') -or ($_.CommandLine -like '*remote-debugging-port=%DEBUG_PORT%*') }; if ($targets) { $targets | ForEach-Object { Write-Output ('Stopping chrome PID=' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } else { Write-Output 'No target Chrome process found for cleanup.' }" >> "%LOG_FILE%" 2>&1

tasklist /FI "IMAGENAME eq chromedriver.exe" 2>NUL | find /I "chromedriver.exe" >NUL 2>&1
if not errorlevel 1 (
    echo Terminating ChromeDriver processes... >> "%LOG_FILE%" 2>&1
    taskkill /F /IM chromedriver.exe /T >> "%LOG_FILE%" 2>&1
) else (
    echo ChromeDriver already terminated. >> "%LOG_FILE%" 2>&1
)

timeout /t 1 /nobreak >NUL 2>&1

rem ========================================
rem Execution summary
rem ========================================
echo. >> "%LOG_FILE%" 2>&1
echo ========================================= >> "%LOG_FILE%" 2>&1
echo Execution Summary >> "%LOG_FILE%" 2>&1
echo ========================================= >> "%LOG_FILE%" 2>&1
echo Script: !LATEST_SCRIPT! >> "%LOG_FILE%" 2>&1
echo Chrome User Data: !CHROME_USER_DATA! >> "%LOG_FILE%" 2>&1
echo Debug Port: !DEBUG_PORT! >> "%LOG_FILE%" 2>&1
echo Exit Code: !EXIT_CODE! >> "%LOG_FILE%" 2>&1
echo End Time: %date% %time% >> "%LOG_FILE%" 2>&1
echo ========================================= >> "%LOG_FILE%" 2>&1

exit /b !EXIT_CODE!

endlocal