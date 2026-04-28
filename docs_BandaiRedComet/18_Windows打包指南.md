# 18. Windows 打包指南（PyInstaller）

**目的**：把项目打成 `万代抢购器.exe`（单文件 50-70 MB），朋友双击即用。
**前置**：你（开发者）在 Windows 上有 Python，朋友机器**不需要 Python**。
**耗时**：第一次约 5 分钟（装依赖），后续 30 秒-1 分钟。

---

## 18.1 为什么必须在 Windows 上打包

PyInstaller 打的是**当前操作系统**的可执行文件：
- WSL Ubuntu 跑 PyInstaller → 输出 Linux ELF（不能给 Windows 用）
- Windows 跑 PyInstaller → 输出 .exe ✅

所以打包 + 测试这一步**必须在 Windows 原生**做。

---

## 18.2 准备：Windows 装 Python（一次性，5 分钟）

如果你 Windows 上没装 Python：

1. 微软商店搜 **"Python 3.13"** 或 **"Python 3.12"**（点"获取"，自动装）
2. 装完后打开 PowerShell：
   ```powershell
   python --version
   # 应输出：Python 3.13.x
   ```

如果有了就跳过这步。

---

## 18.3 打包（一条命令）

打开 **PowerShell**（普通权限，不需要管理员），切到项目根目录：

```powershell
# WSL 路径在 Windows 是这样访问：
cd \\wsl.localhost\Ubuntu\home\zzhuxiaojun\20260331_MangaTL_ClaudeQ\BandaiRedComet_20260421

# 或者你之前 git clone 一份到本地 Windows 盘也可以
# 比如 cd C:\dev\BandaiRedComet_20260421

# 跑打包脚本
.\scripts\build_exe.ps1
```

**第一次跑**会做 4 件事：
1. 检查 Python 版本
2. 建 `.venv-win/` 子目录（Windows 专用，**和 WSL 的 .venv/ 完全隔离**）
3. 装所有依赖（httpx / pywebview / PyQt6 / PyInstaller 等，约 350 MB 进 venv）
4. PyInstaller 打包

**之后每次跑**：跳过 1-3，只做第 4 步打包，30 秒-1 分钟出 exe。

**输出**：`dist\万代抢购器.exe`

---

## 18.4 测试 exe 能跑

```powershell
.\dist\万代抢购器.exe
```

或者直接资源管理器双击。

**预期**：
- 0.5-3 秒后弹出窗口（首次启动 PyInstaller 解压临时文件较慢）
- 窗口外观和 `bdgui` 跑出来的一致
- CK 自动验证、搜索、HAR 导入、抢购流程全可用

**Windows Defender 误报**：PyInstaller 打的 exe 偶尔会被误判，点"信任"或"加入排除"即可。**根本解法是签名**（Phase 4），暂时不做。

---

## 18.5 体积优化（可选）

当前 exe ≈ 50-70 MB，主要来自 PyQt6 + WebEngine。如果嫌大可以：

**1. 加 UPX 压缩**：
```powershell
# 装 UPX：从 https://upx.github.io/ 下载，扔到 PATH 里
# 改 万代抢购器.spec 的 upx=False → upx=True
```
压缩后约 25-35 MB。但 **UPX 压过的 exe 更容易被杀毒误报**，不推荐。

**2. 切 onedir 模式**：改 .spec 的 EXE → COLLECT，生成 `dist/万代抢购器/` 目录（启动快但分发要打成 zip）。

**3. 切 nsis 安装包**：用 NSIS 把单 exe 包成 1-3 MB 的安装器。Phase 4 再做。

---

## 18.6 给朋友 / 分发

打好的 `万代抢购器.exe` 单文件可以：
- ✅ 直接发给朋友（QQ / 微信文件 / 邮件 / 网盘）
- ✅ 上传到 GitHub Release v0.2.0 附件
- ✅ 朋友双击即用，不需要装 Python / 任何依赖

朋友拿到 exe 后还需要：
- 一次抓 HAR 拿 CK（朋友给的"上号软件"或自己抓包）
- 之后 GUI 里点"📁 从 HAR 导入 CK"，下次自动验证不用再粘

---

## 18.7 常见问题

### Q: 打包过程中 PyQt6 装不上 / 慢

国内可能 pip 走慢，加镜像源：
```powershell
.\.venv-win\Scripts\pip install pyqt6 qtpy "PyQt6-WebEngine" pyinstaller `
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q: 打完包 .exe 双击立刻闪退

加 `console=True`（在 .spec 文件里改）重新打包，再次双击会显示黑窗里的 Python 报错。常见：
- 缺 hidden import（看 stderr 里 ModuleNotFoundError → 加到 .spec hidden 列表）
- web 资源没打进去（Path 错误）

### Q: WebEngine 启动报错 / 白屏

确认 `PyQt6-WebEngine` 装好了。检查 .venv-win\Lib\site-packages\PyQt6 下有没有 `QtWebEngineWidgets.pyd`。

### Q: 朋友机器 Windows 7 能跑吗

PyQt6 + WebEngine 要求 Windows 10+。Windows 7 用户得换更老版本 PyQt5 + 重打包。**正常 v0.2.0 不支持 Win7**。

### Q: 打包后启动很慢

PyInstaller `--onefile` 模式每次启动要解压到临时目录，3-5 秒正常。改成 onedir 模式（参见 §18.5）启动 < 1 秒，但目录更乱。

---

## 18.8 GitHub Release 流程

打好 exe 后发布：

```bash
# 在 WSL 或 Windows 都行，gh CLI 装好
gh release create v0.2.0 dist/万代抢购器.exe \
  --title "v0.2.0 · GUI 朋友友好版（exe）" \
  --notes-file release_notes_v020.md
```

朋友下载链接形如：`https://github.com/zzhuxiaojun-glitch/.../releases/download/v0.2.0/万代抢购器.exe`

---

## 18.9 路线图位置

```
✅ Phase 0  核心抢购
✅ Phase 1  GUI MVP
✅ Phase 2  GUI 体验优化（搜索/CK/SQLite/时区/耗时）
⏳ Phase 3  打 exe（你按本文档操作）  ← 在这
⏳ Phase 3.5 真抢购演练（可选，建议在 Phase 3 之后用 exe 做）
⏳ Phase 4+ 安装包 / 自动更新 / 内置抓 CK
```
