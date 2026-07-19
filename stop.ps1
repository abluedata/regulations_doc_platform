# Stop all services: Elasticsearch (optional) / mineru-api / adapter / API / frontend
# Usage:
#   .\stop.ps1
#   .\stop.ps1 -WithEs          # also stop the Docker ES container
#   .\stop.ps1 -MinerUPort 8001 -AdapterPort 8003 -ApiPort 8002 -FrontendPort 5173

param(
    [switch]$WithEs,
    [int]$MinerUPort = 8001,
    [int]$AdapterPort = 8003,
    [int]$ApiPort = 8002,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root ".data\logs"

function Stop-Port([int]$Port) {
    $pids = @()
    try {
        $pids = @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique
        )
    } catch {}
    if (-not $pids -or $pids.Count -eq 0) {
        Write-Host "  port $Port : no listening process"
        return
    }
    foreach ($procId in $pids) {
        if (-not $procId -or $procId -le 0) { continue }
        try {
            $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
            $name = if ($p) { $p.ProcessName } else { "?" }
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Write-Host "  port $Port : killed PID=$procId ($name)" -ForegroundColor Yellow
        } catch {
            Write-Host "  port $Port : kill PID=$procId failed: $_" -ForegroundColor Red
        }
    }
}

Write-Host "==> Stopping regulations_doc_platform services" -ForegroundColor Cyan
foreach ($p in @($MinerUPort, $AdapterPort, $ApiPort, $FrontendPort)) {
    Stop-Port $p
}

# clean up launcher powershell wrappers spawned by start.ps1
$pidFile = Join-Path $LogDir "services.pids.json"
if (Test-Path $pidFile) {
    try {
        $info = Get-Content $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($svc in @($info.services)) {
            if ($svc.pid) {
                $proc = Get-Process -Id $svc.pid -ErrorAction SilentlyContinue
                if ($proc) {
                    Stop-Process -Id $svc.pid -Force -ErrorAction SilentlyContinue
                    Write-Host "  killed launcher $($svc.name) PID=$($svc.pid)" -ForegroundColor Yellow
                }
            }
        }
    } catch {}
}

# optional: stop Docker ES container (keep data volume)
if ($WithEs) {
    try {
        $null = docker ps 2>&1
        if ($LASTEXITCODE -eq 0) {
            $state = docker inspect -f '{{.State.Status}}' es-local 2>$null
            if ($state) {
                docker stop es-local | Out-Null
                Write-Host "  ES container es-local stopped (data volume esdata preserved)" -ForegroundColor Yellow
            } else {
                Write-Host "  ES container es-local not found, skip"
            }
        } else {
            Write-Host "  Docker not running, skip ES stop"
        }
    } catch {}
}

Write-Host "==> done" -ForegroundColor Green
