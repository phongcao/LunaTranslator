<#
.SYNOPSIS
    Adds a Start Menu shortcut that runs LunaTranslator from this source tree with the repo's .venv.
    Run dev-build.bat first. Nothing is copied: the shortcut always runs the current source.
.PARAMETER Desktop
    Also create a desktop shortcut.
.PARAMETER Uninstall
    Remove the shortcuts instead.
#>
param([switch]$Desktop, [switch]$Uninstall)
$ErrorActionPreference = 'Stop'

$pythonw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$icon = Join-Path $PSScriptRoot '.venv\LunaTranslator.ico'
$shortcuts = @(Join-Path ([Environment]::GetFolderPath('Programs')) 'LunaTranslator.lnk')
if ($Desktop -or $Uninstall) {
    $shortcuts += Join-Path ([Environment]::GetFolderPath('Desktop')) 'LunaTranslator.lnk'
}

if ($Uninstall) {
    foreach ($path in $shortcuts) {
        if (Test-Path $path) { Remove-Item $path; "Removed: $path" }
    }
    return
}

if (-not (Test-Path $pythonw)) {
    throw '.venv not found. Run dev-build.bat first.'
}

& (Join-Path $PSScriptRoot 'src\scripts\make_dev_icon.ps1') -Out $icon

$shell = New-Object -ComObject WScript.Shell
foreach ($path in $shortcuts) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = '-B LunaTranslator\main.py'
    $lnk.WorkingDirectory = Join-Path $PSScriptRoot 'src'
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = 'LunaTranslator (from source)'
    $lnk.Save()
    "Shortcut: $path"
}
