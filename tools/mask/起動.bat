@echo off
chcp 65001 > nul

echo マスクツール起動中...

rem 最新版に更新（gitがある場合のみ）
where git > nul 2>&1
if %errorlevel%==0 (
    echo 最新版を確認中...
    git -C "%~dp0..\.." pull origin main
)

py -m pip install -q -r "%~dp0requirements.txt" flask

start http://localhost:5000
py "%~dp0app.py"
