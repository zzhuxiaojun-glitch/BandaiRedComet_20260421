"""万代接口封装（骨架）。

⚠️ 本文件里所有带 `TODO(抓包)` 标记的地方，都需要在拿到 `bandai_capture.sanitized.har` 之后
   根据真实请求补完。现在的路径/参数/响应字段都是按常见电商 API 惯例占位的。
"""

from dataclasses import dataclass
from typing import Any

from loguru import logger

from .client import BandaiClient


class ApiError(Exception):
    def __init__(self, code: str, msg: str, raw: Any = None):
        self.code = code
        self.msg = msg
        self.raw = raw
        super().__init__(f"[{code}] {msg}")


def _check(resp_json: dict) -> dict:
    """通用业务码处理。
    TODO(抓包): 根据真实响应调整 success 判定字段与数据字段名。
    常见形态: {"code":"0","msg":"ok","data":{...}} 或 {"status":200,"result":{...}}
    """
    code = str(resp_json.get("code", resp_json.get("status", "")))
    if code in ("0", "200", "SUCCESS"):
        return resp_json.get("data") or resp_json.get("result") or {}
    raise ApiError(code, resp_json.get("msg") or resp_json.get("message") or "unknown", resp_json)


@dataclass
class OrderDraft:
    """确认订单阶段返回的订单快照。"""
    confirm_token: str
    total_price: float
    raw: dict


@dataclass
class Order:
    order_no: str
    pay_params: dict
    raw: dict


class BandaiApi:
    def __init__(self, client: BandaiClient):
        self.c = client

    # ─── 预检 ────────────────────────────────────
    async def whoami(self) -> dict:
        """用来验证 CK 是否有效。
        TODO(抓包): 替换为一个无副作用的接口，如 /api/user/profile。
        """
        r = await self.c.get("/api/user/profile")
        r.raise_for_status()
        return _check(r.json())

    async def get_product(self, sku_id: str) -> dict:
        """TODO(抓包): 抓详情页时对应的接口。"""
        r = await self.c.get("/api/product/detail", params={"skuId": sku_id})
        r.raise_for_status()
        return _check(r.json())

    # ─── 下单四步 ────────────────────────────────
    async def add_to_cart(self, sku_id: str, quantity: int) -> dict:
        """TODO(抓包): 点『加入购物车』对应的接口。
        有些商品"立即购买"会跳过此步，直接走 prepare_order；根据抓包结果决定是否调用。
        """
        r = await self.c.post(
            "/api/cart/add",
            json_body={"skuId": sku_id, "quantity": quantity},
        )
        r.raise_for_status()
        return _check(r.json())

    async def prepare_order(self, sku_id: str, quantity: int, address_id: str) -> OrderDraft:
        """TODO(抓包): 『立即购买』或『去结算』 → 进确认订单页。
        响应里通常带一个一次性 token / tradeNo / checkoutId，用于下一步创建订单。
        """
        r = await self.c.post(
            "/api/order/confirm",
            json_body={
                "skuId": sku_id,
                "quantity": quantity,
                "addressId": address_id,
            },
        )
        r.raise_for_status()
        data = _check(r.json())
        return OrderDraft(
            confirm_token=data.get("confirmToken") or data.get("checkoutId") or "",
            total_price=float(data.get("totalPrice", 0)),
            raw=data,
        )

    async def create_order(self, draft: OrderDraft, sku_id: str, quantity: int, address_id: str) -> Order:
        """TODO(抓包): 『提交订单』 → 真正占库存。
        响应里通常带 order_no + 微信支付参数 (prepayId / timeStamp / nonceStr / paySign)。
        """
        r = await self.c.post(
            "/api/order/create",
            json_body={
                "confirmToken": draft.confirm_token,
                "skuId": sku_id,
                "quantity": quantity,
                "addressId": address_id,
            },
        )
        r.raise_for_status()
        data = _check(r.json())
        return Order(
            order_no=data.get("orderNo") or data.get("orderId") or "",
            pay_params=data.get("payParams") or data.get("paySign") or {},
            raw=data,
        )

    # ─── 可选：预热用 ────────────────────────────
    async def stock_of(self, sku_id: str) -> int | None:
        """若有独立的库存查询接口，可在 T-2s 高频轮询。
        TODO(抓包): 观察商品详情页秒刷新时是否有单独的 stock 接口。
        """
        try:
            r = await self.c.get("/api/product/stock", params={"skuId": sku_id})
            r.raise_for_status()
            data = _check(r.json())
            return int(data.get("stock", 0))
        except Exception as e:
            logger.debug(f"stock_of failed (非致命): {e}")
            return None
