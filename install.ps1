param(
    [switch]$SkipAsarPatch,
    [switch]$SkipPip
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$HubRoot = Join-Path $RepoRoot "packages\web-hub"
$ModifierRoot = Join-Path $RepoRoot "packages\desktop-ui-modifier"

Write-Host ""
Write-Host "  ======================================================" -ForegroundColor Cyan
Write-Host "   Antigravity Unleashed - Setup & ASAR Installer" -ForegroundColor Cyan
Write-Host "  ======================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verify prerequisites
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3.11+ was not found on PATH. Please install Python first."
    exit 1
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "Node.js 20+ was not found on PATH. Please install Node.js first."
    exit 1
}

# 2. Install Python dependencies
if (-not $SkipPip) {
    Write-Host "[1/4] Installing Python dependencies..." -ForegroundColor Yellow
    $ReqFile = Join-Path $HubRoot "requirements.txt"
    if (Test-Path $ReqFile) {
        & python -m pip install -r $ReqFile aiohttp --quiet
    }
} else {
    Write-Host "[1/4] Skipping pip install (-SkipPip)..." -ForegroundColor DarkGray
}

# 3. Initialize ~/.gemini/config/antigravity-hub/config.json (if not present)
Write-Host "[2/4] Checking runtime configuration in ~/.gemini/config..." -ForegroundColor Yellow
$GeminiConfigDir = Join-Path $HOME ".gemini\config"
$HubConfigDir = Join-Path $GeminiConfigDir "antigravity-hub"
$HubConfigFile = Join-Path $HubConfigDir "config.json"

New-Item -ItemType Directory -Force -Path $HubConfigDir | Out-Null

if (-not (Test-Path $HubConfigFile)) {
    $RandomHex = -join ((1..24) | ForEach-Object { "{0:x}" -f (Get-Random -Max 16) })
    $DefaultApiKey = "sk-ag-$RandomHex"
    $ConfigPayload = @{
        hub_root   = $HubRoot
        hub_port   = 8000
        api_port   = 8001
        auth_token = $DefaultApiKey
        api_keys   = @{
            $DefaultApiKey = @{
                label      = "local-default"
                created_at = (Get-Date).ToString("o")
            }
        }
    } | ConvertTo-Json -Depth 5
    Set-Content -Path $HubConfigFile -Value $ConfigPayload -Encoding UTF8
    Write-Host "      Created $HubConfigFile" -ForegroundColor Green
    Write-Host "      Local OpenAI API Key: $DefaultApiKey" -ForegroundColor Cyan
} else {
    Write-Host "      Existing config preserved: $HubConfigFile" -ForegroundColor DarkGray
}

$UserPcMd = Join-Path $GeminiConfigDir "USER.pc.md"
$MemoryPcMd = Join-Path $GeminiConfigDir "MEMORY.pc.md"
if (-not (Test-Path $UserPcMd) -and (Test-Path (Join-Path $RepoRoot "USER.example.md"))) {
    Copy-Item (Join-Path $RepoRoot "USER.example.md") $UserPcMd
}
if (-not (Test-Path $MemoryPcMd) -and (Test-Path (Join-Path $RepoRoot "MEMORY.example.md"))) {
    Copy-Item (Join-Path $RepoRoot "MEMORY.example.md") $MemoryPcMd
}

# 4. Build preload.js
Write-Host "[3/4] Compiling Desktop UI Modifier (preload.js)..." -ForegroundColor Yellow
$BuildPreload = Join-Path $ModifierRoot "scripts\build_preload.py"
& python $BuildPreload
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to compile preload.js"
    exit 1
}

# 5. Patch app.asar & restart Antigravity (or just start Hub services)
if (-not $SkipAsarPatch) {
    Write-Host "[4/4] Patching Antigravity app.asar and restarting IDE..." -ForegroundColor Yellow
    $RepackScript = Join-Path $ModifierRoot "scripts\repack_and_restart.py"
    & python $RepackScript
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "ASAR patch returned exit code $LASTEXITCODE. Check ~/.gemini/antigravity/scratch/repack_and_restart.log for details."
        exit $LASTEXITCODE
    }
    Write-Host ""
    Write-Host "  Done! Antigravity Unleashed is active (press Ctrl+Shift+B inside Antigravity)." -ForegroundColor Green
} else {
    Write-Host "[4/4] Starting Web Hub & OpenAI API Bridge (-SkipAsarPatch)..." -ForegroundColor Yellow
    $StartServices = Join-Path $HubRoot "start_services.ps1"
    if (Test-Path $StartServices) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $StartServices
    }
}
