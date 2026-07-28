@echo off
chcp 65001 > nul
setlocal

echo ============================================================
echo  マスク診断ツール
echo  マスクされずに残った値が、ファイルのどこにあるか調べます
echo ============================================================
echo.

rem 最新版に更新（gitがある場合のみ）
where git > nul 2>&1
if %errorlevel%==0 (
    git -C "%~dp0..\.." pull origin main > nul 2>&1
)

py -m pip install -q -r "%~dp0requirements.txt" > nul 2>&1

rem ファイル: ドラッグ＆ドロップされていればそれを使う
set "TARGET=%~1"
if "%TARGET%"=="" (
    echo 調べたいファイルをこのウィンドウにドラッグして Enter
    echo （このバッチにファイルを直接ドラッグしても使えます）
    set /p "TARGET=ファイル: "
)

rem 前後のダブルクォートを除去
set TARGET=%TARGET:"=%

if not exist "%TARGET%" (
    echo.
    echo ファイルが見つかりません: %TARGET%
    echo.
    pause
    exit /b 1
)

echo.
echo 対象ファイル: %TARGET%
echo.
echo マスクされずに残った値を入力して Enter
echo （例: 鈴木一郎）
set /p "VALUE=残った値: "

if "%VALUE%"=="" (
    echo.
    echo 値が入力されていません。
    echo.
    pause
    exit /b 1
)

echo.
py "%~dp0診断.py" "%TARGET%" "%VALUE%"

echo.
echo ============================================================
echo  上の内容をコピーして共有してください
echo  （値そのものが機密なら、その部分だけ伏せてください）
echo ============================================================
echo.
pause
