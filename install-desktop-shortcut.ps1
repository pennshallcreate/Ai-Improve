# Creates an "AI Improve Agent" application shortcut on your Windows Desktop.
# It points at run.bat in this folder, so double-clicking the desktop icon
# installs dependencies (first run), launches the app, and opens your browser.
$ErrorActionPreference = 'Stop'

$root    = $PSScriptRoot
$target  = Join-Path $root 'run.bat'
$desktop = [Environment]::GetFolderPath('Desktop')
$link    = Join-Path $desktop 'AI Improve Agent.lnk'

if (-not (Test-Path $target)) {
    Write-Host "Could not find run.bat next to this script. Run it from the Ai-Improve folder." -ForegroundColor Red
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath       = $target
$sc.WorkingDirectory = $root
$sc.IconLocation     = "$env:SystemRoot\System32\shell32.dll,13"
$sc.Description       = 'Self-Improving Local AI Agent'
$sc.Save()

Write-Host ""
Write-Host "Done! 'AI Improve Agent' is now on your Desktop." -ForegroundColor Green
Write-Host "Double-click it any time to open the app in your browser."
