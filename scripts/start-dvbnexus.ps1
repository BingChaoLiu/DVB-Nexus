# DVB-Nexus 一键启动脚本（由仓库根目录的 start.cmd 调起，也可直接用 PowerShell 运行）
# - 启动后端 uvicorn（127.0.0.1:8765）与前端 Vite（固定 127.0.0.1:5188，strictPort）
# - 服务就绪后打开默认浏览器；重复运行安全：端口已被监听时跳过该服务
# - 每个服务一个独立窗口，关闭对应窗口即停止该服务
param(
    [switch]$NoOpen   # 只启动服务，不打开浏览器（供自动化/测试使用）
)

$Root = Split-Path -Parent $PSScriptRoot

# ---- 可配置项 ----
# 数据库路径（与 README 快速开始一致；已在系统环境变量设置时不覆盖）
if (-not $env:DVBNEXUS_DB_PATH) { $env:DVBNEXUS_DB_PATH = 'D:/dvbnexus-data/dvbnexus.db' }
$BackendPort = 8765
# 前端固定 5188（strictPort + 显式绑定 IPv4 回环）：5173 常被其它程序（如 Foxmail）占用
# 导致 Vite 端口漂移；不指定 --host 时 Vite 只绑 ::1，127.0.0.1 探测会误判未就绪
$FrontendPort = 5188

function Fail($msg) {
    Write-Host "[错误] $msg" -ForegroundColor Red
    Read-Host '按回车键关闭本窗口'
    exit 1
}

# ---- 环境检查 ----
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail '未找到 python，请先安装 Python >= 3.10 并加入 PATH'
}
& python -c 'import uvicorn, bootstrap' 2>$null
if ($LASTEXITCODE -ne 0) { Fail '后端未安装，请先在仓库根目录执行: pip install -e .' }
if (-not (Test-Path "$Root\frontend\node_modules")) {
    Fail '前端依赖未安装，请先执行: cd frontend && npm install'
}
& python -c 'import websockets' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '[警告] 未安装 websockets，实时推送不可用（建议: pip install "websockets>=14,<16"）' -ForegroundColor Yellow
}

# ---- 数据库目录（不存在则创建） ----
$dbDir = Split-Path -Parent $env:DVBNEXUS_DB_PATH
if ($dbDir -and -not (Test-Path $dbDir)) {
    Write-Host "[init] 创建数据库目录 $dbDir"
    New-Item -ItemType Directory -Path $dbDir -Force | Out-Null
}

# ---- 就绪探测（HTTP 直连 127.0.0.1，绕过系统代理） ----
# Windows PowerShell 5.1 不自动加载 System.Net.Http，需显式 Add-Type；
# 加载失败时退化为 TCP 连通探测（uvicorn/vite 端口绑定后即刻可服务）
$httpClient = $null
try {
    Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $httpClient = New-Object System.Net.Http.HttpClient($handler)
    $httpClient.Timeout = [TimeSpan]::FromSeconds(2)
} catch { }
function Test-HttpReady($url, $port) {
    if ($httpClient) {
        try {
            $resp = $httpClient.GetAsync($url).Result
            $resp.Dispose()
            return $true
        } catch { return $false }
    }
    $client = New-Object System.Net.Sockets.TcpClient
    try { $client.Connect('127.0.0.1', $port); return $client.Connected } catch { return $false } finally { $client.Close() }
}
function Test-PortListening($port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

# ---- 启动后端（已在运行则跳过） ----
if (Test-PortListening $BackendPort) {
    Write-Host "[跳过] 端口 $BackendPort 已有后端在运行"
} else {
    Write-Host "[启动] 后端 http://127.0.0.1:$BackendPort（窗口: dvb-nexus-backend）"
    # 逐 token 传参：避免 PS 5.1 Start-Process + cmd /k 的整串引号解析问题（title/echo 会被吞掉）
    Start-Process cmd.exe -ArgumentList @('/k', 'title', 'dvb-nexus-backend', '&&', 'echo', '[DVB-Nexus 后端] 关闭本窗口即停止服务', '&&', 'python', '-m', 'uvicorn', 'bootstrap.asgi:app', '--host', '127.0.0.1', '--port', "$BackendPort") -WorkingDirectory $Root | Out-Null
    $ok = $false
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-HttpReady "http://127.0.0.1:$BackendPort/api/v1/version" $BackendPort) { $ok = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ok) { Fail "后端 30 秒内未就绪，请查看 dvb-nexus-backend 窗口中的报错" }
}
Write-Host "[就绪] 后端: http://127.0.0.1:$BackendPort"

# ---- 启动前端（已在运行则跳过） ----
if (Test-PortListening $FrontendPort) {
    Write-Host "[跳过] 端口 $FrontendPort 已有前端在运行"
} else {
    Write-Host "[启动] 前端 http://localhost:$FrontendPort（窗口: dvb-nexus-frontend）"
    Start-Process cmd.exe -ArgumentList @('/k', 'title', 'dvb-nexus-frontend', '&&', 'echo', '[DVB-Nexus 前端] 关闭本窗口即停止服务', '&&', 'npm', 'run', 'dev', '--', '--port', "$FrontendPort", '--strictPort', '--host', '127.0.0.1') -WorkingDirectory "$Root\frontend" | Out-Null
    $ok = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-HttpReady "http://127.0.0.1:$FrontendPort/" $FrontendPort) { $ok = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ok) { Fail "前端 60 秒内未就绪，请查看 dvb-nexus-frontend 窗口中的报错" }
}
Write-Host "[就绪] 前端: http://localhost:$FrontendPort"

# ---- 打开浏览器 ----
if ($NoOpen) {
    Write-Host '[跳过] 已指定 -NoOpen，不打开浏览器'
} else {
    Start-Process "http://localhost:$FrontendPort/"
}

Write-Host ''
Write-Host '================= DVB-Nexus 已启动 ================='
Write-Host "  前端  http://localhost:$FrontendPort/"
Write-Host "  后端  http://127.0.0.1:$BackendPort/api/v1/version"
Write-Host '  停止: 关闭 dvb-nexus-backend / dvb-nexus-frontend 窗口'
Write-Host '====================================================='
if (-not $NoOpen) {
    Write-Host '本窗口 5 秒后自动关闭...'
    Start-Sleep -Seconds 5
}
exit 0
