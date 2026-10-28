$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$web = Join-Path $root 'web'
if (-not (Test-Path -LiteralPath $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
& $python -c 'import fastapi, uvicorn, httpx, dotenv'
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖未安装；请先执行 README 中的安装步骤。' }
if (-not (Test-Path -LiteralPath (Join-Path $web 'node_modules'))) { throw '缺少 web/node_modules；请先执行 npm install。' }
$run = Join-Path $root '.run'
New-Item -ItemType Directory -Path $run -Force | Out-Null
$server = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory (Join-Path $root 'server') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $run 'server.out.log') -RedirectStandardError (Join-Path $run 'server.err.log') -PassThru
$frontend = Start-Process -FilePath $npm -ArgumentList @('run','dev') -WorkingDirectory $web -WindowStyle Hidden -RedirectStandardOutput (Join-Path $run 'web.out.log') -RedirectStandardError (Join-Path $run 'web.err.log') -PassThru
@{ server = $server.Id; web = $frontend.Id } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'pids.json')
Write-Output '后端：http://127.0.0.1:8000/health'
Write-Output 'Web：http://127.0.0.1:5173/'
Write-Output '停止服务：.\scripts\stop-local.ps1'
