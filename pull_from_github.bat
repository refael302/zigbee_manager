@echo off
cd /d "%~dp0"
git pull origin main
echo.
echo Project updated from GitHub.
pause
