@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"

REM Find pixi: check PATH first, then default install location
where pixi >nul 2>&1
if %errorlevel% == 0 (
    set "PIXI=pixi"
) else if exist "%USERPROFILE%\AppData\Local\pixi\bin\pixi.exe" (
    set "PIXI=%USERPROFILE%\AppData\Local\pixi\bin\pixi.exe"
) else (
    echo ERROR: pixi not found. Install from https://pixi.sh
    pause
    exit /b 1
)

"%PIXI%" run python -m sciview.launchers stable