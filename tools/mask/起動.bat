@echo off
chcp 65001 > nul

echo マスクツール起動中...

py -m pip install -q -r "%~dp0requirements.txt" flask

start http://localhost:5000
py "%~dp0app.py"
