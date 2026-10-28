$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$worker = Join-Path $root 'pc-worker'
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

Push-Location $worker
try {
    & $python -m worker --once
    if ($LASTEXITCODE -ne 0) { throw 'Worker status check failed.' }
    & $python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Worker tests failed.' }
} finally {
    Pop-Location
}
