"""HAR 文件解析工具，抽取万代商品信息等。

复用方：
  - tools/verify/list_products_from_har.py（CLI）
  - ui/gui.py Api.pick_har_and_list（GUI "从 HAR 选商品"）
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse

from .crypto import aes_decrypt


def _decrypt_url_param(enc: str):
    """HAR 里的 URL 参数可能 0/1/2 层 URL 编码，三种都试。"""
    for c in (enc, unquote(enc), unquote(unquote(enc))):
        try:
            return aes_decrypt(c)
        except Exception:
            pass
    return None


def extract_products_from_har(har_path: str | Path) -> list[dict]:
    """扫 HAR，返回所有在请求/响应里出现的商品的结构化信息列表。

    每项字段：
      spu_id / name_cn / name_jp / price / stock / status (0=可售/1=未开售) /
      sale_start / deposit
    """
    path = Path(har_path)
    if not path.exists():
        raise FileNotFoundError(f"HAR 文件不存在: {path}")

    har = json.loads(path.read_text(encoding="utf-8"))
    seen: dict[str, dict] = {}

    for entry in har["log"]["entries"]:
        url = entry["request"]["url"]
        if "bandainamcoshanghai.com/api/" not in url:
            continue

        # 只关心 spu 详情 / sku 详情
        is_spu_detail = "/spu/v2/detail/new" in url
        is_sku_detail = "/spu/sku/detail" in url
        if not (is_spu_detail or is_sku_detail):
            continue

        # 从 URL 参数抽 id
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        enc = qs.get("encryptionUrlParams", [None])[0]
        if not enc:
            continue
        req = _decrypt_url_param(enc)
        if not isinstance(req, dict):
            continue
        spu_id = str(req.get("id") or req.get("spuId") or "")
        if not spu_id:
            continue

        # 响应体整块是 AES 密文
        resp_text = entry.get("response", {}).get("content", {}).get("text", "")
        if not resp_text:
            continue
        try:
            resp = aes_decrypt(resp_text.strip())
        except Exception:
            continue
        if not isinstance(resp, dict) or resp.get("code") not in (0, "0"):
            continue

        data = resp.get("data")
        if is_spu_detail and isinstance(data, dict):
            # spu/v2/detail/new 返回 dict
            info = {
                "spu_id": spu_id,
                "name_cn": data.get("nameCn", ""),
                "name_jp": data.get("nameJp") or data.get("nameJa") or "",
                "price": data.get("price"),
                "stock": data.get("stock"),
                "status": data.get("saleStatus"),
                "sale_start": data.get("saleStartTime", ""),
                "deposit": data.get("depositAmount"),
            }
            # spu 详情优先，覆盖 sku 详情的占位
            seen[spu_id] = info
        elif is_sku_detail and isinstance(data, list) and spu_id not in seen:
            # sku 列表作为兜底（没有 spu 详情时才用）
            first = next((s for s in data if isinstance(s, dict)), None)
            if first:
                seen[spu_id] = {
                    "spu_id": spu_id,
                    "name_cn": first.get("nameCn", ""),
                    "name_jp": "",  # sku 层没有日文原名
                    "price": first.get("pricePlusTaxRmb"),
                    "stock": first.get("stock"),
                    "status": None,
                    "sale_start": "",
                    "deposit": None,
                }

    return sorted(seen.values(), key=lambda x: x["spu_id"])


# 服务端 saleStatus 取值（2026-04-26 实战观察）
# 0 = 可售（在 saleStartTime ~ saleEndTime 窗口内）
# 1 = 未开售（saleStartTime 之前）
# 2 = 已结束（saleEndTime 之后，小程序底部显示"预售已结束"灰按钮）
SALE_STATUS_MAP: dict[int | None, str] = {
    0: "可售",
    1: "未开售",
    2: "已结束",
    None: "-",
}


def format_sale_status(s) -> str:
    """saleStatus → 中文，未知值原样数字。"""
    if s in SALE_STATUS_MAP:
        return SALE_STATUS_MAP[s]
    return f"未知({s})"


def format_products_table(products: Iterable[dict]) -> str:
    """给 CLI 打印的漂亮表格。"""
    lines = [
        f"{'SPU ID':<8} {'价格':<10} {'库存':<8} {'状态':<10} {'开售时间':<22} 商品名",
        "─" * 100,
    ]
    for info in products:
        price = f"¥{info['price']}" if info['price'] is not None else "-"
        stock = str(info['stock']) if info['stock'] is not None else "-"
        status = format_sale_status(info["status"])
        lines.append(
            f"{info['spu_id']:<8} {price:<10} {stock:<8} {status:<10} "
            f"{info['sale_start']:<22} {info['name_cn']}"
        )
        if info.get("name_jp"):
            lines.append(f"{'':<8} {'':<10} {'':<8} {'':<10} {'':<22} （日）{info['name_jp']}")
    return "\n".join(lines)
