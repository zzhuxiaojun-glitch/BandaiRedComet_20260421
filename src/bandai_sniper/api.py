"""万代接口封装。所有路径 + 入参结构已由 2026-04-22 HAR 端到端验证。"""

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from .client import BandaiClient


class ApiError(Exception):
    def __init__(self, code: Any, msg: str, raw: Any = None):
        self.code = code
        self.msg = msg
        self.raw = raw
        super().__init__(f"[{code}] {msg}")


def _unwrap(resp: dict | list) -> Any:
    """万代响应统一形态：`{"code":0,"message":"操作成功","data":...}`。
    code=0 成功，其余抛 ApiError。
    """
    if not isinstance(resp, dict):
        return resp
    code = resp.get("code")
    if code in (0, "0"):
        return resp.get("data")
    raise ApiError(code, resp.get("message") or resp.get("msg") or "unknown", resp)


@dataclass
class OrderDraft:
    """confirmOrder 的完整响应 data。create_order 会把它原样回传。"""
    raw: dict
    sku_list: list[dict] = field(default_factory=list)
    order_amount: float = 0.0
    address: dict = field(default_factory=dict)


@dataclass
class Address:
    id: int
    province_id: str
    province_name: str
    city_id: str
    city_name: str
    district_id: str
    district_name: str
    receiver: str
    receiver_phone: str
    address: str  # 详细街道
    raw: dict

    @classmethod
    def from_list_item(cls, item: dict) -> "Address":
        return cls(
            id=item["id"],
            province_id=item["provinceId"],
            province_name=item["provinceName"],
            city_id=item["cityId"],
            city_name=item["cityName"],
            district_id=item["districtId"],
            district_name=item["districtName"],
            receiver=item["receiver"],
            receiver_phone=item["receiverPhone"],
            address=item["address"],
            raw=item,
        )


@dataclass
class PayParams:
    """createOrder 响应里的微信 JSAPI 支付参数。
    注意：后端字段名是 `packagev`（疑似 typo），微信 SDK 实际需要 `package`。
    小程序前端手动映射了一下，这里也做同样的映射。
    """
    prepay_id: str
    timestamp: str
    nonce_str: str
    package: str  # 映射自 packagev
    sign_type: str
    pay_sign: str
    order_id: int
    raw: dict

    @classmethod
    def from_resp(cls, data: dict) -> "PayParams":
        return cls(
            prepay_id=data["prepayId"],
            timestamp=str(data["timeStamp"]),
            nonce_str=data["nonceStr"],
            package=data.get("package") or data["packagev"],
            sign_type=data.get("signType", "RSA"),
            pay_sign=data["paySign"],
            order_id=int(data.get("id", 0)),
            raw=data,
        )


class BandaiApi:
    def __init__(self, client: BandaiClient):
        self.c = client

    # ═══════════════════════════════════════════════════════════════
    # 基础 / 预检
    # ═══════════════════════════════════════════════════════════════

    async def sync_timestamp(self) -> int:
        """拉服务器 ms 时间戳，同时验证签名。冒烟首选。
        响应 `data.timestamp` 即毫秒时间。顺便把 server-local 时差灌回 client。
        """
        import time as _time
        data = _unwrap(await self.c.get("/api/common/config/get", {}))
        server_ms = int(data["timestamp"])
        offset = server_ms - int(_time.time() * 1000)
        self.c.set_time_offset(offset)
        logger.info(
            f"server time synced, offset={offset}ms, "
            f"encryptionEnable={data.get('encryptionEnable')}"
        )
        return server_ms

    async def whoami(self) -> list[dict]:
        """验证 CK 有效 + 拿 memberId。每 item 带 `memberId`。无副作用。"""
        return _unwrap(await self.c.get(
            "/api/member/v1/app/personalPermission/getCurrentMemberPermission", {}
        ))

    async def check_agreement(self) -> list[dict]:
        """待同意的协议列表（空数组 = 已同意）。"""
        return _unwrap(await self.c.get("/api/member/v1/app/member/checkAgreementVersion", {}))

    # ═══════════════════════════════════════════════════════════════
    # 商品浏览
    # ═══════════════════════════════════════════════════════════════

    async def list_category_by_level(self, level: int = 2) -> list[dict]:
        return _unwrap(await self.c.get(
            "/api/commodity/v1/app/category/listByLevel", {"level": str(level)}
        ))

    async def list_category_by_parent(self, parent_id: int) -> list[dict]:
        return _unwrap(await self.c.get(
            "/api/commodity/v1/app/category/listByParentId", {"parentId": str(parent_id)}
        ))

    async def query_spu(
        self,
        *,
        category_id: int,
        page_num: int = 1,
        page_size: int = 12,
        can_buy: str = "1",
    ) -> dict:
        """返回 `{total, list}`。"""
        return _unwrap(await self.c.post(
            "/api/commodity/v1/app/spu/query",
            {
                "canBuy": can_buy,
                "categoryId": str(category_id),
                "pageNum": str(page_num),
                "pageSize": str(page_size),
            },
        ))

    async def query_spu_simple(self, spu_id_list: list[str]) -> list[dict]:
        return _unwrap(await self.c.post(
            "/api/commodity/v1/app/spu/simple/query", {"spuIdList": spu_id_list}
        ))

    async def query_recommendation(self, page_num: int = 1, page_size: int = 20) -> dict:
        return _unwrap(await self.c.post(
            "/api/commodity/v1/app/spu/v2/queryRecommendation",
            {"allowRecommend": "1", "pageNum": str(page_num), "pageSize": str(page_size)},
        ))

    # ═══════════════════════════════════════════════════════════════
    # 商品详情（下单前）
    # ═══════════════════════════════════════════════════════════════

    async def get_spu_detail(self, spu_id: str | int) -> dict:
        """商品详情。返回 stock / price / presaleType / saleStartTime 等关键字段。"""
        return _unwrap(await self.c.get(
            "/api/commodity/v1/app/spu/v2/detail/new", {"id": str(spu_id)}
        ))

    async def get_sku_list(self, spu_id: str | int) -> list[dict]:
        """取 SPU 下的 SKU 列表（含 `skuId`、库存、价格）。参数名 `id` 但传的是 spuId。"""
        return _unwrap(await self.c.get(
            "/api/commodity/v1/app/spu/sku/detail", {"id": str(spu_id)}
        ))

    async def get_near_store(self, spu_id: str | int) -> dict:
        """查询附近门店可售状态。返回 `{"storeCanBuy": bool}`。"""
        return _unwrap(await self.c.post(
            "/api/commodity/v1/app/spu/nearStore/get", {"spuId": str(spu_id)}
        ))

    async def is_collect(self, spu_id: str | int) -> bool:
        return bool(_unwrap(await self.c.get(
            "/api/member/v1/app/member/isCollect", {"id": str(spu_id)}
        )))

    # ═══════════════════════════════════════════════════════════════
    # 地址
    # ═══════════════════════════════════════════════════════════════

    async def get_default_address(self) -> dict | None:
        """默认地址。可能为空（新用户）。"""
        return _unwrap(await self.c.get(
            "/api/order/v1/app/address/getDefaultOrderAddress", {}
        ))

    async def list_addresses(self, page_num: int = 1, page_size: int = 20) -> list[Address]:
        data = _unwrap(await self.c.post(
            "/api/order/v1/app/address/getOrderAddressList",
            {"pageNum": str(page_num), "pageSize": str(page_size)},
        ))
        return [Address.from_list_item(it) for it in (data or {}).get("list", [])]

    # ═══════════════════════════════════════════════════════════════
    # 优惠券
    # ═══════════════════════════════════════════════════════════════

    async def query_available_coupons(self, sku_list: list[dict]) -> dict:
        """sku_list 元素 `{skuId, num}`。返回 `{firstList, secondList}`。"""
        return _unwrap(await self.c.post(
            "/api/marketing/v1/app/couponrecord/queryAppOrderCouponMemberList",
            {"skuList": sku_list},
        ))

    # ═══════════════════════════════════════════════════════════════
    # 下单四步（HAR 完全验证）
    # ═══════════════════════════════════════════════════════════════

    async def confirm_order(
        self,
        sku_list: list[dict],
        *,
        address: Address | None = None,
    ) -> OrderDraft:
        """确认订单（算价 / 确认库存，不占库存）。
        - 不带地址：只算 goodsPrice，运费=0
        - 带地址：返回含 freight 的完整 orderAmount
        实战流程：先不带地址调一次确认库存，再带地址调一次算运费。
        """
        payload: dict = {
            "latitude": "undefined",
            "longitude": "undefined",
            "skuList": sku_list,
        }
        if address is not None:
            payload.update({
                "provinceId": address.province_id,
                "provinceName": address.province_name,
                "cityId": address.city_id,
                "cityName": address.city_name,
                "districtId": address.district_id,
                "districtName": address.district_name,
                "receiver": address.receiver,
                "receiverPhone": address.receiver_phone,
                "receiverAddress": address.address,
            })
        data = _unwrap(await self.c.post(
            "/api/order/v1/app/order/confirmOrder", payload,
        ))
        return OrderDraft(
            raw=data,
            sku_list=data.get("skuList", []),
            order_amount=float(data.get("orderAmount", 0)),
            address=address.raw if address else {},
        )

    async def create_order(
        self,
        draft: OrderDraft,
        address: Address,
        *,
        use_point: int = 0,
    ) -> PayParams:
        """真正创建订单（占库存），返回微信 JSAPI 支付参数。
        payload = confirmOrder 响应 data 字符串化回传 + 地址 + usePoint。
        """
        # confirmOrder 返回的字段 → createOrder 入参（全部转字符串）
        d = draft.raw
        payload: dict = {
            "latitude": "undefined",
            "longitude": "undefined",
            "couponDiscountAmount": _js_str(d.get("couponDiscountAmount", 0)),
            "skuList": [_stringify_sku(s) for s in d.get("skuList", [])],
            "orderType": _js_str(d.get("orderType", "")),
            "orderAmount": _js_str(d.get("orderAmount", "")),
            "freight": _js_str(d.get("freight", 0)),
            "freightBeforeDiscount": _js_str(d.get("freightBeforeDiscount", 0)),
            "goodsOriginalPrice": _js_str(d.get("goodsOriginalPrice", "")),
            "goodsPrice": _js_str(d.get("goodsPrice", "")),
            "goodsPayAmount": _js_str(d.get("goodsPayAmount", "")),
            "orderPoint": _js_str(d.get("orderPoint", 0)),
            "depositAmount": _js_str(d.get("depositAmount", 0)),
            "balanceAmount": _js_str(d.get("balanceAmount", 0)),
            "usePoint": _js_str(use_point),
            # 地址
            "provinceId": address.province_id,
            "provinceName": address.province_name,
            "cityId": address.city_id,
            "cityName": address.city_name,
            "districtId": address.district_id,
            "districtName": address.district_name,
            "receiver": address.receiver,
            "receiverPhone": address.receiver_phone,
            "receiverAddress": address.address,
        }
        data = _unwrap(await self.c.post(
            "/api/order/v1/app/order/createOrder", payload,
        ))
        return PayParams.from_resp(data)

    async def get_order_detail(self, order_id: str | int) -> dict:
        """根据订单 id（不是 orderNo）查详情。用于抢购后确认订单状态。"""
        return _unwrap(await self.c.post(
            "/api/order/v1/app/order/getOrderDetail", {"id": str(order_id)}
        ))


def _js_str(v: Any) -> str:
    """JS `String(v)` 等价：142.0 → "142"（不是 Python 的 "142.0"），20.5 → "20.5"。
    createOrder 的入参全部是字符串，且数字不带无谓的 .0 —— 签名必须匹配。
    """
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return repr(v)  # "20.5" 样式，不是科学计数
    return str(v)


def _stringify_sku(sku: dict) -> dict:
    """把 confirmOrder 响应里的 sku item 转成 createOrder 入参格式（全 JS 字符串）。"""
    fields = [
        "spuId", "skuId", "num", "goodsOriginalPrice", "goodsPrice",
        "payAmount", "point", "totalPoint", "spuType", "skuWeight",
        "skuMediaUrl", "spuName", "skuName", "freeFreight", "purchaseLimitLevel",
    ]
    return {k: _js_str(sku[k]) for k in fields if k in sku}
