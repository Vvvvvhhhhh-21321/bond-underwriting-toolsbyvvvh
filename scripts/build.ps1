$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace ".venv\Scripts\python.exe"
$env:PYTHONNOUSERSITE = "1"

Push-Location $workspace
try {
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
    & $python -m mypy
    if ($LASTEXITCODE -ne 0) { throw "Type checking failed" }
    & $python "scripts\build_app.py"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

    $compiler = Join-Path $workspace "tools\inno\ISCC.exe"
    if (-not (Test-Path $compiler)) { throw "Inno Setup compiler not found" }
    & $compiler "installer\disclosure-pdf-scaler.iss"
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed" }
}
finally {
    Pop-Location
}
