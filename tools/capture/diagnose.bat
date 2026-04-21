@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0diagnose.ps1"
pause
