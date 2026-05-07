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
    _setup_logger()
    logger.info("万代抢购器启动中...")
    # 注意：必须在 setup_logger 之后再 import，否则 ui/session.py 的 sink
    # 会先于 stderr 那条注册，多重输出
    from bandai_sniper.ui.gui import launch
    launch()


if __name__ == "__main__":
    main()
