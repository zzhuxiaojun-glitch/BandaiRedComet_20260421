"""诊断脚本：查看 HAR 里都抓到了什么，帮助确认抓包完整性。

用法:
    python inspect_har.py bandai_capture.har
"""

import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


EXPECTED_PATTERNS = {
    "用户信息 / CK 校验": ["/user", "/profile", "/me", "/auth"],
    "商品详情": ["/product/detail", "/goods/detail", "/sku"],
    "加购物车": ["/cart/add", "/cart"],
    "确认订单": ["/order/confirm", "/checkout", "/order/prepare"],
    "创建订单": ["/order/create", "/order/submit", "/order"],
    "地址": ["/address"],
    "库存": ["/stock", "/inventory"],
}


def match(path: str, patterns: list[str]) -> bool:
    return any(p in path for p in patterns)


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python inspect_har.py <har_file>")
        return 1

    har_path = Path(sys.argv[1])
    if not har_path.exists():
        print(f"找不到: {har_path}")
        return 1

    with har_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("log", {}).get("entries", [])
    print(f"\n📊 {har_path.name} · 共 {len(entries)} 条请求\n")

    # 域名统计
    host_counter: Counter = Counter()
    for e in entries:
        try:
            host_counter[urlparse(e["request"]["url"]).netloc] += 1
        except Exception:
            pass

    print("── 域名分布 ──")
    for host, cnt in host_counter.most_common(10):
        print(f"  {cnt:4d}  {host}")

    # 按路径分组
    print("\n── URL 路径（去参数） ──")
    path_counter: Counter = Counter()
    for e in entries:
        try:
            u = urlparse(e["request"]["url"])
            path_counter[f"{e['request']['method']:5s} {u.path}"] += 1
        except Exception:
            pass

    for p, cnt in sorted(path_counter.items()):
        print(f"  {cnt:3d}× {p}")

    # 预期清单检查
    print("\n── 预期接口检查 ──")
    all_paths = [urlparse(e["request"]["url"]).path for e in entries]
    complete = True
    for name, patterns in EXPECTED_PATTERNS.items():
        hits = [p for p in all_paths if match(p, patterns)]
        mark = "✅" if hits else "❌"
        if not hits:
            complete = False
        uniq = sorted(set(hits))[:3]
        print(f"  {mark} {name:20s} {'命中 ' + str(uniq) if hits else '未抓到，建议重抓'}")

    # 响应码健康度
    print("\n── 响应码分布 ──")
    status_counter = Counter(e["response"]["status"] for e in entries)
    for code, cnt in sorted(status_counter.items()):
        mark = "✅" if 200 <= code < 300 else "⚠️ "
        print(f"  {mark} {code}: {cnt}")

    print()
    if complete:
        print("🎉 看起来抓得挺全。下一步跑 sanitize_har.py 脱敏。")
    else:
        print("⚠️  有些关键接口没抓到，检查有没有漏点操作。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
