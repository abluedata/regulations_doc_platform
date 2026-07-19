# One-click start: ES(Docker) -> mineru-api :8001 + adapter :8003 + API :8002 + frontend :5173
# Uses project-root venv (Python 3.12 + mineru[pipeline])
#
# Usage:
#   .\start.ps1
#   .\start.ps1 -SkipFrontend
#   .\start.ps1 -Restart
#   .\start.ps1 -OpenBrowser

param(
    [switch]$SkipFrontend,
    [switch]$Restart,
    [switch]$OpenBrowser,
    [int]$MinerUPort = 8001,
    [int]$AdapterPort = 8003,
    [int]$ApiPort = 8002,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Py = Join-Path $Root "venv\Scripts\python.exe"
$MinerUApi = Join-Path $Root "venv\Scripts\mineru-api.exe"
$FrontendDir = Join-Path $Root "frontend"
$LogDir = Join-Path $Root ".data\logs"
$PidFile = Join-Path $LogDir "services.pids.json"

function Write-Step([string]$msg) { Write-Host ("==> " + $msg) -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host ("  OK  " + $msg) -ForegroundColor Green }
function Write-Warn2([string]$msg){ Write-Host ("  !!  " + $msg) -ForegroundColor Yellow }
function Write-Fail([string]$msg) { Write-Host ("  XX  " + $msg) -ForegroundColor Red }

function Test-HttpOk {
    param([string]$Url, [int]$TimeoutSec = 2)
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec -Proxy $null
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    } catch {
        return $false
    }
}

function Get-PortPids {
    param([int]$Port)
    try {
        return @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique
        )
    } catch {
        return @()
    }
}

function Stop-Port {
    param([int]$Port)
    $pids = Get-PortPids -Port $Port
    foreach ($procId in $pids) {
        if ($procId -and $procId -gt 0) {
            try {
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                Write-Warn2 ("stopped PID=" + $procId + " on port " + $Port)
            } catch {}
        }
    }
}

function Start-LoggedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [hashtable]$EnvMap
    )
    $outLog = Join-Path $LogDir ($Name + ".out.log")
    $errLog = Join-Path $LogDir ($Name + ".err.log")
    $launcher = Join-Path $LogDir ($Name + ".launcher.ps1")

    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine("`$ErrorActionPreference = 'Continue'")
    [void]$sb.AppendLine("Set-Location -LiteralPath '" + ($WorkingDirectory -replace "'", "''") + "'")
    if ($EnvMap) {
        foreach ($key in $EnvMap.Keys) {
            $val = [string]$EnvMap[$key]
            $val = $val -replace "'", "''"
            [void]$sb.AppendLine("`$env:" + $key + " = '" + $val + "'")
        }
    }
    $argParts = @()
    foreach ($a in $ArgumentList) {
        $escaped = [string]$a
        $escaped = $escaped -replace '"', '\"'
        if ($escaped -match '\s') {
            $argParts += ('"' + $escaped + '"')
        } else {
            $argParts += $escaped
        }
    }
    $argLine = $argParts -join " "
    $fp = $FilePath -replace "'", "''"
    $ol = $outLog -replace "'", "''"
    $el = $errLog -replace "'", "''"
    [void]$sb.AppendLine("& '" + $fp + "' " + $argLine + " 1>> '" + $ol + "' 2>> '" + $el + "'")

    Set-Content -Path $launcher -Value $sb.ToString() -Encoding UTF8

    $p = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher) `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Minimized `
        -PassThru

    return @{
        name = $Name
        pid  = $p.Id
        out  = $outLog
        err  = $errLog
        launcher = $launcher
    }
}

function Wait-Http {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Retries = 60,
        [int]$DelaySec = 2
    )
    for ($i = 1; $i -le $Retries; $i++) {
        if (Test-HttpOk -Url $Url) {
            Write-Ok ($Name + " ready  " + $Url)
            return $true
        }
        Write-Host ("  ... waiting " + $Name + " (" + $i + "/" + $Retries + ")")
        Start-Sleep -Seconds $DelaySec
    }
    Write-Fail ($Name + " not ready: " + $Url)
    return $false
}

# -- precheck --
if (-not (Test-Path $Py)) {
    Write-Error "Missing venv python: $Py. Create Python 3.12 venv and pip install -r requirements.txt"
}
if (-not (Test-Path $MinerUApi)) {
    Write-Error "Missing mineru-api: $MinerUApi. Run: .\venv\Scripts\pip install `"mineru[pipeline]==3.4.4`""
}
if (-not $SkipFrontend) {
    if (-not (Test-Path (Join-Path $FrontendDir "package.json"))) {
        Write-Error "Missing frontend: $FrontendDir"
    }
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Error "npm not found. Install Node.js or pass -SkipFrontend"
    }
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root ".data\mineru_output") | Out-Null

# -- 0) Elasticsearch (Docker) --
$esScript = Join-Path $Root "scripts\start_es.ps1"
if (Test-Path $esScript) {
    $esArgs = @("-ExecutionPolicy", "Bypass", "-File", $esScript)
    if ($Restart) { $esArgs += "-Restart" }
    & powershell.exe @esArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Elasticsearch not ready, services depending on ES will fail"
    }
}

# -- env --
if (-not $env:MINERU_MODEL_SOURCE) { $env:MINERU_MODEL_SOURCE = "modelscope" }
if (-not $env:MINERU_FALLBACK) { $env:MINERU_FALLBACK = "true" }
if (-not $env:MINERU_FORMULA_ENABLE) { $env:MINERU_FORMULA_ENABLE = "false" }
if (-not $env:MINERU_TABLE_ENABLE) { $env:MINERU_TABLE_ENABLE = "true" }

$env:MINERU_BACKEND = "pipeline"
$env:MINERU_API_URL = "http://127.0.0.1:$MinerUPort"
$env:MINERU_URL = "http://127.0.0.1:$AdapterPort"
$env:MINERU_ADAPTER_PORT = "$AdapterPort"
$env:MINERU_API_OUTPUT_ROOT = Join-Path $Root ".data\mineru_output"
$env:CUDA_VISIBLE_DEVICES = ""

$commonEnv = @{
    MINERU_MODEL_SOURCE    = $env:MINERU_MODEL_SOURCE
    MINERU_BACKEND         = "pipeline"
    MINERU_API_URL         = $env:MINERU_API_URL
    MINERU_URL             = $env:MINERU_URL
    MINERU_FALLBACK        = $env:MINERU_FALLBACK
    MINERU_FORMULA_ENABLE  = $env:MINERU_FORMULA_ENABLE
    MINERU_TABLE_ENABLE    = $env:MINERU_TABLE_ENABLE
    MINERU_ADAPTER_PORT    = "$AdapterPort"
    MINERU_API_OUTPUT_ROOT = $env:MINERU_API_OUTPUT_ROOT
    CUDA_VISIBLE_DEVICES   = ""
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " regulations_doc_platform  start" -ForegroundColor Cyan
Write-Host (" root: " + $Root) -ForegroundColor DarkGray
Write-Host (" venv: " + $Py) -ForegroundColor DarkGray
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$ports = @($MinerUPort, $AdapterPort, $ApiPort)
if (-not $SkipFrontend) { $ports += $FrontendPort }

if ($Restart) {
    Write-Step ("Restart: free ports " + ($ports -join ", "))
    foreach ($p in $ports) { Stop-Port -Port $p }
    Start-Sleep -Seconds 1
}

$started = @()

# 1) mineru-api
$mineruUrl = "http://127.0.0.1:$MinerUPort/health"
if ((-not $Restart) -and (Test-HttpOk -Url $mineruUrl)) {
    Write-Ok ("mineru-api already running :" + $MinerUPort)
} else {
    if (-not $Restart) { Stop-Port -Port $MinerUPort }
    Write-Step ("start mineru-api :" + $MinerUPort + " (pipeline/CPU)")
    $started += Start-LoggedProcess -Name "mineru-api" -FilePath $MinerUApi -ArgumentList @(
        "--host", "127.0.0.1",
        "--port", "$MinerUPort",
        "--enable-vlm-preload", "false"
    ) -WorkingDirectory $Root -EnvMap $commonEnv
}
if (-not (Wait-Http -Name "mineru-api" -Url $mineruUrl -Retries 60 -DelaySec 2)) {
    Write-Warn2 ("mineru-api not ready, see logs under " + $LogDir)
}

# 2) adapter
$adapterUrl = "http://127.0.0.1:$AdapterPort/health"
if ((-not $Restart) -and (Test-HttpOk -Url $adapterUrl)) {
    Write-Ok ("adapter already running :" + $AdapterPort)
} else {
    if (-not $Restart) { Stop-Port -Port $AdapterPort }
    Write-Step ("start adapter :" + $AdapterPort)
    $started += Start-LoggedProcess -Name "adapter" -FilePath $Py -ArgumentList @(
        "-m", "mineru_service.server"
    ) -WorkingDirectory $Root -EnvMap $commonEnv
}
if (-not (Wait-Http -Name "adapter" -Url $adapterUrl -Retries 30 -DelaySec 1)) {
    Write-Warn2 ("adapter not ready, see logs under " + $LogDir)
}

# 3) business API (cwd=backend, so api/services/core top-level packages can be imported)
$apiUrl = "http://127.0.0.1:$ApiPort/api/docs"
$apiDocsUrl = "http://127.0.0.1:$ApiPort/docs"
$BackendDir = Join-Path $Root "backend"
if ((-not $Restart) -and ((Test-HttpOk -Url $apiUrl) -or (Test-HttpOk -Url $apiDocsUrl))) {
    Write-Ok ("business API already running :" + $ApiPort)
} else {
    if (-not $Restart) { Stop-Port -Port $ApiPort }
    Write-Step ("start business API :" + $ApiPort)
    $started += Start-LoggedProcess -Name "api" -FilePath $Py -ArgumentList @(
        "-m", "uvicorn", "api.main:app",
        "--host", "127.0.0.1",
        "--port", "$ApiPort"
    ) -WorkingDirectory $BackendDir -EnvMap $commonEnv
}
$apiOk = Wait-Http -Name "business-api" -Url $apiUrl -Retries 30 -DelaySec 1
if (-not $apiOk) {
    $apiOk = Wait-Http -Name "business-api" -Url $apiDocsUrl -Retries 5 -DelaySec 1
}
if (-not $apiOk) {
    Write-Warn2 ("business API not ready, see logs under " + $LogDir)
}

# 4) frontend
$feUrl = "http://127.0.0.1:$FrontendPort/"
if (-not $SkipFrontend) {
    if ((-not $Restart) -and (Test-HttpOk -Url $feUrl)) {
        Write-Ok ("frontend already running :" + $FrontendPort)
    } else {
        if (-not $Restart) { Stop-Port -Port $FrontendPort }
        Write-Step ("start frontend :" + $FrontendPort)
        $started += Start-LoggedProcess -Name "frontend" -FilePath "cmd.exe" -ArgumentList @(
            "/c", ("npm run dev -- --host 127.0.0.1 --port " + $FrontendPort)
        ) -WorkingDirectory $FrontendDir -EnvMap $commonEnv
    }
    if (-not (Wait-Http -Name "frontend" -Url $feUrl -Retries 30 -DelaySec 1)) {
        Write-Warn2 ("frontend not ready, see logs under " + $LogDir)
    }
}

# save pid info
try {
    $payload = [ordered]@{
        started_at = (Get-Date).ToString("s")
        root       = $Root
        services   = $started
        urls       = [ordered]@{
            es         = "http://127.0.0.1:9200"
            mineru_api = ("http://127.0.0.1:" + $MinerUPort + "/health")
            adapter    = ("http://127.0.0.1:" + $AdapterPort + "/health")
            api        = ("http://127.0.0.1:" + $ApiPort)
            frontend   = ("http://127.0.0.1:" + $FrontendPort + "/")
        }
    }
    ($payload | ConvertTo-Json -Depth 6) | Set-Content -Path $PidFile -Encoding UTF8
} catch {}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " started" -ForegroundColor Cyan
Write-Host "----------------------------------------"
Write-Host ("  Elasticsearch: http://127.0.0.1:9200")
Write-Host ("  MinerU API   : http://127.0.0.1:" + $MinerUPort + "/health")
Write-Host ("  Adapter      : http://127.0.0.1:" + $AdapterPort + "/health")
Write-Host ("  Business API : http://127.0.0.1:" + $ApiPort)
Write-Host ("  API docs     : http://127.0.0.1:" + $ApiPort + "/docs")
if (-not $SkipFrontend) {
    Write-Host ("  Frontend     : http://127.0.0.1:" + $FrontendPort + "/") -ForegroundColor Green
}
Write-Host "----------------------------------------"
Write-Host ("  Logs         : " + $LogDir)
Write-Host "  Stop         : .\stop.ps1"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($OpenBrowser -and -not $SkipFrontend) {
    try { Start-Process $feUrl } catch {}
}

$allOk = $true
foreach ($pair in @(
    @("mineru-api", $mineruUrl),
    @("adapter", $adapterUrl),
    @("api", $apiUrl)
)) {
    if (Test-HttpOk -Url $pair[1]) {
        Write-Ok ($pair[0] + " health OK")
    } else {
        Write-Fail ($pair[0] + " health FAIL")
        $allOk = $false
    }
}
if (-not $SkipFrontend) {
    if (Test-HttpOk -Url $feUrl) {
        Write-Ok "frontend health OK"
    } else {
        Write-Fail "frontend health FAIL"
        $allOk = $false
    }
}

if (-not $allOk) {
    Write-Host ""
    Write-Warn2 ("Some services not ready. Check " + $LogDir + "\*.out.log / *.err.log")
    exit 1
}
exit 0
