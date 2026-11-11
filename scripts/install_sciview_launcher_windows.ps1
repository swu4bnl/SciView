# Manage the SciView shortcuts in the Start menu and on the Desktop.
#
#   install_sciview_launcher_windows.ps1                ask about each shortcut, remember the answers, apply them
#   install_sciview_launcher_windows.ps1 -FromLauncher  ask only about shortcuts with no saved answer
#   install_sciview_launcher_windows.ps1 -Add           remember "yes" for both shortcuts and add them
#   install_sciview_launcher_windows.ps1 -Remove        remember "no" for both shortcuts and remove them
#
# This script is best effort. It never touches shortcuts it did not create, it
# rewrites its own shortcuts only when they are missing or point elsewhere, and
# the launcher treats a failure as a warning rather than a reason to stop.
param(
    [switch]$FromLauncher,
    [switch]$Add,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LauncherName = "Launch-SciView-win64.cmd"
$LauncherPath = Join-Path $ProjectRoot $LauncherName
$IconPath = Join-Path $ProjectRoot "src\sciview\interfaces\theme\assets\sciview.ico"
$IconLocation = "$IconPath,0"
$Self = "scripts\install_sciview_launcher_windows.ps1"

# Same per-user data root the application uses for its session cache.
$PreferenceFile = Join-Path $env:LOCALAPPDATA "sciview\launcher-shortcuts.txt"

$Targets = @(
    [pscustomobject]@{
        Key         = "start_menu"
        Path        = (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\SciView.lnk")
        Description = "Start menu"
        Question    = "Add SciView to the Start menu? [Y/n]"
        Default     = "y"
    },
    [pscustomobject]@{
        Key         = "desktop"
        Path        = (Join-Path ([Environment]::GetFolderPath("Desktop")) "SciView.lnk")
        Description = "Desktop"
        Question    = "Add a SciView shortcut to the Desktop? [y/N]"
        Default     = "n"
    }
)

function Read-PyprojectValue {
    param([string]$Key)
    $match = Select-String -LiteralPath (Join-Path $ProjectRoot "pyproject.toml") -Pattern "^$Key = `"(.*)`"$" |
        Select-Object -First 1
    if (-not $match) {
        throw "pyproject.toml does not define '$Key'."
    }
    return $match.Matches[0].Groups[1].Value
}

$AppUserModelId = Read-PyprojectValue "app_id"

function Read-Preferences {
    $preferences = @{}
    if (Test-Path -LiteralPath $PreferenceFile) {
        foreach ($line in Get-Content -LiteralPath $PreferenceFile) {
            if ($line -match '^([a-z_]+)=(yes|no)$') {
                $preferences[$Matches[1]] = $Matches[2]
            }
        }
    }
    return $preferences
}

function Save-Preferences {
    param([hashtable]$Preferences)
    New-Item -ItemType Directory -Path (Split-Path -Parent $PreferenceFile) -Force | Out-Null
    $lines = foreach ($key in ($Preferences.Keys | Sort-Object)) { "$key=$($Preferences[$key])" }
    Set-Content -LiteralPath $PreferenceFile -Value $lines
}

function Read-YesNo {
    param([string]$Question, [string]$Default)
    $answer = Read-Host $Question
    if ([string]::IsNullOrWhiteSpace($answer)) {
        $answer = $Default
    }
    return ($answer -match '^(y|yes)$')
}

if (-not ("SciViewShortcutAppId" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential)]
public struct SciViewPropertyKey {
    public Guid FormatId;
    public uint PropertyId;
}

[StructLayout(LayoutKind.Explicit)]
public struct SciViewPropVariant {
    [FieldOffset(0)] public ushort VariantType;
    [FieldOffset(8)] public IntPtr StringValue;
}

[ComImport]
[Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface ISciViewPropertyStore {
    [PreserveSig] int GetCount(out uint count);
    [PreserveSig] int GetAt(uint index, out SciViewPropertyKey key);
    [PreserveSig] int GetValue(ref SciViewPropertyKey key, out SciViewPropVariant value);
    [PreserveSig] int SetValue(ref SciViewPropertyKey key, ref SciViewPropVariant value);
    [PreserveSig] int Commit();
}

public static class SciViewShortcutAppId {
    private static readonly Guid InterfaceId = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
    private static readonly Guid AppUserModelIdFormat = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern int SHGetPropertyStoreFromParsingName(
        string path, IntPtr bindContext, uint flags, ref Guid interfaceId,
        out ISciViewPropertyStore propertyStore);

    [DllImport("ole32.dll")]
    private static extern int PropVariantClear(ref SciViewPropVariant value);

    private static ISciViewPropertyStore Open(string shortcutPath) {
        Guid interfaceId = InterfaceId;
        ISciViewPropertyStore store;
        int result = SHGetPropertyStoreFromParsingName(shortcutPath, IntPtr.Zero, 2, ref interfaceId, out store);
        Marshal.ThrowExceptionForHR(result);
        return store;
    }

    public static void Set(string shortcutPath, string appId) {
        ISciViewPropertyStore store = Open(shortcutPath);
        SciViewPropertyKey key = new SciViewPropertyKey { FormatId = AppUserModelIdFormat, PropertyId = 5 };
        SciViewPropVariant value = new SciViewPropVariant {
            VariantType = 31,
            StringValue = Marshal.StringToCoTaskMemUni(appId)
        };
        try {
            Marshal.ThrowExceptionForHR(store.SetValue(ref key, ref value));
            Marshal.ThrowExceptionForHR(store.Commit());
        }
        finally {
            PropVariantClear(ref value);
            Marshal.ReleaseComObject(store);
        }
    }
}
"@
}

$Shell = New-Object -ComObject WScript.Shell
$ShellApplication = New-Object -ComObject Shell.Application

function Get-ShortcutAppUserModelId {
    param([string]$Path)
    $folder = $ShellApplication.Namespace((Split-Path -Parent $Path))
    if ($null -eq $folder) {
        return ""
    }
    $item = $folder.ParseName((Split-Path -Leaf $Path))
    if ($null -eq $item) {
        return ""
    }
    return [string]$item.ExtendedProperty("System.AppUserModel.ID")
}

function Normalize-ShortcutIconLocation {
    param([string]$IconLocation)
    $parts = $IconLocation -split ",", 2
    $iconPath = [Environment]::ExpandEnvironmentVariables($parts[0].Trim('"'))
    $resourceIndex = if ($parts.Count -gt 1) { $parts[1].Trim() } else { "0" }
    try {
        $iconPath = [IO.Path]::GetFullPath($iconPath)
    }
    catch {
        return $IconLocation.Trim()
    }
    return "$iconPath,$resourceIndex"
}

function Get-ShortcutState {
    # missing: no file; current: ours and up to date; outdated: ours but points
    # at another checkout or icon; foreign: not created by this launcher.
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return "missing"
    }
    $existing = $Shell.CreateShortcut($Path)
    if ([IO.Path]::GetFileName($existing.TargetPath) -ine $LauncherName) {
        return "foreign"
    }
    if ($existing.TargetPath -ine $LauncherPath) {
        if (Test-Path -LiteralPath $existing.TargetPath) {
            if ([IO.Path]::GetFullPath($existing.TargetPath) -ine [IO.Path]::GetFullPath($LauncherPath)) {
                return "foreign"
            }
        }
        return "outdated"
    }
    if ($existing.WorkingDirectory -ieq $ProjectRoot -and
        (Normalize-ShortcutIconLocation $existing.IconLocation) -ieq
            (Normalize-ShortcutIconLocation $IconLocation) -and
        (Get-ShortcutAppUserModelId $Path) -ieq $AppUserModelId) {
        return "current"
    }
    return "outdated"
}

# --- Decide the desired state ---------------------------------------------------

$Preferences = Read-Preferences
$Changed = $false
$Asked = $false
foreach ($Target in $Targets) {
    if ($Remove) {
        $Desired = "no"
    }
    elseif ($Add) {
        $Desired = "yes"
    }
    elseif ($FromLauncher -and $Preferences.ContainsKey($Target.Key)) {
        continue
    }
    else {
        $Desired = if (Read-YesNo $Target.Question $Target.Default) { "yes" } else { "no" }
        $Asked = $true
    }
    if ($Preferences[$Target.Key] -ne $Desired) {
        $Preferences[$Target.Key] = $Desired
        $Changed = $true
    }
}
if ($Changed) {
    Save-Preferences $Preferences
}
if ($Asked) {
    Write-Host "SciView remembers these answers. To change them, run $Self again, or $Self -Add or -Remove."
}

# --- Apply it ---------------------------------------------------------------------

$Pending = @()
foreach ($Target in $Targets) {
    $State = Get-ShortcutState $Target.Path
    switch ($Preferences[$Target.Key]) {
        "yes" {
            switch ($State) {
                "foreign" { Write-Warning "A different SciView shortcut exists at $($Target.Path); leaving it unchanged." }
                "current" { }
                default { $Pending += $Target.Path }
            }
        }
        "no" {
            if ($State -in @("current", "outdated")) {
                Remove-Item -LiteralPath $Target.Path -Force
                Write-Host "Removed $($Target.Path)"
            }
            elseif ($Remove) {
                Write-Host "No SciView shortcut created by this launcher was found in the $($Target.Description)."
            }
        }
    }
}
if ($Pending.Count -eq 0) {
    return
}

if (-not (Test-Path -LiteralPath $IconPath)) {
    throw "SciView icon file was not found: $IconPath"
}
# The shortcut carries the same AppUserModelID that main.py sets on the process,
# so Windows groups SciView windows under this shortcut and allows taskbar pinning.
foreach ($ShortcutPath in $Pending) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $ShortcutPath) -Force | Out-Null
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $LauncherPath
    $Shortcut.WorkingDirectory = $ProjectRoot
    $Shortcut.IconLocation = $IconLocation
    $Shortcut.Description = "SciView X-ray scattering application"
    $Shortcut.Save()
    [SciViewShortcutAppId]::Set($ShortcutPath, $AppUserModelId)
    Write-Host "Installed SciView shortcut: $ShortcutPath"
}
