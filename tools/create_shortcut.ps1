# Create a per-user desktop shortcut; no administrator rights are needed.
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$pythonWindowed = Join-Path $projectDirectory '.venv\Scripts\pythonw.exe'
$launcherPath = Join-Path $projectDirectory 'launch.py'
if (-not (Test-Path -LiteralPath $pythonWindowed -PathType Leaf)) {
    throw 'Run setup.ps1 first.'
}
$desktopDirectory = [Environment]::GetFolderPath('Desktop')
if (-not $desktopDirectory) { throw 'Windows desktop folder is unavailable.' }
$shortcutPath = Join-Path $desktopDirectory 'GoPro LitHero Live Monitor.lnk'
$shell = New-Object -ComObject WScript.Shell
try {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    if ((Test-Path -LiteralPath $shortcutPath) -and $shortcut.TargetPath -and $shortcut.TargetPath -ne $pythonWindowed) {
        throw 'A shortcut with this name points to another application; it was not overwritten.'
    }
    $shortcut.TargetPath = $pythonWindowed
    $shortcut.Arguments = '-I -S "' + $launcherPath + '" --connect --fullscreen'
    $shortcut.WorkingDirectory = $projectDirectory
    $shortcut.Description = 'GoPro LIT HERO live framing monitor'
    $shortcut.IconLocation = $pythonWindowed + ',0'
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    Write-Host 'Desktop shortcut created.'
}
finally {
    if ($shortcut) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shortcut) }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
}
