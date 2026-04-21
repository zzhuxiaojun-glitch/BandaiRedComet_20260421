import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import ntplib
from loguru import logger

NTP_SERVERS = ["ntp.aliyun.com", "ntp.ntsc.ac.cn", "time.apple.com"]


def sync_ntp_offset(timeout: float = 2.0) -> float:
    """返回 NTP 时间 - 本机时间的偏差（秒）。
    若全部失败返回 0.0 并告警。
    """
    client = ntplib.NTPClient()
    for srv in NTP_SERVERS:
        try:
            resp = client.request(srv, version=3, timeout=timeout)
            offset = resp.offset
            logger.info(f"NTP sync via {srv}: offset={offset*1000:.1f}ms")
            return offset
        except Exception as e:
            logger.debug(f"NTP {srv} failed: {e}")
    logger.warning("NTP 全部失败，使用本机时间")
    return 0.0


def to_timestamp(dt: datetime, tz: str) -> float:
    """把 config 里的 snipe_time 转成绝对 UNIX 秒。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    return dt.timestamp()


async def wait_until(target_ts: float, *, offset: float = 0.0, lead_ms: int = 5) -> None:
    """精确等到 target_ts。
    - offset: NTP 偏差（本机比 NTP 慢则为正）
    - lead_ms: 提前多少毫秒醒来以抵消 TTFB
    单调时钟循环 + 最后 20ms 改 busy-wait。
    """
    adjusted_target = target_ts - offset - lead_ms / 1000
    while True:
        remaining = adjusted_target - time.time()
        if remaining <= 0:
            return
        if remaining > 1.0:
            await asyncio.sleep(remaining - 0.5)
        elif remaining > 0.02:
            await asyncio.sleep(0.005)
        else:
            # 最后 20ms busy-wait
            while time.time() < adjusted_target:
                pass
            return
