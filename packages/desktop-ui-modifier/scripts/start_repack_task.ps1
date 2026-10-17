[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$GuardOnly,
    [switch]$RegisterOnly,
    [switch]$WaitForRepack,
    [string]$PythonPath = $env:ANTIGRAVITY_PYTHON,
    [string]$PythonwPath = $env:ANTIGRAVITY_PYTHONW,
    [string]$TaskName = 'Antigravity-Repack',
    [string]$GuardTaskName = 'Antigravity-Patch-Guard'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$resolvedPython = $null
$feedbackScriptPath = Join-Path $PSScriptRoot 'injector_status.py'
$repackStartedAt = 0.0

trap {
    $failureMessage = $_.Exception.Message
    [Console]::Error.WriteLine($failureMessage)
    if (-not $WhatIfPreference) {
        try {
            if ($resolvedPython -and (Test-Path -LiteralPath $feedbackScriptPath -PathType Leaf)) {
                & $resolvedPython $feedbackScriptPath --launcher-error $failureMessage --started-at $repackStartedAt
                if ($LASTEXITCODE -ne 0) { throw 'Popup helper failed.' }
            } else {
                Add-Type -AssemblyName System.Windows.Forms
                [System.Windows.Forms.MessageBox]::Show($failureMessage, 'Anti-Gravity Injector - Fehler', 'OK', 'Warning') | Out-Null
            }
        } catch {
            [Console]::Error.WriteLine("Fehler-Popup konnte nicht gestartet werden: $($_.Exception.Message)")
        }
    }
    exit 1
}

function Resolve-ApplicationPath {
    param(
        [string]$Preferred,
        [string[]]$FallbackNames,
        [string]$Description
    )

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($Preferred)) {
        $candidates += $Preferred
    }
    $candidates += $FallbackNames

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        if ([IO.Path]::IsPathRooted($candidate)) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                return (Resolve-Path -LiteralPath $candidate).Path
            }
            continue
        }
        $command = Get-Command -Name $candidate -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $command) {
            return $command.Source
        }
    }

    throw "$Description not found. Pass an explicit path or configure the documented environment variable."
}

$scriptDirectory = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$skillRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDirectory '..')).Path
$repackScriptPath = Join-Path $scriptDirectory 'repack_and_restart.py'
$guardScriptPath = Join-Path $scriptDirectory 'auto_repack_guard.py'
$supportedVersionPath = Join-Path $skillRoot 'SUPPORTED_UPSTREAM_VERSION'

foreach ($requiredFile in @($repackScriptPath, $guardScriptPath, $supportedVersionPath, $feedbackScriptPath, (Join-Path $scriptDirectory 'notification_popup.py'))) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required modifier file not found: $requiredFile"
    }
}

$supportedVersion = (Get-Content -LiteralPath $supportedVersionPath -Raw).Trim().TrimStart('v')
if ([string]::IsNullOrWhiteSpace($supportedVersion)) {
    throw "SUPPORTED_UPSTREAM_VERSION is empty: $supportedVersionPath"
}

$resolvedPython = Resolve-ApplicationPath `
    -Preferred $PythonPath `
    -FallbackNames @('python.exe', 'python3.exe', 'py.exe') `
    -Description 'Python interpreter'

$pythonDirectory = Split-Path -Parent $resolvedPython
$pythonLeaf = Split-Path -Leaf $resolvedPython
$windowlessSibling = if ($pythonLeaf -ieq 'py.exe') { 'pyw.exe' } else { 'pythonw.exe' }
$resolvedPythonw = Resolve-ApplicationPath `
    -Preferred $PythonwPath `
    -FallbackNames @((Join-Path $pythonDirectory $windowlessSibling), 'pythonw.exe', 'pyw.exe') `
    -Description 'Windowless Python interpreter'

& $resolvedPython -c 'import aiohttp' | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Python dependency aiohttp is missing. Install the documented dependencies before registering tasks.'
}

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$quotedGuardScript = '"' + $guardScriptPath + '"'
$quotedRepackScript = '"' + $repackScriptPath + '"'

$guardAction = New-ScheduledTaskAction `
    -Execute $resolvedPythonw `
    -Argument $quotedGuardScript `
    -WorkingDirectory $skillRoot
$guardTrigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$guardPrincipal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited
$guardSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

if ($PSCmdlet.ShouldProcess($GuardTaskName, "Register v$supportedVersion compatibility guard")) {
    Register-ScheduledTask `
        -TaskName $GuardTaskName `
        -Action $guardAction `
        -Trigger $guardTrigger `
        -Principal $guardPrincipal `
        -Settings $guardSettings `
        -Description "Re-applies the verified Anti-Gravity v$supportedVersion modifier after compatible changes." `
        -Force | Out-Null
}

if ($GuardOnly) {
    if (-not $RegisterOnly -and $PSCmdlet.ShouldProcess($GuardTaskName, 'Start compatibility guard')) {
        Start-ScheduledTask -TaskName $GuardTaskName
    }
    return
}

$repackAction = New-ScheduledTaskAction `
    -Execute $resolvedPythonw `
    -Argument $quotedRepackScript `
    -WorkingDirectory $skillRoot
$repackPrincipal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited
$repackSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

if ($PSCmdlet.ShouldProcess($TaskName, "Register v$supportedVersion transactional repack")) {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $repackAction `
        -Principal $repackPrincipal `
        -Settings $repackSettings `
        -Description "Applies and verifies the Anti-Gravity v$supportedVersion desktop modifier." `
        -Force | Out-Null
}

if (-not $RegisterOnly -and $PSCmdlet.ShouldProcess($TaskName, 'Start transactional repack')) {
    $previousRun = (Get-ScheduledTaskInfo -TaskName $TaskName).LastRunTime;
    $repackStartedAt = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
    Start-ScheduledTask -TaskName $TaskName
    if ($WaitForRepack) {
        Write-Host 'Injector gestartet. Warte auf den Abschluss ...'
        $deadline = (Get-Date).AddMinutes(10)
        $statusPath = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.gemini\antigravity\scratch\repack_status.json'
        $lastPhase = ''
        $phaseLabels = @{
            preflight = 'Pruefe die installierte Version'
            build = 'Baue die Erweiterung'
            validate = 'Pruefe Originaldateien und JavaScript'
            save_state = 'Sichere den App-Zustand'
            stop = 'Beende die App fuer den Repack'
            pack = 'Packe und pruefe das neue Archiv'
            install = 'Erstelle Backups und installiere'
            start = 'Starte Anti-Gravity'
            verify = 'Pruefe die laufende Injektion'
            guard_state = 'Speichere den verifizierten Guard-Status'
            rollback = 'Stelle die vorherige Installation wieder her'
            complete = 'Injektion erfolgreich verifiziert'
        }
        do {
            Start-Sleep -Seconds 1
            $task = Get-ScheduledTask -TaskName $TaskName
            $info = Get-ScheduledTaskInfo -TaskName $TaskName
            $status = $null
            if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
                $status = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($status.updated_at -ge $repackStartedAt -and $status.phase -ne $lastPhase) {
                    $lastPhase = $status.phase
                    $label = if ($phaseLabels.ContainsKey($lastPhase)) { $phaseLabels[$lastPhase] } else { $lastPhase }
                    Write-Host $label
                }
            }
            if ($info.LastRunTime -gt $previousRun -and $task.State -notin @('Running', 'Queued')) {
                if ($info.LastTaskResult -ne 0) {
                    $errorPath = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.gemini\antigravity\scratch\repack_error.txt'
                    $details = if (Test-Path -LiteralPath $errorPath -PathType Leaf) {
                        Get-Content -LiteralPath $errorPath -Raw
                    } else {
                        'Details: ~/.gemini/antigravity/scratch/repack_and_restart.log'
                    }
                    throw "Injector fehlgeschlagen (Exit $($info.LastTaskResult)). $details"
                }
                if ($null -eq $status -or $status.state -ne 'success' -or $status.updated_at -lt $repackStartedAt) {
                    throw 'Task beendet, aber eine erfolgreich verifizierte Injektion wurde nicht bestaetigt. Bitte das Repack-Log pruefen.'
                }
                Write-Host 'Injector erfolgreich abgeschlossen und verifiziert.'
                & $resolvedPython $feedbackScriptPath --completion --started-at $repackStartedAt
                if ($LASTEXITCODE -ne 0) { throw 'Die Injektion ist verifiziert, aber das Erfolgs-Popup konnte nicht gestartet werden.' }
                if ($PSCmdlet.ShouldProcess($GuardTaskName, 'Start compatibility guard after verified repack')) {
                    Start-ScheduledTask -TaskName $GuardTaskName
                }
                return
            }
        } while ((Get-Date) -lt $deadline)
        throw 'Injector hat nach 10 Minuten keinen Abschluss gemeldet. Bitte das Repack-Log pruefen.'
    }
    # Fire-and-forget mode: make sure the guard is not left stopped. It skips work
    # while repack_and_restart.py runs and afterwards adopts the verified signature.
    $guardTask = Get-ScheduledTask -TaskName $GuardTaskName -ErrorAction SilentlyContinue
    if ($null -ne $guardTask -and $guardTask.State -ne 'Running' -and
        $PSCmdlet.ShouldProcess($GuardTaskName, 'Start compatibility guard alongside repack')) {
        Start-ScheduledTask -TaskName $GuardTaskName
    }
}
