@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   Bandai Capture Launcher
echo ================================================
echo.
echo Launching PowerShell with ExecutionPolicy=Bypass
echo Click YES on the UAC prompt when it appears.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0start_capture.ps1"
echo.
echo ================================================
echo   PowerShell script exited
echo ================================================
pause
