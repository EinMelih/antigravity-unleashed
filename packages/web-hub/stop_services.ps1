# stop_services.ps1
param(
    [switch]$CheckOnly
)

$projectRoot = [System.IO.Path]::GetFullPath(
    (Split-Path -Parent $MyInvocation.MyCommand.Path)
).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
$serviceScripts = @(
    'proxy_server.py',
    'api_bridge.py',
    'session_manager.py',
    'auto_healer.py',
    'watchdog_monitor.py'
)
$servicePorts = @(8000, 8001, 8002, 8007, 8010)
$serviceScriptPaths = @(
    $serviceScripts | ForEach-Object {
        [System.IO.Path]::GetFullPath((Join-Path $projectRoot $_))
    }
)

function Test-IsOwnedHubProcess {
    param(
        [Parameter(Mandatory = $true)]$Process
    )

    if ($Process.Name -notmatch '^python(?:w)?\.exe$') {
        return $false
    }

    $commandLine = [string]$Process.CommandLine
    if (-not $commandLine) {
        return $false
    }

    foreach ($scriptPath in $serviceScriptPaths) {
        $escapedPath = [regex]::Escape($scriptPath)
        $argumentPattern = '(?i)(?:^|\s)"?' + $escapedPath + '"?(?:\s|$)'
        if ([regex]::IsMatch($commandLine, $argumentPattern)) {
            return $true
        }
    }

    return $false
}

function Get-OwnedHubProcesses {
    return @(
        Get-CimInstance Win32_Process `
            -Filter "Name = 'python.exe' or Name = 'pythonw.exe'" `
            -ErrorAction SilentlyContinue |
            Where-Object { Test-IsOwnedHubProcess -Process $_ }
    )
}

function Get-ForeignHubPortListeners {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$OwnedProcesses
    )

    $ownedIds = @{}
    foreach ($ownedProcess in $OwnedProcesses) {
        $ownedIds[[int]$ownedProcess.ProcessId] = $true
    }

    $foreign = @()
    foreach ($port in $servicePorts) {
        $listeners = @(
            Get-NetTCPConnection -LocalPort $port -State Listen `
                -ErrorAction SilentlyContinue
        )
        foreach ($listener in $listeners) {
            $processId = [int]$listener.OwningProcess
            if ($ownedIds.ContainsKey($processId)) {
                continue
            }

            $processInfo = Get-CimInstance Win32_Process `
                -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
            $foreign += [pscustomobject]@{
                Port = $port
                ProcessId = $processId
                Name = if ($processInfo) { [string]$processInfo.Name } else { 'unknown' }
                CommandLine = if ($processInfo) { [string]$processInfo.CommandLine } else { '' }
            }
        }
    }

    return @($foreign | Sort-Object Port, ProcessId -Unique)
}

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Anti-Gravity Hub - Shutdown (PowerShell)" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

$ownedProcesses = @(Get-OwnedHubProcesses)
$foreignListeners = @(Get-ForeignHubPortListeners -OwnedProcesses $ownedProcesses)

if ($foreignListeners.Count -gt 0) {
    Write-Host "Refusing to stop services because a foreign process owns a Hub port:" -ForegroundColor Red
    foreach ($listener in $foreignListeners) {
        Write-Host (
            "  Port {0}: PID {1} ({2})" -f `
                $listener.Port, $listener.ProcessId, $listener.Name
        ) -ForegroundColor Red
        if ($listener.CommandLine) {
            Write-Host "    $($listener.CommandLine)" -ForegroundColor DarkGray
        }
    }
    Write-Host "No foreign process was terminated." -ForegroundColor Yellow
    exit 1
}

if ($CheckOnly) {
    exit 0
}

if ($ownedProcesses.Count -eq 0) {
    Write-Host "No managed Anti-Gravity services from this project are running." -ForegroundColor Green
    exit 0
}

Write-Host "Stopping $($ownedProcesses.Count) managed service process(es)..." -ForegroundColor Yellow
$stopFailed = $false
foreach ($processInfo in $ownedProcesses) {
    try {
        Write-Host (
            "  Stopping PID {0}: {1}" -f `
                $processInfo.ProcessId, $processInfo.CommandLine
        ) -ForegroundColor DarkGray
        Stop-Process -Id ([int]$processInfo.ProcessId) -ErrorAction Stop
    } catch {
        $stopFailed = $true
        Write-Host (
            "  Failed to stop PID {0}: {1}" -f `
                $processInfo.ProcessId, $_.Exception.Message
        ) -ForegroundColor Red
    }
}

$deadline = [DateTime]::UtcNow.AddSeconds(5)
do {
    $remaining = @(
        $ownedProcesses | Where-Object {
            Get-Process -Id ([int]$_.ProcessId) -ErrorAction SilentlyContinue
        }
    )
    if ($remaining.Count -eq 0) {
        break
    }
    Start-Sleep -Milliseconds 200
} while ([DateTime]::UtcNow -lt $deadline)

if ($remaining.Count -gt 0) {
    $stopFailed = $true
    foreach ($processInfo in $remaining) {
        Write-Host "  PID $($processInfo.ProcessId) is still running." -ForegroundColor Red
    }
}

$remainingListeners = @(Get-ForeignHubPortListeners -OwnedProcesses @())
if ($remainingListeners.Count -gt 0) {
    $stopFailed = $true
    Write-Host "A process now occupies a Hub port; it was not terminated:" -ForegroundColor Red
    foreach ($listener in $remainingListeners) {
        Write-Host (
            "  Port {0}: PID {1} ({2})" -f `
                $listener.Port, $listener.ProcessId, $listener.Name
        ) -ForegroundColor Red
    }
}

if ($stopFailed) {
    exit 1
}

Write-Host "All managed Anti-Gravity services stopped successfully." -ForegroundColor Green
Write-Host "================================================"
exit 0
