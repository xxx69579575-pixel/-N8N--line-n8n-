@echo off
setlocal
cd /d "%~dp0" || exit /b 1
python "scripts\api_server.py"
exit /b %errorlevel%
