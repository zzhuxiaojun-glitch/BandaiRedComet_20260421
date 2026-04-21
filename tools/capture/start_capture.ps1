# 万代小程序流量捕获脚本
# 在 Windows PowerShell 里双击或右键『用 PowerShell 运行』
# 需要管理员权限（用来让 mitmproxy 以 local 模式按进程截流）

[CmdletBinding()]
param(
    [string]$OutFile = "bandai_capture.har",
    [string]$Processes = "WeChat,WeChatAppEx"
)

$ErrorActionPreference = "Stop"

# ─── 全局错误兜底：任何异常都暂停，防止窗口闪退 ─
trap {
    Write-Host ""
    Write-Host "❌ 脚本出错:" -ForegroundColor Red
    Write-Host "   $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "位置: $($_.InvocationInfo.PositionMessage)" -ForegroundColor DarkYellow
    Write-Host ""
    Read-Host "按回车退出（截图发我）"
    exit 1
}

# ─── 同时把整个会话记录下来方便排查 ────────────
try { Start-Transcript -Path "$PSScriptRoot\capture_session.log" -Force | Out-Null } catch {}

# ─── 0. 管理员权限检查 ─────────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(`
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "需要管理员权限，正在尝试提权（UAC 弹窗请点『是』）..." -ForegroundColor Yellow
    try {
        Start-Process powershell -Verb RunAs -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-NoExit",
            "-File", "`"$PSCommandPath`""
        )
    } catch {
        Write-Host "❌ UAC 提权失败: $_" -ForegroundColor Red
        Read-Host "按回车退出（通常是 UAC 被拒绝，请重试并点『是』）"
        exit 1
    }
    exit
}

Write-Host "✅ 已获得管理员权限" -ForegroundColor Green
Write-Host ""

# ─── 1. 检查 Python ─────────────────────────
Write-Host "[1/4] 检查 Python..." -ForegroundColor Cyan
try {
    $pyver = python --version 2>&1
    Write-Host "    $pyver" -ForegroundColor Gray
} catch {
    Write-Host "    未检测到 python。请先安装 Python 3.11+ (https://www.python.org/downloads/)" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# ─── 2. 检查并安装 mitmproxy ──────────────────
Write-Host "[2/4] 检查 mitmproxy..." -ForegroundColor Cyan
$mitmVersion = ""
try {
    $mitmVersion = (mitmdump --version 2>&1 | Select-String -Pattern "Mitmproxy" | Select-Object -First 1).ToString()
} catch {
    $mitmVersion = ""
}

if (-not $mitmVersion) {
    Write-Host "    未安装，开始安装 mitmproxy..." -ForegroundColor Yellow
    python -m pip install --upgrade mitmproxy
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    安装失败" -ForegroundColor Red
        Read-Host "按回车退出"
        exit 1
    }
} else {
    Write-Host "    $mitmVersion" -ForegroundColor Gray
}

# ─── 2.5 确保根证书已装到 Windows 信任库 ────────
Write-Host "[2.5/4] 检查 mitmproxy 根证书..." -ForegroundColor Cyan
$certPath = "$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.cer"
if (-not (Test-Path $certPath)) {
    Write-Host "    首次运行，生成证书..." -ForegroundColor Yellow
    $p = Start-Process mitmdump -ArgumentList "--no-http2" -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 3
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}
$existing = Get-ChildItem Cert:\LocalMachine\Root -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -match "mitmproxy" }
if (-not $existing) {
    Write-Host "    安装到 LocalMachine\Root..." -ForegroundColor Yellow
    Import-Certificate -FilePath $certPath -CertStoreLocation "Cert:\LocalMachine\Root" | Out-Null
    Write-Host "    ✅ 证书已装。务必彻底重启微信后再继续！" -ForegroundColor Green
    $wx = Get-Process -Name WeChat, WeChatAppEx -ErrorAction SilentlyContinue
    if ($wx) {
        Write-Host "    检测到微信正在运行，建议先关掉所有 WeChat / WeChatAppEx" -ForegroundColor Yellow
        $k = Read-Host "要我帮你结束这些进程吗？(y/N)"
        if ($k -eq "y" -or $k -eq "Y") {
            $wx | Stop-Process -Force -ErrorAction SilentlyContinue
            Write-Host "    ✅ 微信进程已结束，重开微信登录后再按回车继续" -ForegroundColor Green
        }
    }
} else {
    Write-Host "    ✅ 证书已在信任库中" -ForegroundColor Green
}

# ─── 3. 提示 ─────────────────────────────────
Write-Host ""
Write-Host "[3/4] 即将启动抓包" -ForegroundColor Cyan
Write-Host "    过滤进程: $Processes" -ForegroundColor Gray
Write-Host "    输出文件: $OutFile" -ForegroundColor Gray
Write-Host "    只保留域名: *.bandainamcoshanghai.com" -ForegroundColor Gray
Write-Host ""
Write-Host "  ⚠️  首次运行会触发 Windows 防火墙弹窗，允许即可。" -ForegroundColor Yellow
Write-Host "  ⚠️  首次运行会自动安装 WinDivert 驱动，也允许即可。" -ForegroundColor Yellow
Write-Host ""
Write-Host "  抓完之后在此窗口按 Ctrl+C 即可停止，HAR 会保存到脚本目录。" -ForegroundColor Yellow
Write-Host ""
Read-Host "准备好了按回车开始"

# ─── 4. 启动 mitmdump ────────────────────────
Push-Location $PSScriptRoot
Write-Host "[4/4] mitmdump 启动中..." -ForegroundColor Cyan

$args = @(
    "--mode", "local:$Processes",
    "--set", "allow_hosts=.*\.bandainamcoshanghai\.com",
    "--set", "hardump=$OutFile",
    "--set", "console_eventlog_verbosity=info",
    "--showhost"
)

try {
    & mitmdump @args
} finally {
    Pop-Location
    Write-Host ""
    Write-Host "抓包结束。HAR 文件: $((Resolve-Path $OutFile).Path)" -ForegroundColor Green
    Write-Host "下一步请运行:  python sanitize_har.py $OutFile" -ForegroundColor Yellow
    Read-Host "按回车退出"
}
