$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
py -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 from python.org, including the Windows Python launcher.' }
& '.\.venv\Scripts\python.exe' -m pip install --require-hashes -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your internet connection.' }
Write-Host 'Setup complete. Run monitor.cmd for fullscreen or start.cmd for a window.'
