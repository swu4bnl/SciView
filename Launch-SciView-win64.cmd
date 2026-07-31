@echo off
setlocal
cd /d "%~dp0"
title SciView Launcher

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_sciview_windows.ps1" %*
if errorlevel 1 (
    echo.
    echo SciView did not start. Review the messages above, then press any key to close this window.
    pause >nul
    exit /b 1
)
