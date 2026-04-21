import httpx
from loguru import logger

from .config import Notify


async def push(cfg: Notify, title: str, content: str) -> None:
    if not cfg.enabled or cfg.provider == "none":
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            if cfg.provider == "bark":
                # cfg.token 形如 https://api.day.app/XXXX
                await c.post(f"{cfg.token.rstrip('/')}/{title}/{content}")
            elif cfg.provider == "server_chan":
                await c.post(
                    f"https://sctapi.ftqq.com/{cfg.token}.send",
                    data={"title": title, "desp": content},
                )
            elif cfg.provider == "feishu":
                await c.post(
                    cfg.token,
                    json={"msg_type": "text", "content": {"text": f"{title}\n{content}"}},
                )
        logger.info(f"通知已推送 [{cfg.provider}]")
    except Exception as e:
        logger.error(f"通知推送失败: {e}")
