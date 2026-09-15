param([int]$Port = 8787)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Please install uv: https://docs.astral.sh/uv/getting-started/installation/' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Please install Node.js 20.19+ or 22.12+.' }
uv sync --frozen
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
$env:EXAMPILOT_PORT = "$Port"
Write-Host "ExamPilot: http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host 'Keep this terminal running. Ctrl+C stops the app and its MCP child process.'
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -m backend.run

