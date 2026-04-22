"""Plan A 端到端冒烟测试。

递进验证链：
  1. sync_timestamp ── 无副作用，GET 空参。返回合法 JSON = 签名服务端认
  2. whoami         ── 验证 CK 有效，返回 memberId 应 == 796529
  3. get_spu_detail ── 带 URL 参数的加密，测商品查询链路
  4. confirm_order  ── dry-run 算价（不占库存）

任意一步挂就停，打印足够信息诊断。
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bandai_sniper.api import ApiError, BandaiApi  # noqa: E402
from bandai_sniper.client import BandaiClient  # noqa: E402


def load_env() -> dict:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


async def step(label: str, coro):
    print(f"\n━━━ {label} ━━━")
    try:
        result = await coro
        preview = json.dumps(result, ensure_ascii=False, default=str)
        if len(preview) > 500:
            preview = preview[:500] + f"... (+{len(preview)-500} chars)"
        print(f"✅ OK: {preview}")
        return result
    except ApiError as e:
        print(f"❌ ApiError code={e.code} msg={e.msg}")
        print(f"   raw={json.dumps(e.raw, ensure_ascii=False, default=str)[:400]}")
        raise
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
        raise


async def main() -> int:
    env = load_env()
    ck = env.get("BANDAI_CK", "")
    if not ck:
        print("BANDAI_CK 未在 .env 中配置")
        return 1
    print(f"CK head={ck[:20]}... tail=...{ck[-10:]}  (len={len(ck)})")

    client = BandaiClient(ck=ck, timeout=8.0)
    # 加入 UA 和微信 Referer，尽量伪装成小程序流量
    ua = env.get("BANDAI_UA")
    if ua:
        client._client.headers["User-Agent"] = ua
    client._client.headers["Referer"] = "https://servicewechat.com/wx1cb4557915b2b7cd/129/page-frame.html"
    client._client.headers["xweb_xhr"] = "1"

    try:
        api = BandaiApi(client)

        # 1 ── 无副作用，最安全
        server_ms = await step("1. sync_timestamp", api.sync_timestamp())

        # 2 ── 验证 CK
        me = await step("2. whoami", api.whoami())
        if isinstance(me, list) and me:
            mids = {item.get("memberId") for item in me if isinstance(item, dict)}
            print(f"   memberId(s) = {mids}")

        # 3 ── 带 URL 参数加密
        await step("3. get_spu_detail(6521)", api.get_spu_detail(6521))

        # 4 ── dry-run 算价（无 address）
        draft = await step(
            "4. confirm_order (dry-run, 无地址)",
            api.confirm_order([{"skuId": "9266", "num": "1", "spuId": "6521"}]),
        )
        print(f"   orderAmount = {draft.order_amount}")

        print("\n═══════════ 全部通过 ═══════════")
        print("Plan A 签名 / 加密 / 地址-less 下单链路 在真实网络上工作。")
        print("下一步：带地址 confirm_order → createOrder（真占库存），需你手工挑冷门商品再做。")
        return 0
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
