@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title SciView Launcher

set "SCIVIEW_SETUP_ONLY=0"
set "SCIVIEW_ACCEPT_PIXI_INSTALL=0"
for %%A in (%*) do (
    if /i "%%~A"=="-SetupOnly" set "SCIVIEW_SETUP_ONLY=1"
    if /i "%%~A"=="-AcceptPixiInstall" set "SCIVIEW_ACCEPT_PIXI_INSTALL=1"
)

if /i "%SCIVIEW_FORCE_CMD_LAUNCHER%"=="1" goto compatibility_launcher

set "SCIVIEW_POLICY="
for /f "usebackq delims=" %%P in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-ExecutionPolicy" 2^>nul`) do set "SCIVIEW_POLICY=%%P"

if /i not "%SCIVIEW_POLICY%"=="Bypass" goto compatibility_launcher

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_sciview_windows.ps1" %*
if errorlevel 1 (
    echo.
    echo SciView did not start. Review the messages above, then press any key to close this window.
    pause >nul
    exit /b 1
)
exit /b 0

:compatibility_launcher
echo Windows policy blocks local PowerShell scripts.
echo Starting SciView with the compatibility launcher.
echo.

call :find_pixi
if defined PIXI_EXE goto pixi_ready

echo SciView needs Pixi to prepare its environment.
if "%SCIVIEW_ACCEPT_PIXI_INSTALL%"=="1" goto install_pixi
set "SCIVIEW_INSTALL_PIXI="
set /p "SCIVIEW_INSTALL_PIXI=Install Pixi for this user account? [Y/n] "
if /i "%SCIVIEW_INSTALL_PIXI%"=="n" goto setup_cancelled
if /i "%SCIVIEW_INSTALL_PIXI%"=="no" goto setup_cancelled

:install_pixi
echo.
echo Downloading and installing Pixi...
powershell.exe -NoProfile -Command "Invoke-RestMethod -UseBasicParsing https://pixi.sh/install.ps1 | Invoke-Expression"
if errorlevel 1 goto pixi_install_failed

call :find_pixi
if not defined PIXI_EXE goto pixi_not_found

:pixi_ready
echo.
echo Preparing SciView dependencies...
call "%PIXI_EXE%" install
if errorlevel 1 goto dependency_install_failed

if "%SCIVIEW_SETUP_ONLY%"=="1" (
    echo.
    echo SciView setup is ready.
    exit /b 0
)

echo.
echo Starting SciView...
call "%PIXI_EXE%" run launch-app
if errorlevel 1 goto app_failed
exit /b 0

:find_pixi
set "PIXI_EXE="
for /f "delims=" %%P in ('where.exe pixi 2^>nul') do if not defined PIXI_EXE set "PIXI_EXE=%%P"
if not defined PIXI_EXE if exist "%LOCALAPPDATA%\pixi\bin\pixi.exe" set "PIXI_EXE=%LOCALAPPDATA%\pixi\bin\pixi.exe"
if not defined PIXI_EXE if exist "%USERPROFILE%\.pixi\bin\pixi.exe" set "PIXI_EXE=%USERPROFILE%\.pixi\bin\pixi.exe"
exit /b 0

:setup_cancelled
echo.
echo Setup was cancelled. SciView needs Pixi before it can start.
goto launcher_failed

:pixi_install_failed
echo.
echo Pixi installation failed.
goto launcher_failed

:pixi_not_found
echo.
echo Pixi was installed, but the launcher could not find it.
echo Close this window and start SciView again.
goto launcher_failed

:dependency_install_failed
echo.
echo SciView could not prepare its dependencies. Review the error above, then run the launcher again.
goto launcher_failed

:app_failed
echo.
echo SciView exited with an error.

:launcher_failed
echo.
echo SciView did not start. Review the messages above, then press any key to close this window.
pause >nul
exit /b 1
