# 启动 MinerU pipeline（CPU）官方 API + 平台适配层
# 统一使用项目根目录 venv（Python 3.12 + mineru[pipeline]）
# 用法（项目根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts\start_mineru_pipeline.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$VenvPython = Join-Path $Root "venv\Scripts\python.exe"
$MinerUApi = Join-Path $Root "venv\Scripts\mineru-api.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "未找到 venv，请先: D:\workspace\python\python.exe -m venv venv && .\venv\Scripts\pip install -r requirements.txt"
}
if (-not (Test-Path $MinerUApi)) {
    Write-Error "未找到 mineru-api，请先: .\venv\Scripts\pip install `"mineru[pipeline]==3.4.4`""
}

# 国内模型源（CPU pipeline）
$env:MINERU_MODEL_SOURCE = if ($env:MINERU_MODEL_SOURCE) { $env:MINERU_MODEL_SOURCE } else { "modelscope" }
$env:MINERU_BACKEND = "pipeline"
$env:MINERU_API_URL = "http://127.0.0.1:8001"
$env:MINERU_ADAPTER_PORT = if ($env:MINERU_ADAPTER_PORT) { $env:MINERU_ADAPTER_PORT } else { "8003" }
$env:MINERU_FORMULA_ENABLE = if ($env:MINERU_FORMULA_ENABLE) { $env:MINERU_FORMULA_ENABLE } else { "false" }
$env:MINERU_TABLE_ENABLE = if ($env:MINERU_TABLE_ENABLE) { $env:MINERU_TABLE_ENABLE } else { "true" }
$env:MINERU_API_OUTPUT_ROOT = if ($env:MINERU_API_OUTPUT_ROOT) { $env:MINERU_API_OUTPUT_ROOT } else { (Join-Path $Root ".data\mineru_output") }
# 强制 CPU：不预加载 VLM
$env:CUDA_VISIBLE_DEVICES = ""

New-Item -ItemType Directory -Force -Path $env:MINERU_API_OUTPUT_ROOT | Out-Null

Write-Host "MINERU_MODEL_SOURCE=$($env:MINERU_MODEL_SOURCE)"
Write-Host "venv: $VenvPython"
Write-Host "Starting mineru-api on 8001 (pipeline/CPU)..."

Start-Process -FilePath $MinerUApi -ArgumentList @("--host", "127.0.0.1", "--port", "8001", "--enable-vlm-preload", "false") -WorkingDirectory $Root -WindowStyle Minimized

# 等待 health
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 2 -Proxy $null
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
    Write-Host "waiting mineru-api... $($i+1)"
}
if (-not $ok) {
    Write-Warning "mineru-api health 未在 120s 内就绪，仍尝试启动 adapter"
}

Write-Host "Starting adapter on $($env:MINERU_ADAPTER_PORT)..."
& $VenvPython -m mineru_service.server
