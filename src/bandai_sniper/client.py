import json
import time
from typing import Any

import httpx
from loguru import logger

from .crypto import aes_decrypt, build_signed_request

BASE_URL = "https://crm-app-api.bandainamcoshanghai.com"

# 默认伪装成 微信 PC 端小程序（万代服务端对缺失 UA / Referer 的请求会返回 432）
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf254173b) XWEB/19027"
)
DEFAULT_REFERER = "https://servicewechat.com/wx1cb4557915b2b7cd/129/page-frame.html"


def _redact(headers: dict) -> dict:
    out = dict(headers)
    for k in list(out.keys()):
        if k.lower() == "api-access-token":
            out[k] = out[k][:6] + "***" + out[k][-4:] if out[k] else "***"
    return out


class BandaiClient:
    """所有万代 API 的薄包装。
    - 每次请求通过 build_signed_request 生成签名 / AES body
    - 响应体整体是一段 base64 AES 密文，收到后自动解密为 dict
    - HTTP/2 + keep-alive
    """

    def __init__(
        self,
        ck: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 5.0,
        user_agent: str = DEFAULT_UA,
        referer: str = DEFAULT_REFERER,
    ):
        self._ck = ck
        self._time_offset_ms = 0
        self._client = httpx.AsyncClient(
            base_url=base_url,
            http2=True,
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=16, max_connections=32),
            headers={
                "User-Agent": user_agent,
                "Referer": referer,
                "xweb_xhr": "1",
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )

    def set_time_offset(self, offset_ms: int) -> None:
        """由 /common/config/get 返回的服务器时间校准。"""
        self._time_offset_ms = offset_ms

    async def aclose(self) -> None:
        await self._client.aclose()

    async def call(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
    ) -> dict | list:
        """执行一次已签名、已加密的请求，返回已解密的响应 dict / list。
        params 既是 URL query（GET）也是 body payload（POST），由 build_signed_request 决定。
        """
        req = build_signed_request(
            params or {},
            self._ck,
            method=method,
            time_offset_ms=self._time_offset_ms,
        )

        url = path + req["url_suffix"]
        headers = req["headers"]
        body = req["body"]

        t0 = time.monotonic()
        if method.upper() == "GET":
            resp = await self._client.request(method, url, headers=headers)
        else:
            resp = await self._client.request(
                method, url, headers=headers, content=body.encode("utf-8") if body else b""
            )
        dt_ms = (time.monotonic() - t0) * 1000

        # 万代响应体是整块 base64 AES 密文。
        raw_text = resp.text.strip()
        decoded: dict | list | str
        try:
            decoded = aes_decrypt(raw_text) if raw_text else {}
        except Exception:
            try:
                decoded = resp.json()
            except Exception:
                decoded = raw_text[:500]

        logger.bind(tag="http").info(
            json.dumps(
                {
                    "method": method,
                    "url": str(resp.request.url),
                    "status": resp.status_code,
                    "latency_ms": round(dt_ms, 1),
                    "req_params": params,
                    "req_headers": _redact(dict(resp.request.headers)),
                    "resp": decoded if isinstance(decoded, (dict, list)) else str(decoded)[:200],
                },
                ensure_ascii=False,
            )
        )
        resp.raise_for_status()
        return decoded

    async def get(self, path: str, params: Any = None) -> dict | list:
        return await self.call("GET", path, params=params)

    async def post(self, path: str, params: Any = None) -> dict | list:
        return await self.call("POST", path, params=params)
