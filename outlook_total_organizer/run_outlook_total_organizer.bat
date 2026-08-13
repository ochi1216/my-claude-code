@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem 同じフォルダ内の outlook_total_organizer_*.py のうち、
rem ファイル名の並び順（yyyymmdd_NN形式）で最も新しいものを自動選択して起動する。
rem コードのバージョンが上がっても、このバッチファイル自体は変更不要。

set "LATEST="
for /f "delims=" %%F in ('dir /b /o-n "outlook_total_organizer_*.py" 2^>nul') do (
    if not defined LATEST set "LATEST=%%F"
)

if not defined LATEST (
    echo [ERROR] outlook_total_organizer_*.py が見つかりません。
    echo このバッチファイルは outlook_total_organizer_*.py と同じフォルダに置いてください。
    echo.
    pause
    exit /b 1
)

echo 起動するバージョン: %LATEST%
echo.

rem "python"→"py"ランチャーの順に、実際に動くかどうかを"--version"の実行で確認する。
rem where（ファイルの存在確認のみ）は使わない。Windowsによっては、実体がインストール
rem されていなくても "python" コマンドがMicrosoft Storeへの誘導スタブとしてPATH上に
rem 存在することがあり、whereだけでは「見つかった」と誤判定してしまうため。
rem また、判定には "if errorlevel N" 形式を使う（"%%errorlevel%%" 変数はカッコで
rem 囲まれたif/elseの入れ子の中では実行時に正しく更新されないcmd.exeの既知の制限があり、
rem 前回配布した版はこれが原因でpython/pyの判定を誤り、エラー表示もされないまま
rem ウィンドウが閉じてしまっていたため）。
rem "python"を優先する（"py"ランチャーは、環境によって"python"コマンドとは別の
rem Python環境を指すことがあり、その場合pywin32が未インストール/未登録のまま
rem 実行されてアクセス違反（終了コード -1073741819）でクラッシュする事例が確認されたため）。
set "PYCMD="

python --version >nul 2>nul
if not errorlevel 1 set "PYCMD=python"

if not defined PYCMD (
    py --version >nul 2>nul
    if not errorlevel 1 set "PYCMD=py"
)

if not defined PYCMD (
    echo [ERROR] python が見つかりません。
    echo Python がインストールされ、PATHが通っているかご確認ください。
    echo （Microsoft Storeの「python」エイリアスが影響している場合は、
    echo   設定 ＞ アプリ ＞ アプリ実行エイリアス で python.exe / python3.exe を無効化した上で、
    echo   python.org 等から実体のあるPythonを入れ直してください。）
    echo.
    pause
    exit /b 1
)

echo 使用する起動コマンド: %PYCMD%
echo.
"%PYCMD%" "%LATEST%"
set "RUN_RESULT=%errorlevel%"

echo.
if not "%RUN_RESULT%"=="0" (
    echo [ERROR] 起動時にエラーが発生しました（終了コード: %RUN_RESULT%）。上記のメッセージをご確認ください。
) else (
    echo 終了しました。
)
echo.
pause
