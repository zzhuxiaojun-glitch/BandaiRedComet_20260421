"""从 HAR 里列出所有商品（SPU/SKU），一行一个，方便朋友挑选。

用法：
    PYTHONPATH=src .venv/bin/python tools/verify/list_products_from_har.py <path-to-har>
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bandai_sniper.crypto import aes_decrypt  # noqa: E402


def _decrypt_url_param(enc: str):
    for c in (enc, unquote(enc), unquote(unquote(enc))):
        try:
            return aes_decrypt(c)
        except Exception:
            pass
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: list_products_from_har.py <har-file>")
        return 1
    har_path = Path(sys.argv[1])
    if not har_path.exists():
        print(f"找不到 HAR 文件: {har_path}")
        return 1

    har = json.loads(har_path.read_text(encoding="utf-8"))
    seen_spus: dict[str, dict] = {}

    for entry in har["log"]["entries"]:
        url = entry["request"]["url"]
        if "bandainamcoshanghai.com/api/" not in url:
            continue

        # 从 spu 详情 / SKU 详情的 req 里抽 id
        spu_id = None
        if "/spu/v2/detail/new" in url or "/spu/sku/detail" in url:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            enc = qs.get("encryptionUrlParams", [None])[0]
            if enc:
                req = _decrypt_url_param(enc)
                if isinstance(req, dict):
                    spu_id = str(req.get("id") or req.get("spuId") or "")

        if not spu_id:
            continue

        # 从 resp 里把商品名 / 价格 / 库存 挑出来
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
        if isinstance(data, dict):
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
            seen_spus.setdefault(spu_id, info)
        elif isinstance(data, list):
            # spu/sku/detail 返回 list of sku
            for sku in data:
                if not isinstance(sku, dict):
                    continue
                name = sku.get("nameCn") or ""
                # sku 里没有 spu 层的日文名，先占位
                seen_spus.setdefault(spu_id, {
                    "spu_id": spu_id,
                    "name_cn": name,
                    "name_jp": "",
                    "price": sku.get("pricePlusTaxRmb"),
                    "stock": sku.get("stock"),
                    "status": None,
                    "sale_start": "",
                    "deposit": None,
                })

    if not seen_spus:
        print("⚠️ 没在 HAR 里找到商品请求。确认抓包时打开了至少一个商品详情页。")
        return 1

    print(f"\n在 HAR 里发现 {len(seen_spus)} 个商品：\n")
    print(f"{'SPU ID':<8} {'价格':<10} {'库存':<8} {'状态':<10} {'开售时间':<22} 商品名")
    print("─" * 100)
    for info in sorted(seen_spus.values(), key=lambda x: x["spu_id"]):
        price = f"¥{info['price']}" if info['price'] is not None else "-"
        stock = str(info['stock']) if info['stock'] is not None else "-"
        status_map = {0: "可售", 1: "未开售", None: "-"}
        status = status_map.get(info["status"], str(info["status"]))
        print(
            f"{info['spu_id']:<8} {price:<10} {stock:<8} {status:<10} "
            f"{info['sale_start']:<22} {info['name_cn']}"
        )
        if info["name_jp"]:
            print(f"{'':<8} {'':<10} {'':<8} {'':<10} {'':<22} （日）{info['name_jp']}")

    print()
    print("把心仪的 SPU ID 填进 GUI 的「商品」卡片，开抢。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
