"""PyInstaller 打包入口。

等价于 `python -m bandai_sniper gui` 直接启动 GUI。

打包后行为：
  - 双击 .exe → PyInstaller 解压到临时目录运行
  - 日志写到 .exe 所在目录的 logs/ 子目录（持久化）
  - 配置存到 %APPDATA%/BandaiSniper/state.json
  - 历史 DB 存到 %APPDATA%/BandaiSniper/history.db
"""
from __future__ import annotations
import os
# 必须在 import webview / pythonnet 之前设置：
# pythonnet 3.x 默认尝试 coreclr (.NET 5+)，朋友 Win11 没装就崩。
# netfx = .NET Framework 4.x，Win10/11 系统内置必有，最稳。
os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")

import sys
from pathlib import Path

from loguru import logger


def _check_ascii_path() -> None:
    """检查 exe 所在路径是否含非 ASCII 字符。

    pythonnet/clr_loader 的原生 DLL 用 ANSI API 处理路径，中文路径下会
    "Failed to resolve Python.Runtime.Loader.Initialize"。打包后 frozen
    才检查；开发时跳过（dev 路径可能也有中文，但 dev 下用的是系统 Python
    + .venv，走的不是同一条加载链路）。
    """
    if not getattr(sys, "frozen", False):
        return
    exe_dir = Path(sys.executable).parent
    try:
        str(exe_dir).encode("ascii")
        return  # 全 ASCII，OK
    except UnicodeEncodeError:
        pass

    msg = (
        "无法在带中文/特殊字符的路径下启动。\n\n"
        f"当前路径：\n{exe_dir}\n\n"
        "请把整个【万代抢购器】文件夹剪切到纯英文路径再启动，例如：\n"
        "  C:\\BandaiSniper\\\n"
        "  D:\\Tools\\BandaiSniper\\\n\n"
        "（这是 pythonnet 库的限制，不是程序 bug）"
    )
    # 用 ctypes 弹原生 MessageBox（不依赖任何 GUI 框架，避免触发 pythonnet）
    try:
        import ctypes
        # MB_OK | MB_ICONERROR | MB_SYSTEMMODAL = 0x1010
        ctypes.windll.user32.MessageBoxW(0, msg, "万代抢购器 · 启动失败", 0x1010)
    except Exception:
        pass
    sys.exit(1)


def _resolve_log_dir() -> Path:
    """打包后写到 exe 同级 logs/，开发时写 ./logs/。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后 sys.executable = .exe 路径
        return Path(sys.executable).parent / "logs"
    return Path("./logs")


def _setup_logger() -> None:
    log_dir = _resolve_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    # PyInstaller --windowed 模式下 sys.stderr 是 None，loguru 不接受 None
    # 所以只在 stderr 有效时加这个 sink；exe 用户看不到这条，看 log 文件
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level="INFO",
            format="<green>{time:HH:mm:ss.SSS}</green> <level>{level:<7}</level> {message}",
        )
    logger.add(
        log_dir / "gui_{time:YYYYMMDD_HHmmss}.log",
        level="DEBUG",
        rotation="50 MB",
        retention="30 days",
        encoding="utf-8",
    )


def main() -> None:
    _check_ascii_path()  # 必须先于 setup_logger，logs 目录都还没建呢
    _setup_logger()
    logger.info("万代抢购器启动中...")
    # 注意：必须在 setup_logger 之后再 import，否则 ui/session.py 的 sink
    # 会先于 stderr 那条注册，多重输出
    from bandai_sniper.ui.gui import launch
    launch()


if __name__ == "__main__":
    main()
