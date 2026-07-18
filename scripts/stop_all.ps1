# 一键停止：释放 mineru-api / adapter / 业务 API / 前端 占用的端口
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\stop_all.ps1

param(
    [int]$MinerUPort = 8001,
    [int]$AdapterPort = 8003,
    [int]$ApiPort = 8002,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
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
        Write-Host "  端口 $Port : 无监听进程"
        return
    }
    foreach ($procId in $pids) {
        if (-not $procId -or $procId -le 0) { continue }
        try {
            $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
            $name = if ($p) { $p.ProcessName } else { "?" }
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Write-Host "  端口 $Port : 已结束 PID=$procId ($name)" -ForegroundColor Yellow
        } catch {
            Write-Host "  端口 $Port : 结束 PID=$procId 失败: $_" -ForegroundColor Red
        }
    }
}

Write-Host "==> 停止 regulations_doc_platform 相关服务" -ForegroundColor Cyan
foreach ($p in @($MinerUPort, $AdapterPort, $ApiPort, $FrontendPort)) {
    Stop-Port $p
}

# 顺带清理本次 start 拉起的包装 powershell（若仍残留）
$pidFile = Join-Path $LogDir "services.pids.json"
if (Test-Path $pidFile) {
    try {
        $info = Get-Content $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($svc in @($info.services)) {
            if ($svc.pid) {
                $proc = Get-Process -Id $svc.pid -ErrorAction SilentlyContinue
                if ($proc) {
                    Stop-Process -Id $svc.pid -Force -ErrorAction SilentlyContinue
                    Write-Host "  结束启动包装进程 $($svc.name) PID=$($svc.pid)" -ForegroundColor Yellow
                }
            }
        }
    } catch {}
}

Write-Host "==> 完成" -ForegroundColor Green
