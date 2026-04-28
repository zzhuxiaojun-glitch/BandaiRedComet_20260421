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
            elif cfg.provider == "pushplus":
                # PushPlus 一个 token 可同时推到微信公众号 / QQ / 钉钉等
                # 前提：用户在 pushplus.plus 网站绑定相应通道
                # 默认走"一对一" 推送（默认通道由用户在网站设置）
                await c.post(
                    "http://www.pushplus.plus/send",
                    json={
                        "token": cfg.token,
                        "title": title,
                        "content": content,
                    },
                )
        logger.info(f"通知已推送 [{cfg.provider}]")
    except Exception as e:
        logger.error(f"通知推送失败: {e}")
