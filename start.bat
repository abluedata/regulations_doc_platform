@echo off
REM 双击或在 cmd 中运行：一键启动全部服务
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_all.ps1" %*
exit /b %ERRORLEVEL%
