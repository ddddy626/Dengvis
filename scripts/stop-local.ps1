$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root '.run\pids.json'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output '没有本项目启动的服务记录。'; exit 0 }
$localPids = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
foreach ($processId in @($localPids.server, $localPids.web)) {
    if ($processId -and (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $processId
    }
}
Remove-Item -LiteralPath $pidFile
Write-Output '已停止本项目服务。'
