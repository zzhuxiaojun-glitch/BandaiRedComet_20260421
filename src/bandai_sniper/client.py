import json
import time
from typing import Any

import httpx
from loguru import logger

BASE_URL = "https://rm-app-api.bandainamcoshanghai.com"


def _redact(headers: dict) -> dict:
    out = dict(headers)
    for k in list(out.keys()):
        if k.lower() == "api-access-token":
            out[k] = out[k][:6] + "***" + out[k][-4:] if out[k] else "***"
    return out


class BandaiClient:
    """所有万代 API 的薄包装。
    - 自动注入 api-access-token
    - HTTP/2 + keep-alive
    - 每次请求的 ts/url/status/latency/body 都落 jsonl
    """

    def __init__(self, ck: str, *, base_url: str = BASE_URL, timeout: float = 5.0):
        self._ck = ck
        self._client = httpx.AsyncClient(
            base_url=base_url,
            http2=True,
            timeout=timeout,
            headers={
                "api-access-token": ck,
                # TODO(抓包后补全): User-Agent / Referer / 其他标配头
                # "User-Agent": "...",
                # "Referer": "https://servicewechat.com/wxXXXXX/...",
            },
            limits=httpx.Limits(max_keepalive_connections=16, max_connections=32),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: Any = None,
    ) -> httpx.Response:
        t0 = time.monotonic()
        resp = await self._client.request(method, path, params=params, json=json_body)
        dt_ms = (time.monotonic() - t0) * 1000
        try:
            body_preview = resp.text[:500]
        except Exception:
            body_preview = "<binary>"
        logger.bind(tag="http").info(
            json.dumps(
                {
                    "method": method,
                    "url": str(resp.request.url),
                    "status": resp.status_code,
                    "latency_ms": round(dt_ms, 1),
                    "req_headers": _redact(dict(resp.request.headers)),
                    "req_body": json_body,
                    "resp_body": body_preview,
                },
                ensure_ascii=False,
            )
        )
        return resp

    async def get(self, path: str, **kw) -> httpx.Response:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw) -> httpx.Response:
        return await self.request("POST", path, **kw)
