# Start / check Elasticsearch container (Docker Desktop must be running first)
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\start_es.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start_es.ps1 -Restart
#   powershell -ExecutionPolicy Bypass -File scripts\start_es.ps1 -ImageTag 8.19.0 -Password es123456

param(
    [string]$ContainerName = "es-local",
    [string]$ImageTag = "8.19.0",
    [int]$Port = 9200,
    [switch]$Restart,
    [switch]$EnableSecurity   # 默认关闭 security，开发场景走 HTTP
)

$ErrorActionPreference = "Stop"

function Test-Docker {
    try {
        $null = docker ps 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Test-EsReady {
    param([int]$TimeoutSec = 2)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port" -UseBasicParsing -TimeoutSec $TimeoutSec -Proxy $null
        return $r.StatusCode -ge 200 -and $r.StatusCode -lt 400
    } catch {
        return $false
    }
}

function Get-ContainerState {
    param([string]$Name)
    try {
        $state = docker inspect -f '{{.State.Status}}' $Name 2>$null
        return [string]$state
    } catch {
        return ""
    }
}

Write-Host "==> Elasticsearch startup check" -ForegroundColor Cyan

# 1. Docker running?
if (-not (Test-Docker)) {
    Write-Host "  XX  Docker Desktop not running. Please start Docker Desktop first." -ForegroundColor Red
    Write-Host "      Search 'Docker Desktop' in Start Menu, wait for icon to stabilize, then retry." -ForegroundColor Yellow
    exit 1
}
Write-Host "  OK  Docker is running" -ForegroundColor Green

# 2. Port already answering -> assume ES is up
if (Test-EsReady) {
    if ($Restart) {
        Write-Host "  ..  -Restart specified, stopping existing ES container" -ForegroundColor Yellow
        docker stop $ContainerName 2>$null | Out-Null
        Start-Sleep -Seconds 2
    } else {
        Write-Host "  OK  ES already running on :$Port" -ForegroundColor Green
        exit 0
    }
}

# 3. Container exists (stopped)?
$state = Get-ContainerState -Name $ContainerName
if ($state -eq "exited") {
    Write-Host "  ..  Container $ContainerName exists but stopped, starting..." -ForegroundColor Yellow
    docker start $ContainerName | Out-Null
} elseif ($state -eq "running") {
    Write-Host "  ..  Container running but port not responding, waiting..." -ForegroundColor Yellow
} elseif (-not $state) {
    Write-Host "  ..  Container does not exist, creating (image elasticsearch:$ImageTag)..." -ForegroundColor Yellow
    $envFlags = @("-e", "discovery.type=single-node")
    if ($EnableSecurity) {
        $envFlags += @("-e", "xpack.security.enabled=true", "-e", "ELASTIC_PASSWORD=es123456")
    } else {
        $envFlags += @("-e", "xpack.security.enabled=false")
    }
    & docker run -d `
        --name $ContainerName `
        -p "${Port}:9200" -p "9300:9300" `
        @envFlags `
        -v esdata:/usr/share/elasticsearch/data `
        --restart unless-stopped `
        "docker.elastic.co/elasticsearch/elasticsearch:$ImageTag" | Out-Null
} else {
    Write-Host "  !!  Container $ContainerName in abnormal state: $state" -ForegroundColor Yellow
    docker restart $ContainerName | Out-Null
}

# 4. Wait for ES ready
Write-Host "  ..  Waiting for ES health..." -ForegroundColor Yellow
for ($i = 1; $i -le 60; $i++) {
    if (Test-EsReady) {
        $authInfo = if ($EnableSecurity) { " (user=elastic, password=es123456)" } else { " (security disabled, no auth)" }
        Write-Host "  OK  ES ready on :$Port$authInfo" -ForegroundColor Green
        exit 0
    }
    Start-Sleep -Seconds 2
    Write-Host "      ... ($i/60)"
}

Write-Host "  XX  ES not ready within 120s" -ForegroundColor Red
Write-Host "      Check logs: docker logs $ContainerName" -ForegroundColor Yellow
exit 1
