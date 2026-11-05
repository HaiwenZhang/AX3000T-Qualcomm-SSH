@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0test.ps1"
set "test_exit=%errorlevel%"
pause
exit /b %test_exit%
