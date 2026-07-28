@echo off
chcp 65001 > nul

rem 入力の受け付けはすべて diagnose.py 側で行う。
rem バッチの set /p は文字コードの影響で入力待ちが素通りすることがあるため。

where git > nul 2>&1
if %errorlevel%==0 (
    git -C "%~dp0..\.." pull origin main > nul 2>&1
)

py -m pip install -q -r "%~dp0requirements.txt" > nul 2>&1

py "%~dp0diagnose.py" %*

echo.
pause
