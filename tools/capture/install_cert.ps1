# 把 mitmproxy 的根证书装到 Windows 信任库
# 只需跑一次。需要管理员权限。

$ErrorActionPreference = "Stop"

trap {
    Write-Host ""
    Write-Host "❌ 出错:" -ForegroundColor Red
    Write-Host "   $_" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# 管理员检查
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(`
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "需要管理员权限，正在提权..." -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit",
        "-File", "`"$PSCommandPath`""
    )
    exit
}

$certPath = "$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.cer"

# 如果证书不存在，先让 mitmdump 跑一次生成证书
if (-not (Test-Path $certPath)) {
    Write-Host "证书不存在，让 mitmdump 先生成一次..." -ForegroundColor Yellow
    $p = Start-Process mitmdump -ArgumentList "--no-http2" -PassThru
    Start-Sleep -Seconds 3
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

if (-not (Test-Path $certPath)) {
    Write-Host "❌ 证书仍未生成，请先手动跑一次 mitmdump 再来" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

Write-Host "[1/3] 找到证书: $certPath" -ForegroundColor Cyan

# 查看是否已装
$existing = Get-ChildItem Cert:\LocalMachine\Root | Where-Object {
    $_.Subject -match "mitmproxy"
}

if ($existing) {
    Write-Host "[2/3] 证书已经在信任库里了:" -ForegroundColor Green
    $existing | ForEach-Object { Write-Host "      $($_.Subject) (过期 $($_.NotAfter))" -ForegroundColor Gray }
    Write-Host "[3/3] 无需重复安装" -ForegroundColor Green
} else {
    Write-Host "[2/3] 安装证书到 LocalMachine\Root..." -ForegroundColor Cyan
    Import-Certificate -FilePath $certPath -CertStoreLocation "Cert:\LocalMachine\Root" | Out-Null
    Write-Host "[3/3] ✅ 安装完成" -ForegroundColor Green
}

Write-Host ""
Write-Host "⚠️  接下来必须彻底重启微信:" -ForegroundColor Yellow
Write-Host "    1) 任务管理器里结束所有 WeChat.exe / WeChatAppEx.exe" -ForegroundColor Yellow
Write-Host "    2) 重新打开微信 PC 并登录" -ForegroundColor Yellow
Write-Host "    3) 再跑 start_capture.ps1 / .bat" -ForegroundColor Yellow
Write-Host ""

$kill = Read-Host "要我现在就帮你结束所有微信进程吗？(y/N)"
if ($kill -eq "y" -or $kill -eq "Y") {
    Get-Process -Name WeChat, WeChatAppEx, WeChatOCR, WeChatUtility -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "✅ 已结束，请重新打开微信" -ForegroundColor Green
}

Read-Host "按回车退出"
