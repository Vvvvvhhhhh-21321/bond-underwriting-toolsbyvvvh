$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace ".venv\Scripts\python.exe"
$env:PYTHONNOUSERSITE = "1"

Push-Location $workspace
try {
    $testTemp = Join-Path $workspace ("tmp\build-tests-" + [guid]::NewGuid().ToString("N"))
    & $python -m pytest -q -p no:cacheprovider --basetemp $testTemp
    if ($LASTEXITCODE -ne 0) { throw "自动测试失败" }
    & $python -m mypy
    if ($LASTEXITCODE -ne 0) { throw "类型检查失败" }
    & $python "scripts\build_app.py"
    if ($LASTEXITCODE -ne 0) { throw "应用程序打包失败" }

    $compiler = Join-Path $workspace "tools\inno\ISCC.exe"
    if (-not (Test-Path $compiler)) { throw "未找到 Inno Setup 编译器" }
    & $compiler "installer\disclosure-pdf-scaler.iss"
    if ($LASTEXITCODE -ne 0) { throw "安装程序构建失败" }
}
finally {
    Pop-Location
}
