# 万代抢购器 · Windows exe 打包脚本
# 用法：在项目根目录的 PowerShell 里跑
#   .\scripts\build_exe.ps1
#
# 前置：Windows 装 Python 3.11+（Microsoft Store 一键装即可）
#       第一次跑会自动建 .venv-win 并装依赖（约 5 分钟）
#       之后每次跑只 PyInstaller，30 秒-1 分钟

$ErrorActionPreference = "Stop"

# 切到项目根目录（脚本在 scripts/ 下，回退一级）
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host ""
Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  万代抢购器 · Windows exe 打包"          -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ─── 1. 检查 Python ───
Write-Host "[1/4] 检查 Python..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 找不到 Python。请先装 Python 3.11+" -ForegroundColor Red
    Write-Host "   微软商店搜 'Python 3.13' 一键装最快" -ForegroundColor Red
    exit 1
}
Write-Host "    $pythonVersion" -ForegroundColor Green

# ─── 2. 建 / 复用 Windows 专用 venv ───
$VenvDir = ".venv-win"
if (-not (Test-Path $VenvDir)) {
    Write-Host "[2/4] 建 Windows venv（只第一次跑）..." -ForegroundColor Yellow
    python -m venv $VenvDir
    Write-Host "    ✓ $VenvDir 已建" -ForegroundColor Green
} else {
    Write-Host "[2/4] 已有 $VenvDir 复用" -ForegroundColor Green
}

$VenvPython = ".\$VenvDir\Scripts\python.exe"
$VenvPip    = ".\$VenvDir\Scripts\pip.exe"

# ─── 3. 装依赖 ───
Write-Host "[3/4] 装依赖（含 PyQt6 / PyInstaller）..." -ForegroundColor Yellow
& $VenvPip install --upgrade pip --quiet
& $VenvPip install -r requirements.txt --quiet
& $VenvPip install pyqt6 qtpy "PyQt6-WebEngine" pyinstaller --quiet
Write-Host "    ✓ 依赖就绪" -ForegroundColor Green

# ─── 4. PyInstaller 打包 ───
Write-Host "[4/4] PyInstaller 打包中（30 秒 - 1 分钟）..." -ForegroundColor Yellow
& $VenvPython -m PyInstaller --clean --noconfirm "万代抢购器.spec"

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 打包失败" -ForegroundColor Red
    exit 1
}

# ─── 完成报告（onedir 模式：dist\万代抢购器\万代抢购器.exe）───
$ExeDir  = Join-Path $ProjectRoot "dist\万代抢购器"
$ExePath = Join-Path $ExeDir "万代抢购器.exe"

if (Test-Path $ExePath) {
    $dirSize = (Get-ChildItem $ExeDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host ""
    Write-Host "═══════════════════════════════════════" -ForegroundColor Green
    Write-Host "  ✅ 打包成功" -ForegroundColor Green
    Write-Host "═══════════════════════════════════════" -ForegroundColor Green
    Write-Host "  输出目录：$ExeDir"
    Write-Host "  主 exe ：$ExePath"
    Write-Host ("  目录总大小：{0:N1} MB" -f $dirSize)
    Write-Host ""
    Write-Host "  双击 exe 启动 · 给朋友前先 zip 整个目录"

    # ─── 顺手打 zip 给朋友（覆盖旧的）───
    $ZipPath = Join-Path $ProjectRoot "dist\万代抢购器.zip"
    Write-Host ""
    Write-Host "[5/4] 顺手 zip 打包..." -ForegroundColor Yellow
    if (Test-Path $ZipPath) { Remove-Item $ZipPath }
    Compress-Archive -Path $ExeDir -DestinationPath $ZipPath -CompressionLevel Optimal
    if (Test-Path $ZipPath) {
        $zipSize = (Get-Item $ZipPath).Length / 1MB
        Write-Host ("    ✓ zip：$ZipPath（{0:N1} MB）" -f $zipSize) -ForegroundColor Green
    }
    Write-Host ""
} else {
    Write-Host "⚠️  打包完成但找不到 $ExePath" -ForegroundColor Yellow
}
