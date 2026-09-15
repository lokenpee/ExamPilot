param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Start', 'Stop')]
    [string]$Action,
    [ValidateRange(1024, 65535)]
    [int]$Port = 8787,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runtimeDirectory = Join-Path $projectRoot 'data\runtime'
$statePath = Join-Path $runtimeDirectory 'launcher.json'
$baseUrl = "http://127.0.0.1:$Port"
Set-Location -LiteralPath $projectRoot

function Get-ProjectRoots {
    # Match this workspace's venv launcher AND the exact application module.
    # Never kill all python.exe processes or adopt another application's port.
    return @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object {
            $_.ExecutablePath -ieq $pythonPath -and
            $_.CommandLine -match '(?:^|\s)-m\s+backend\.run\s*$'
        })
}

function Get-ProcessTree([object[]]$Roots) {
    $snapshot = @(Get-CimInstance Win32_Process)
    $result = [Collections.Generic.List[object]]::new()
    $known = [Collections.Generic.HashSet[uint32]]::new()
    foreach ($root in $Roots) {
        if ($known.Add([uint32]$root.ProcessId)) { $result.Add($root) }
    }
    do {
        $added = $false
        foreach ($process in $snapshot) {
            if ($known.Contains([uint32]$process.ParentProcessId) -and $known.Add([uint32]$process.ProcessId)) {
                $result.Add($process)
                $added = $true
            }
        }
    } while ($added)
    return $result.ToArray()
}

function Test-OwnedListener([object[]]$Tree) {
    $ownedIds = @($Tree | ForEach-Object { [uint32]$_.ProcessId })
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    return @($listeners | Where-Object { $_.OwningProcess -in $ownedIds }).Count -gt 0
}

function Test-Ready {
    try {
        $health = Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 2
        return $health.ok -and $health.mcp.connected -and
            'search' -in $health.mcp.tools -and 'get_chunk_context' -in $health.mcp.tools
    } catch { return $false }
}

function Save-LauncherState([object]$RootProcess) {
    New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
    @{
        projectRoot = $projectRoot
        launcherPid = $RootProcess.ProcessId
        createdAt = $RootProcess.CreationDate.ToString('o')
        port = $Port
        url = $baseUrl
    } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Stop-VerifiedTree([object[]]$Tree) {
    # Descendants first; recheck birth time and command line to protect against PID reuse.
    for ($index = $Tree.Count - 1; $index -ge 0; $index--) {
        $expected = $Tree[$index]
        $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($expected.ProcessId)"
        if ($current -and $current.CreationDate -eq $expected.CreationDate -and
            $current.CommandLine -ceq $expected.CommandLine) {
            Stop-Process -Id $current.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

$actionMutex = $null
$hasMutex = $false
try {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $rootHash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant()))).Replace('-', '') }
    finally { $sha.Dispose() }
    $actionMutex = [Threading.Mutex]::new($false, "Local\ExamPilot-$rootHash")
    try { $hasMutex = $actionMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $hasMutex = $true }
    if (-not $hasMutex) {
        Write-Host 'Another ExamPilot start/stop action is already in progress. Please wait.'
        exit 0
    }
    $roots = @(Get-ProjectRoots)
    if ($Action -eq 'Stop') {
        if (-not $roots.Count) {
            Write-Host 'ExamPilot is already stopped.' -ForegroundColor Green
            exit 0
        }
        # A saved port is advisory only: processes are always verified by workspace.
        if (Test-Path -LiteralPath $statePath) {
            try {
                $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
                if ($saved.projectRoot -eq $projectRoot -and $saved.port -ge 1024 -and $saved.port -le 65535) {
                    $Port = [int]$saved.port
                    $baseUrl = "http://127.0.0.1:$Port"
                }
            } catch { }
        }
        $tree = @(Get-ProcessTree $roots)
        if (Test-OwnedListener $tree) {
            # Ask the application to cancel jobs and persist their checkpoints before shutdown.
            try {
                $projects = Invoke-RestMethod -Uri "$baseUrl/api/projects" -TimeoutSec 3
                foreach ($project in $projects) {
                    $state = Invoke-RestMethod -Uri "$baseUrl/api/projects/$($project.id)" -TimeoutSec 3
                    foreach ($job in $state.jobs) {
                        if ($job.status -in @('running', 'queued')) {
                            Invoke-RestMethod -Method Post -Uri "$baseUrl/api/jobs/$($job.id)/cancel" -TimeoutSec 10 | Out-Null
                        }
                    }
                }
            } catch {
                Write-Host 'The server did not finish cancelling jobs. Saved progress can be recovered on restart.' -ForegroundColor Yellow
            }
        }
        Stop-VerifiedTree $tree
        if (@(Get-ProjectRoots).Count) { throw 'A verified ExamPilot process is still running. Please retry Stop.' }
        # Clear only our own fixed state file; leave documents, database and logs intact.
        if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath }
        Write-Host 'ExamPilot and its MCP process have stopped. Your data is preserved.' -ForegroundColor Green
        exit 0
    }

    if ($roots.Count) {
        $tree = @(Get-ProcessTree $roots)
        if ((Test-OwnedListener $tree) -and (Test-Ready)) {
            Save-LauncherState $roots[0]
            Write-Host "ExamPilot is already running: $baseUrl" -ForegroundColor Green
            if (-not $NoBrowser) { Start-Process $baseUrl }
            exit 0
        }
        throw 'This project is already running or starting, but is not ready on this port. Use Stop, then Start.'
    }

    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $Port is occupied by another process. It will not be stopped."
    }
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is missing. Install it first: https://docs.astral.sh/uv/' }
        uv sync --frozen
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) {
        if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Node.js / npm is required to build the web interface.' }
        Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
        try {
            npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
            npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
        } finally { Pop-Location }
    }
    New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $outLog = Join-Path $runtimeDirectory "server-$stamp.log"
    $errLog = Join-Path $runtimeDirectory "server-$stamp.error.log"
    $env:EXAMPILOT_PORT = "$Port"
    $env:PYTHONIOENCODING = 'utf-8'
    $launched = Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'backend.run') `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    Write-Host "Starting ExamPilot: $baseUrl"
    $deadline = (Get-Date).AddSeconds(45)
    do {
        Start-Sleep -Milliseconds 500
        $roots = @(Get-ProjectRoots | Where-Object { $_.ProcessId -eq $launched.Id })
        if (-not $roots.Count) { throw "The server exited. Check: $errLog" }
        if (Test-Ready) {
            if (-not (Test-OwnedListener @(Get-ProcessTree $roots))) { throw 'The listener is not owned by this project.' }
            Save-LauncherState $roots[0]
            Write-Host "ExamPilot is ready: $baseUrl" -ForegroundColor Green
            Write-Host "Logs: $runtimeDirectory"
            if (-not $NoBrowser) { Start-Process $baseUrl }
            exit 0
        }
    } while ((Get-Date) -lt $deadline)
    # A failed startup must not leave an invisible server consuming the port.
    $roots = @(Get-ProjectRoots | Where-Object { $_.ProcessId -eq $launched.Id })
    if ($roots.Count) { Stop-VerifiedTree @(Get-ProcessTree $roots) }
    throw "Startup timed out. Check: $errLog"
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    if ($hasMutex) { $actionMutex.ReleaseMutex() }
    if ($actionMutex) { $actionMutex.Dispose() }
}
