# Build single-file MsgValidator.exe into .\dist
Set-Location $PSScriptRoot
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
# PyInstaller logs to stderr; in Windows PowerShell 5.1 that must not be treated as an error
cmd /c "python -m PyInstaller --noconfirm --clean --onefile --name MsgValidator --splash assets/splash.png --add-data msgvalidator/data;msgvalidator/data --collect-submodules msgvalidator run.py 2>&1"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host "Hotovo: $PSScriptRoot\dist\MsgValidator.exe"
