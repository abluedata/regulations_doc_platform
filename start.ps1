# 项目根一键启动入口
# 用法：
#   .\start.ps1
#   .\start.ps1 -Restart
#   .\start.ps1 -OpenBrowser
#   .\start.ps1 -SkipFrontend

param(
    [switch]$SkipFrontend,
    [switch]$Restart,
    [switch]$OpenBrowser
)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here "scripts\start_all.ps1"
$argsList = @()
if ($SkipFrontend) { $argsList += "-SkipFrontend" }
if ($Restart) { $argsList += "-Restart" }
if ($OpenBrowser) { $argsList += "-OpenBrowser" }

& $script @argsList
exit $LASTEXITCODE
