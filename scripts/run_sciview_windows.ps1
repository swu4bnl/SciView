param(
    [switch]$SetupOnly,
    [switch]$NoAutoPull,
    [switch]$AcceptPixiInstall,

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

function Test-TruthyFlag {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }

    switch -Regex ($Value.Trim().ToLowerInvariant()) {
        '^(1|true|yes|on)$' { return $true }
        default { return $false }
    }
}

function Invoke-SourceAutoUpdate {
    param(
        [bool]$Enabled,
        [string]$PixiExecutable
    )

    if (-not $Enabled) {
        Write-Host "Skipping SciView source update check (--NoAutoPull)."
        return $false
    }

    if (-not (Test-Path (Join-Path $ProjectRoot ".git"))) {
        Write-Host "Skipping SciView source update check (not a git checkout)."
        return $false
    }

    if ([string]::IsNullOrWhiteSpace($PixiExecutable)) {
        Write-Host "Skipping SciView source update check (Pixi-managed git not available)."
        return $false
    }

    $gitPrefix = @("run", "--", "git", "-C", $ProjectRoot)
    Write-Step "Checking for SciView source updates..."
    try {
        $fetchArgs = $gitPrefix + @("fetch", "--quiet")
        & $PixiExecutable @fetchArgs
        if ($LASTEXITCODE -ne 0) {
            throw "git fetch exited with code $LASTEXITCODE"
        }

        $upstreamArgs = $gitPrefix + @("rev-parse", "--abbrev-ref", "--symbolic-full-name", '@{upstream}')
        $upstreamOutput = & $PixiExecutable @upstreamArgs 2>$null
        $upstreamExitCode = $LASTEXITCODE
        $upstream = ([string]$upstreamOutput).Trim()
        if ($upstreamExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($upstream)) {
            Write-Host "Skipping SciView source update (current branch has no upstream)."
            return $false
        }

        $behindArgs = $gitPrefix + @("rev-list", "--count", "HEAD..$upstream")
        $behind = [int](& $PixiExecutable @behindArgs)
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to compare the current branch with $upstream"
        }
        if ($behind -eq 0) {
            Write-Host "SciView is up to date."
            return $false
        }

        Write-Host "$behind update commit(s) available from $upstream."
        $answer = Read-Host "Update SciView now? [y/N]"
        if ($answer -notmatch '^(y|yes)$') {
            Write-Host "Skipping SciView source update."
            return $false
        }

        $mergeArgs = $gitPrefix + @("merge", "--ff-only", $upstream)
        & $PixiExecutable @mergeArgs | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "git merge --ff-only exited with code $LASTEXITCODE"
        }
        Write-Host "SciView source updated."
        return $true
    }
    catch {
        Write-Host "Skipping source auto-update (non-fatal): $($_.Exception.Message)"
        return $false
    }
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

    if (-not $AcceptPixiInstall) {
        $answer = Read-Host "Install Pixi now? [Y/n]"
        if ($answer -match '^(n|no)$') {
            throw "Setup was cancelled. SciView cannot start until Pixi is installed."
        }
    }

    Write-Step "Downloading and installing Pixi..."
    Invoke-RestMethod -UseBasicParsing https://pixi.sh/install.ps1 | Invoke-Expression

    $env:Path = "$env:LOCALAPPDATA\pixi\bin;$env:USERPROFILE\.pixi\bin;$env:Path"
    $tool = Find-ManagedPythonTool
    if ($null -eq $tool) {
        throw "Pixi was installed. Close this window and launch SciView again."
    }
    return $tool
}

try {
    Write-Host "SciView Launcher" -ForegroundColor Green
    Write-Host "This window uses Pixi to prepare the Python environment and start SciView."

    $autoPullEnabled = Test-TruthyFlag $env:SCIVIEW_AUTO_PULL
    if (-not $autoPullEnabled -and [string]::IsNullOrWhiteSpace($env:SCIVIEW_AUTO_PULL)) {
        $autoPullEnabled = $true
    }
    if ($NoAutoPull) {
        $autoPullEnabled = $false
    }

    $tool = Find-ManagedPythonTool
    if ($null -eq $tool) {
        $tool = Install-ManagedPythonTool
    }

    Write-Step "Preparing SciView dependencies..."
    & $tool install
    if ($LASTEXITCODE -ne 0) {
        throw "SciView could not prepare its dependencies. Review the error above, then run the launcher again."
    }

    $sourceUpdated = Invoke-SourceAutoUpdate -Enabled $autoPullEnabled -PixiExecutable $tool
    if ($sourceUpdated) {
        Write-Step "Synchronizing updated SciView dependencies..."
        & $tool install
        if ($LASTEXITCODE -ne 0) {
            throw "SciView updated its source but could not update its dependencies. Review the error above, then run the launcher again."
        }
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