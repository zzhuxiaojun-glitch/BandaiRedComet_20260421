"""从 HAR 里列出所有商品，一行一个，方便挑选。

用法：
    PYTHONPATH=src .venv/bin/python tools/verify/list_products_from_har.py <har-path>
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bandai_sniper.har_utils import (  # noqa: E402
    extract_products_from_har,
    format_products_table,
)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: list_products_from_har.py <har-file>")
        return 1
    try:
        products = extract_products_from_har(sys.argv[1])
    except FileNotFoundError as e:
        print(e)
        return 1

    if not products:
        print("⚠️ 没在 HAR 里找到商品请求。")
        print("   确认抓包时至少打开了一个商品详情页（触发 /spu/v2/detail/new）。")
        return 1

    print(f"\n在 HAR 里发现 {len(products)} 个商品：\n")
    print(format_products_table(products))
    print("\n把心仪的 SPU ID 填进 GUI 的「商品」卡片，开抢。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
