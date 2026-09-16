param(
    [string]$Version = '0.3.0',
    [string]$OutputDirectory = 'release'
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$outputRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
$stageRoot = Join-Path $outputRoot "ExamPilot-$Version-windows"
$archivePath = Join-Path $outputRoot "ExamPilot-$Version-windows.zip"

Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.venv\Scripts\python.exe'))) {
    throw 'Packaged Python runtime is missing. Run uv sync first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) {
    throw 'Frontend build is missing. Run npm.cmd run build in frontend first.'
}

if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force }
if (Test-Path -LiteralPath $archivePath) { Remove-Item -LiteralPath $archivePath -Force }
New-Item -ItemType Directory -Path $stageRoot | Out-Null

$directories = @('backend', 'skills', 'frontend\dist', 'samples', 'scripts')
foreach ($directory in $directories) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $directory) -Destination (Join-Path $stageRoot $directory) -Recurse -Force
}

$venvConfig = Get-Content (Join-Path $projectRoot '.venv\pyvenv.cfg')
$pythonHome = ($venvConfig | Where-Object { $_ -match '^home = (.+)$' } | Select-Object -First 1) -replace '^home = ', ''
if (-not (Test-Path -LiteralPath $pythonHome)) { throw "Python runtime not found: $pythonHome" }
$runtimeRoot = Join-Path $stageRoot 'runtime'
New-Item -ItemType Directory -Path $runtimeRoot | Out-Null
Get-ChildItem -LiteralPath $pythonHome -Force | Where-Object { $_.Name -notin @('Lib', 'Scripts', 'Doc', 'include', 'Tools', 'share') } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $runtimeRoot $_.Name) -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $runtimeRoot 'Lib') | Out-Null
Get-ChildItem -LiteralPath (Join-Path $pythonHome 'Lib') -Force | Where-Object { $_.Name -ne 'site-packages' } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path (Join-Path $runtimeRoot 'Lib') $_.Name) -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $projectRoot '.venv\Lib\site-packages') -Destination (Join-Path $runtimeRoot 'Lib\site-packages') -Recurse -Force

$files = @(
    'README.md',
    'ExamPilot-PRD.md',
    'pyproject.toml',
    'uv.lock',
    '.env.example',
    '08  税收的经济效应.pptx'
)
foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination (Join-Path $stageRoot $file) -Force
}
Get-ChildItem -LiteralPath $projectRoot -Filter '*ExamPilot.bat' -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $stageRoot $_.Name) -Force
}

New-Item -ItemType Directory -Path (Join-Path $stageRoot 'data\runtime') -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $stageRoot 'data\.gitkeep') -Force | Out-Null
@"
ExamPilot Windows release

1. Double-click 启动ExamPilot.bat.
2. The browser opens at http://127.0.0.1:8787.
3. Configure your own API key in API settings.
4. Double-click 停止ExamPilot.bat when finished.

This package includes its Python runtime and frontend build. Node.js, npm and uv are not required.
User data is stored in the data folder.
"@ | Set-Content -LiteralPath (Join-Path $stageRoot 'START-HERE.txt') -Encoding UTF8

Compress-Archive -Path (Join-Path $stageRoot '*') -DestinationPath $archivePath -CompressionLevel Optimal
Write-Host "Created: $archivePath" -ForegroundColor Green
Write-Host ('Size: {0:N1} MB' -f ((Get-Item $archivePath).Length / 1MB))