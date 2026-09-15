@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\app-control.ps1" -Action Stop
if errorlevel 1 (
    echo.
    echo ExamPilot could not stop. See the message above.
    pause
)
endlocal

