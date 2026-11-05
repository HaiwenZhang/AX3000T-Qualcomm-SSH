@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\firewall.ps1" -Action Add %*
set "rule_exit=%errorlevel%"
pause
exit /b %rule_exit%
