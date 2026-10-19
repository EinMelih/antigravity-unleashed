# start_services.ps1
param(
    [switch]$Restart,
    [switch]$SkipDesktopStart,
    [switch]$SkipLocalApi,
    [ValidateRange(5, 300)][int]$HealthTimeoutSeconds = 30
)

$projectRoot = [System.IO.Path]::GetFullPath(
    (Split-Path -Parent $MyInvocation.MyCommand.Path)
).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
$logsDir = Join-Path $projectRoot 'logs'
$stopScript = Join-Path $projectRoot 'stop_services.ps1'
Set-Location -LiteralPath $projectRoot

function Test-LocalApiBridgeEnabled {
    if ($SkipLocalApi) {
        return $false
    }
    $disableEnv = [string]$env:ANTIGRAVITY_DISABLE_LOCAL_API
    if ($disableEnv.Trim().ToLowerInvariant() -in @('1', 'true', 'yes')) {
        return $false
    }
    $enableEnv = [string]$env:ANTIGRAVITY_ENABLE_LOCAL_API
    if ($enableEnv.Trim().ToLowerInvariant() -in @('1', 'true', 'yes')) {
        return $true
    }
    $configFile = if (-not [string]::IsNullOrWhiteSpace($env:ANTIGRAVITY_HUB_CONFIG)) {
        [string]$env:ANTIGRAVITY_HUB_CONFIG
    } else {
        Join-Path $HOME '.gemini\config\antigravity-hub\config.json'
    }
    if (Test-Path -LiteralPath $configFile -PathType Leaf) {
        try {
            $cfg = Get-Content -LiteralPath $configFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($null -ne $cfg.PSObject.Properties['api_bridge_enabled']) {
                return [bool]$cfg.api_bridge_enabled
            }
        } catch {
            # Ignore invalid JSON and fall back to default enabled
        }
    }
    return $true
}

$apiBridgeEnabled = Test-LocalApiBridgeEnabled

$services = @(
    [pscustomobject]@{ Name = 'Proxy Server'; Script = 'proxy_server.py'; Port = 8000; HealthUrl = 'http://127.0.0.1:8000/health'; StdoutLog = 'proxy.log'; StderrLog = 'proxy.err.log' },
    [pscustomobject]@{ Name = 'API Bridge'; Script = 'api_bridge.py'; Port = 8001; HealthUrl = 'http://127.0.0.1:8001/health'; StdoutLog = 'api_bridge.log'; StderrLog = 'api_bridge.err.log' },
    [pscustomobject]@{ Name = 'Session Manager'; Script = 'session_manager.py'; Port = 8002; HealthUrl = 'http://127.0.0.1:8002/health'; StdoutLog = 'session_manager.log'; StderrLog = 'session_manager.err.log' },
    [pscustomobject]@{ Name = 'Auto-Healer'; Script = 'auto_healer.py'; Port = 8007; HealthUrl = 'http://127.0.0.1:8007/health'; StdoutLog = 'auto_healer.log'; StderrLog = 'auto_healer.err.log' },
    [pscustomobject]@{ Name = 'Watchdog'; Script = 'watchdog_monitor.py'; Port = 8010; HealthUrl = 'http://127.0.0.1:8010/health'; StdoutLog = 'watchdog.log'; StderrLog = 'watchdog.err.log' }
)
if (-not $apiBridgeEnabled) {
    $services = @($services | Where-Object { $_.Name -ne 'API Bridge' })
}

function Resolve-AntigravityDesktopExecutable {
    $candidates = [System.Collections.Generic.List[string]]::new()

    if (-not [string]::IsNullOrWhiteSpace($env:ANTIGRAVITY_DESKTOP_EXE)) {
        $candidates.Add($env:ANTIGRAVITY_DESKTOP_EXE)
    }

    foreach ($appPathKey in @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\Antigravity.exe',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\Antigravity.exe'
    )) {
        try {
            $registeredPath = (Get-Item -LiteralPath $appPathKey -ErrorAction Stop).GetValue('')
            if (-not [string]::IsNullOrWhiteSpace([string]$registeredPath)) {
                $candidates.Add([string]$registeredPath)
            }
        } catch {
            # App Paths registration is optional.
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $candidates.Add(
            (Join-Path $env:LOCALAPPDATA 'Programs\Antigravity\Antigravity.exe')
        )
    }

    $pathCommand = Get-Command Antigravity.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($pathCommand) {
        $candidates.Add($pathCommand.Source)
    }

    foreach ($candidate in $candidates) {
        $expanded = [Environment]::ExpandEnvironmentVariables([string]$candidate).Trim().Trim('"')
        if (Test-Path -LiteralPath $expanded -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($expanded)
        }
    }

    return $null
}

function Start-AntigravityDesktopIfNeeded {
    if ($SkipDesktopStart) {
        Write-Host 'Desktop auto-start skipped by request.' -ForegroundColor DarkGray
        return 'skipped'
    }

    $mutex = [System.Threading.Mutex]::new(
        $false,
        'Local\AntiGravityHubDesktopStartup'
    )
    $ownsMutex = $false
    try {
        try {
            $ownsMutex = $mutex.WaitOne([TimeSpan]::FromSeconds(5))
        } catch [System.Threading.AbandonedMutexException] {
            $ownsMutex = $true
        }

        if (-not $ownsMutex) {
            Write-Host 'Desktop startup is already being checked by another launcher.' -ForegroundColor Yellow
            return 'guarded'
        }

        $runningDesktop = Get-Process -Name 'Antigravity' -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($runningDesktop) {
            Write-Host 'Anti-Gravity Desktop is already running.' -ForegroundColor Green
            return 'running'
        }

        $desktopExecutable = Resolve-AntigravityDesktopExecutable
        if ([string]::IsNullOrWhiteSpace($desktopExecutable)) {
            Write-Host 'Anti-Gravity Desktop was not found; Hub services will start and wait for it.' -ForegroundColor Yellow
            return 'not-found'
        }

        Start-Process `
            -FilePath $desktopExecutable `
            -WorkingDirectory (Split-Path -Parent $desktopExecutable) | Out-Null
        Write-Host 'Anti-Gravity Desktop started.' -ForegroundColor Green
        return 'started'
    } finally {
        if ($ownsMutex) {
            $mutex.ReleaseMutex()
        }
        $mutex.Dispose()
    }
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $pythonCommand) {
    throw 'Python 3 was not found on PATH. Install Python 3.11+ or add it to PATH.'
}

if ($pythonCommand.Name -match '^py(?:\.exe)?$') {
    $pythonExecutable = (& $pythonCommand.Source -3 -c 'import sys; print(sys.executable)' | Select-Object -Last 1)
    if ($LASTEXITCODE -ne 0 -or -not $pythonExecutable) {
        throw 'The Python launcher could not resolve a Python 3 interpreter.'
    }
    $pythonExecutable = [System.IO.Path]::GetFullPath([string]$pythonExecutable)
} else {
    $pythonExecutable = [System.IO.Path]::GetFullPath($pythonCommand.Source)
}

function Start-HubPythonService {
    param(
        [Parameter(Mandatory = $true)]$Service
    )

    $scriptPath = [System.IO.Path]::GetFullPath(
        (Join-Path $projectRoot $Service.Script)
    )
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Service script not found: $scriptPath"
    }

    $arguments = @('-u', ('"{0}"' -f $scriptPath))
    $startedProcess = Start-Process `
        -FilePath $pythonExecutable `
        -ArgumentList $arguments `
        -WorkingDirectory $projectRoot `
        -RedirectStandardOutput (Join-Path $logsDir $Service.StdoutLog) `
        -RedirectStandardError (Join-Path $logsDir $Service.StderrLog) `
        -WindowStyle Hidden `
        -PassThru

    return $startedProcess
}

function Test-HubHealthEndpoint {
    param(
        [Parameter(Mandatory = $true)]$Service
    )

    try {
        $response = Invoke-WebRequest `
            -Uri $Service.HealthUrl `
            -Method Get `
            -UseBasicParsing `
            -TimeoutSec 2 `
            -ErrorAction Stop
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    } catch {
        return $false
    }
}

function Test-AllHubServiceEndpointsResponding {
    foreach ($service in $services) {
        if (-not (Test-HubHealthEndpoint -Service $service)) {
            return $false
        }
    }
    return $true
}

function Get-ApiBridgeReadiness {
    try {
        $payload = Invoke-RestMethod `
            -Uri 'http://127.0.0.1:8001/health' `
            -Method Get `
            -TimeoutSec 2 `
            -ErrorAction Stop
        if ($payload.ready -eq $true -and $payload.cdp.bridge -eq 'injected') {
            return 'ready'
        }
        return 'waiting'
    } catch {
        return 'unavailable'
    }
}

function Write-HubStartupSummary {
    $bridgeReadiness = Get-ApiBridgeReadiness

    Write-Host ''
    Write-Host '================================================' -ForegroundColor Green
    Write-Host '  All five service endpoints are responding.' -ForegroundColor Green
    if ($bridgeReadiness -eq 'ready') {
        Write-Host '  Native injection is ready.' -ForegroundColor Green
    } elseif ($bridgeReadiness -eq 'waiting') {
        Write-Host '  Native injection is still waiting; the background CDP supervisor remains active.' -ForegroundColor Yellow
    } else {
        Write-Host '  Native injection readiness could not be read yet.' -ForegroundColor Yellow
    }
    Write-Host '================================================' -ForegroundColor Green
    Write-Host '  Dashboard UI:    http://127.0.0.1:8000/dashboard/'
    Write-Host '  API Bridge:      http://127.0.0.1:8001'
    Write-Host '  Session Manager: http://127.0.0.1:8002'
    Write-Host '  Auto-Healer:     http://127.0.0.1:8007'
    Write-Host '  Watchdog:        http://127.0.0.1:8010'
    Write-Host ''
    Write-Host "  Logs: $logsDir"
    Write-Host '  Stop: .\stop_services.ps1'
    Write-Host '================================================'
}

function Wait-HubServicesHealthy {
    param(
        [Parameter(Mandatory = $true)][object[]]$StartedProcesses
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    $failedNames = @()
    do {
        $failedNames = @(
            $services | Where-Object {
                -not (Test-HubHealthEndpoint -Service $_)
            } | ForEach-Object { $_.Name }
        )
        if ($failedNames.Count -eq 0) {
            return $true
        }

        foreach ($process in $StartedProcesses) {
            $process.Refresh()
            if ($process.HasExited) {
                Write-Host "A service process exited during startup (PID $($process.Id), exit $($process.ExitCode))." -ForegroundColor Red
                return $false
            }
        }
        Start-Sleep -Milliseconds 300
    } while ([DateTime]::UtcNow -lt $deadline)

    Write-Host "Health timeout. Unhealthy services: $($failedNames -join ', ')" -ForegroundColor Red
    return $false
}

function Stop-StartedHubProcesses {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$StartedProcesses
    )

    foreach ($process in $StartedProcesses) {
        try {
            $process.Refresh()
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id -ErrorAction Stop
            }
        } catch {
            Write-Host "Failed to stop startup PID $($process.Id): $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = $projectRoot

if (-not (Test-Path -LiteralPath $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}
if (-not (Test-Path -LiteralPath $stopScript -PathType Leaf)) {
    throw "Stop script not found: $stopScript"
}

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Anti-Gravity Hub - Startup (PowerShell)" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

& $stopScript -CheckOnly
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Startup aborted because a foreign process owns a required port.' -ForegroundColor Red
    exit 1
}

$null = Start-AntigravityDesktopIfNeeded

if (-not $Restart -and (Test-AllHubServiceEndpointsResponding)) {
    Write-Host 'All five managed service processes are already responding. Nothing to restart.' -ForegroundColor Green
    Write-HubStartupSummary
    exit 0
}

Write-Host 'Stopping an existing managed service set before startup...' -ForegroundColor Yellow
& $stopScript
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Startup aborted because the managed service set could not be stopped safely.' -ForegroundColor Red
    exit 1
}
Write-Host ""

$startedProcesses = @()
try {
    foreach ($service in $services) {
        Write-Host "Starting $($service.Name) (Port $($service.Port))..." -ForegroundColor Yellow
        $process = Start-HubPythonService -Service $service
        $startedProcesses += $process
        Start-Sleep -Milliseconds 250
        $process.Refresh()
        if ($process.HasExited) {
            throw "$($service.Name) exited immediately with code $($process.ExitCode)."
        }
    }

    if (-not (Wait-HubServicesHealthy -StartedProcesses $startedProcesses)) {
        throw 'One or more service health checks failed.'
    }
} catch {
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Stopping only the processes started by this invocation...' -ForegroundColor Yellow
    Stop-StartedHubProcesses -StartedProcesses $startedProcesses
    exit 1
}

Write-HubStartupSummary
exit 0
