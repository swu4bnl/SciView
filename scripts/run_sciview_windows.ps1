param(
    [switch]$SetupOnly,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$LauncherArgs
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$ProjectRoot\src;$env:PYTHONPATH" } else { "$ProjectRoot\src" }

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host $Message -ForegroundColor Cyan
}

function Find-ManagedPythonTool {
    $command = Get-Command pixi -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "pixi\bin\pixi.exe"),
        (Join-Path $env:USERPROFILE ".pixi\bin\pixi.exe")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Install-ManagedPythonTool {
    Write-Host "SciView needs to prepare a local Python environment before it can start."
    Write-Host "This launcher uses Pixi, a small Python environment manager, to install SciView dependencies."
    Write-Host "Pixi will be installed for your user account only."
    Write-Host "No administrator permission is required."
    Write-Host ""

    $answer = Read-Host "Install Pixi now? [Y/n]"
    if ($answer -match '^(n|no)$') {
        throw "Setup was cancelled. SciView cannot start until Pixi is installed."
    }

    Write-Step "Downloading and installing Pixi..."
    Invoke-RestMethod -UseBasicParsing https://pixi.sh/install.ps1 | Invoke-Expression

    $env:Path = "$env:LOCALAPPDATA\pixi\bin;$env:USERPROFILE\.pixi\bin;$env:Path"
    $tool = Find-ManagedPythonTool
    if ($null -eq $tool) {
        throw "Pixi was installed, but this launcher could not find it. Close this window and launch SciView again."
    }
    return $tool
}

try {
    Write-Host "SciView Launcher" -ForegroundColor Green
    Write-Host "This window uses Pixi to prepare the Python environment and start SciView."

    $tool = Find-ManagedPythonTool
    if ($null -eq $tool) {
        $tool = Install-ManagedPythonTool
    }

    Write-Step "Preparing SciView dependencies..."
    & $tool install
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency setup failed. Check your internet connection and try again."
    }

    if ($SetupOnly) {
        Write-Host ""
        Write-Host "SciView setup is ready." -ForegroundColor Green
        exit 0
    }

    Write-Step "Starting SciView..."
    $launchArgs = @("run", "launch-app") + $LauncherArgs
    & $tool @launchArgs
    if ($LASTEXITCODE -ne 0) {
        throw "SciView exited with an error."
    }
} catch {
    Write-Host ""
    Write-Host "SciView could not start." -ForegroundColor Red
    Write-Host $_.Exception.Message
    Write-Host ""
    Write-Host "If this keeps happening, send the text in this window to a SciView developer."
    exit 1
}