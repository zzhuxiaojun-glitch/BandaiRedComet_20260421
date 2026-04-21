# 环境诊断：start_capture 跑不起来时先跑这个
# 双击会闪退？请改用：
#   1. 搜索栏搜 "PowerShell" → 右键 "以管理员身份运行"
#   2. cd 到本目录，再 .\diagnose.ps1

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "═══════════ 环境诊断 ═══════════" -ForegroundColor Cyan
Write-Host ""

# 1. PowerShell 版本
Write-Host "[1] PowerShell 版本: $($PSVersionTable.PSVersion)"

# 2. 管理员权限
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(`
    [Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host "[2] 管理员权限: $(if ($isAdmin) { '✅ 是' } else { '❌ 否（这是闪退最常见原因）' })"

# 3. 执行策略
Write-Host "[3] 执行策略（LocalMachine 级）: $(Get-ExecutionPolicy -Scope LocalMachine)"
Write-Host "    执行策略（CurrentUser 级）: $(Get-ExecutionPolicy -Scope CurrentUser)"
Write-Host "    当前进程生效策略: $(Get-ExecutionPolicy)"

# 4. Python
Write-Host -NoNewline "[4] Python: "
try {
    $py = & python --version 2>&1
    Write-Host "$py" -ForegroundColor Green
} catch {
    Write-Host "❌ 未安装或不在 PATH" -ForegroundColor Red
}

# 5. mitmproxy
Write-Host -NoNewline "[5] mitmproxy: "
try {
    $mitm = & mitmdump --version 2>&1 | Select-String "Mitmproxy" | Select-Object -First 1
    Write-Host "$mitm" -ForegroundColor Green
} catch {
    Write-Host "❌ 未安装（第一次跑 start_capture 会自动装）" -ForegroundColor Yellow
}

# 6. 微信进程
Write-Host "[6] 微信进程:"
$wx = Get-Process -Name WeChat, WeChatAppEx -ErrorAction SilentlyContinue
if ($wx) {
    $wx | ForEach-Object { Write-Host "    ✅ $($_.ProcessName) (PID $($_.Id))" -ForegroundColor Green }
} else {
    Write-Host "    ❌ 未运行（请先打开微信 PC 并登录）" -ForegroundColor Red
}

# 7. Mark-of-the-Web 检查
Write-Host "[7] 脚本文件是否被 Windows 标记为"来自网络":"
Get-ChildItem $PSScriptRoot -Filter "*.ps1" | ForEach-Object {
    $zone = Get-Item $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue
    if ($zone) {
        Write-Host "    ⚠️  $($_.Name) 被标记。跑下面这条命令解锁:" -ForegroundColor Yellow
        Write-Host "        Get-ChildItem $PSScriptRoot -Recurse | Unblock-File" -ForegroundColor Gray
    } else {
        Write-Host "    ✅ $($_.Name) 未被标记" -ForegroundColor Green
    }
}

# 8. 当前目录
Write-Host "[8] 脚本所在目录: $PSScriptRoot"
Write-Host ""
Write-Host "═══════════ 诊断结束 ═══════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "把以上内容截图发给我即可。" -ForegroundColor White
Read-Host "按回车退出"
