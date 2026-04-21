@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   Install mitmproxy root cert to Windows trust
echo ================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0install_cert.ps1"
pause
