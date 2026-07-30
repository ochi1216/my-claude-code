@echo off
setlocal enabledelayedexpansion

rem Launcher for the Power Automate PoC PowerShell scripts.
rem
rem WARNING - READ BEFORE EDITING THIS FILE:
rem This project previously shipped a batch file (emergency_alert_tool
rem \run_emergency_alert_tool.bat) with Japanese text saved as UTF-8. On the
rem user's Windows machine, cmd.exe was running under a non-UTF-8 console
rem codepage (e.g. Shift-JIS / CP932), so the Japanese bytes were misread as
rem stray command tokens, and the batch file failed with errors like:
rem   '...' is not recognized as an internal or external command
rem Fix applied: keep ALL text in .bat files pure ASCII, and save with CRLF
rem line endings. Do NOT add Japanese (or other non-ASCII) text to this file.
rem If you need localized messages, put them in the .ps1 scripts or a doc
rem instead, where UTF-8 is handled correctly by PowerShell.

cd /d "%~dp0"

where powershell >nul 2>nul
if errorlevel 1 (
    echo [ERROR] powershell was not found. This launcher requires Windows PowerShell.
    pause
    exit /b 1
)

rem Find the latest revision of each script by filename (yyyymmdd_NN sorts correctly).
set "LATEST_PROVISION="
for /f "delims=" %%F in ('dir /b /o-n "scripts\provision_sharepoint_*.ps1" 2^>nul') do (
    if not defined LATEST_PROVISION set "LATEST_PROVISION=%%F"
)

set "LATEST_DEPLOY="
for /f "delims=" %%F in ('dir /b /o-n "scripts\deploy_solution_*.ps1" 2^>nul') do (
    if not defined LATEST_DEPLOY set "LATEST_DEPLOY=%%F"
)

if not defined LATEST_PROVISION (
    echo [ERROR] No scripts\provision_sharepoint_*.ps1 file was found.
    pause
    exit /b 1
)
if not defined LATEST_DEPLOY (
    echo [ERROR] No scripts\deploy_solution_*.ps1 file was found.
    pause
    exit /b 1
)

echo Using provision script: scripts\%LATEST_PROVISION%
echo Using deploy script   : scripts\%LATEST_DEPLOY%
echo.

:MENU
echo ============================================
echo  Power Automate Safety Check-in - Launcher
echo ============================================
echo  1. Provision SharePoint lists and load data
echo  2. Export DEV solution and unpack (for Git)
echo  3. Pack and import solution into an environment
echo  4. Exit
echo ============================================
set /p CHOICE=Select an option (1-4):

if "%CHOICE%"=="1" goto PROVISION
if "%CHOICE%"=="2" goto EXPORT_UNPACK
if "%CHOICE%"=="3" goto PACK_IMPORT
if "%CHOICE%"=="4" goto END
echo Invalid choice.
echo.
goto MENU

:PROVISION
set /p SITEURL=SharePoint site URL (e.g. https://contoso.sharepoint.com/sites/EQSafetyCheckin):
set "MEMBERSFILE=config\members.json"
if not exist "%MEMBERSFILE%" (
    echo [INFO] config\members.json not found, using config\members.example.json (placeholders).
    set "MEMBERSFILE=config\members.example.json"
)
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\%LATEST_PROVISION%" -SiteUrl "%SITEURL%" -MembersFile "%MEMBERSFILE%"
pause
goto MENU

:EXPORT_UNPACK
set /p SOLUTIONNAME=Solution unique name (e.g. EQSafetyCheckin):
set /p ENVURL=DEV environment URL:
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\%LATEST_DEPLOY%" -Action export-unpack -SolutionName "%SOLUTIONNAME%" -EnvironmentUrl "%ENVURL%"
pause
goto MENU

:PACK_IMPORT
set /p SOLUTIONNAME=Solution unique name (e.g. EQSafetyCheckin):
set /p ENVURL=Target environment URL (TEST or PROD):
set /p MANAGEDANSWER=Import as Managed solution? (y/n):
if /i "%MANAGEDANSWER%"=="y" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\%LATEST_DEPLOY%" -Action pack-import -SolutionName "%SOLUTIONNAME%" -EnvironmentUrl "%ENVURL%" -Managed
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\%LATEST_DEPLOY%" -Action pack-import -SolutionName "%SOLUTIONNAME%" -EnvironmentUrl "%ENVURL%"
)
pause
goto MENU

:END
endlocal
exit /b 0
