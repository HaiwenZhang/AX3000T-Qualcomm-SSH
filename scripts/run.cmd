@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
set "tool_exit=%errorlevel%"
echo.
if not "%tool_exit%"=="0" echo STOP: review the error above before continuing.
pause
exit /b %tool_exit%
