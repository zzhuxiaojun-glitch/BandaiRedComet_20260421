# 找微信小程序缓存里的 wxapkg 文件
# 微信 4.0+ 路径：%APPDATA%\Tencent\xwechat\radium\Applet\packages\<wxid>\<n>\__APP__.wxapkg

$ErrorActionPreference = "Continue"
$APPID = "wx1cb4557915b2b7cd"  # 万代南梦宫官方微商城

$roots = @(
    "$env:APPDATA\Tencent\xwechat\radium",
    "$env:APPDATA\Tencent\xwechat",
    "$env:LOCALAPPDATA\Tencent\xwechat",
    "$env:USERPROFILE\Documents\xwechat_files",
    "$env:USERPROFILE\Documents\WeChat Files",
    "$env:APPDATA\Tencent\WeChat",
    "$env:LOCALAPPDATA\Tencent\WeChat"
)

Write-Host ""
Write-Host "═══ 搜索 .wxapkg 文件 ═══" -ForegroundColor Cyan
Write-Host "目标 AppID: $APPID" -ForegroundColor Gray
Write-Host ""

$allHits = @()
foreach ($root in $roots) {
    if (-not (Test-Path $root)) {
        Write-Host "[skip] $root  (不存在)" -ForegroundColor DarkGray
        continue
    }
    Write-Host "[扫描] $root" -ForegroundColor DarkGray
    $hits = Get-ChildItem -Path $root -Recurse -Filter "*.wxapkg" -ErrorAction SilentlyContinue
    foreach ($h in $hits) {
        $allHits += $h
        $isTarget = $h.FullName -like "*$APPID*"
        $color = if ($isTarget) { "Green" } else { "Gray" }
        $mark = if ($isTarget) { "🎯" } else { "  " }
        Write-Host "$mark $($h.FullName)  ($([math]::Round($h.Length/1KB,1)) KB)" -ForegroundColor $color
    }
}

Write-Host ""
Write-Host "═══ 匹配 AppID 的目录 ═══" -ForegroundColor Cyan
foreach ($root in $roots) {
    if (-not (Test-Path $root)) { continue }
    $appDirs = Get-ChildItem -Path $root -Recurse -Directory -Filter "*$APPID*" -ErrorAction SilentlyContinue
    foreach ($d in $appDirs) {
        Write-Host "🎯 $($d.FullName)" -ForegroundColor Green
        Get-ChildItem -Path $d.FullName -Recurse -File -ErrorAction SilentlyContinue |
            Select-Object -First 30 |
            ForEach-Object {
                $rel = $_.FullName.Substring($d.FullName.Length)
                Write-Host "   $rel  ($([math]::Round($_.Length/1KB,1)) KB)" -ForegroundColor Gray
            }
    }
}

Write-Host ""
if ($allHits.Count -eq 0) {
    Write-Host "⚠️  未找到任何 .wxapkg 文件" -ForegroundColor Yellow
    Write-Host "    请先在微信里打开过万代小程序（让它下载缓存），再重试本脚本" -ForegroundColor Yellow
} else {
    Write-Host "✅ 共找到 $($allHits.Count) 个 .wxapkg 文件" -ForegroundColor Green
    $bandai = $allHits | Where-Object { $_.FullName -like "*$APPID*" }
    if ($bandai) {
        Write-Host "🎯 其中万代相关:" -ForegroundColor Green
        $bandai | ForEach-Object { Write-Host "     $($_.FullName)" -ForegroundColor Green }
    } else {
        Write-Host "⚠️  但没有万代的（AppID 未匹配）。请打开万代小程序再重试" -ForegroundColor Yellow
    }
}

Write-Host ""
Read-Host "把上面的输出截图发我，然后按回车退出"
