"""端到端真实下单冒烟：走到拉支付参数为止（不付款）。

会发生什么：
  - 服务端真的创建一笔订单，占用 1 件库存
  - 订单状态 = "待支付"，15 min 内不支付自动取消释放
  - 拿到 prepayId / paySign / 订单 id 后脚本停止，不调 wx.requestPayment

商品选择：沿用 HAR 里已验证的 HGUC 里歇尔（现货 PB，142 元起步只付定金 20）。
地址：用账户默认地址。
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bandai_sniper.api import ApiError, BandaiApi, Address  # noqa: E402
from bandai_sniper.client import BandaiClient  # noqa: E402

TARGET_SPU = "6521"
TARGET_SKU = "9266"
TARGET_NAME = "预售 PB 万代模型 HGUC 1/144 里歇尔"


def load_env() -> dict:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


async def main() -> int:
    env = load_env()
    client = BandaiClient(ck=env["BANDAI_CK"], timeout=8.0)
    if env.get("BANDAI_UA"):
        client._client.headers["User-Agent"] = env["BANDAI_UA"]
    client._client.headers["Referer"] = "https://servicewechat.com/wx1cb4557915b2b7cd/129/page-frame.html"
    client._client.headers["xweb_xhr"] = "1"

    api = BandaiApi(client)
    try:
        # 1. 对时
        print("━━━ 1. 对时 ━━━")
        await api.sync_timestamp()
        print("✅ 时间同步")

        # 2. 库存 / 限购 check
        print("\n━━━ 2. 商品状态 ━━━")
        detail = await api.get_spu_detail(TARGET_SPU)
        stock = detail.get("stock", 0)
        price = detail.get("price")
        sale_status = detail.get("saleStatus")
        print(f"✅ {TARGET_NAME}  stock={stock}  price={price}  saleStatus={sale_status}")
        if stock < 1 or sale_status != 0:
            print(f"❌ 商品状态异常，中止")
            return 1

        # 3. 地址
        print("\n━━━ 3. 默认地址 ━━━")
        addrs = await api.list_addresses()
        if not addrs:
            print("❌ 账户没有地址，先去小程序加一个")
            return 1
        addr = addrs[0]  # 用第一条
        print(f"✅ {addr.receiver} / {addr.receiver_phone}")
        print(f"   {addr.province_name} {addr.city_name} {addr.district_name} {addr.address}")

        # 4. confirmOrder 带地址（算完整 orderAmount 含运费）
        print("\n━━━ 4. confirmOrder 带地址 ━━━")
        sku_list = [{"skuId": TARGET_SKU, "num": "1", "spuId": TARGET_SPU}]
        draft = await api.confirm_order(sku_list, address=addr)
        print(f"✅ orderAmount={draft.order_amount}  freight={draft.raw.get('freight')}")
        print(f"   depositAmount={draft.raw.get('depositAmount')}  balanceAmount={draft.raw.get('balanceAmount')}")
        print(f"   goodsPayAmount={draft.raw.get('goodsPayAmount')}")

        # 5. createOrder 真占库存！
        print("\n━━━ 5. createOrder（真占库存）━━━")
        print("   ⚠️  下一秒会创建未支付订单，15 min 后自动释放")
        pay = await api.create_order(draft, addr)
        print(f"✅ 订单创建成功")
        print(f"   order_id   = {pay.order_id}")
        print(f"   prepay_id  = {pay.prepay_id}")
        print(f"   timestamp  = {pay.timestamp}")
        print(f"   nonce_str  = {pay.nonce_str}")
        print(f"   package    = {pay.package}")
        print(f"   sign_type  = {pay.sign_type}")
        print(f"   pay_sign   = {pay.pay_sign[:40]}...{pay.pay_sign[-20:]} ({len(pay.pay_sign)} chars)")

        # 6. 查订单详情确认
        print("\n━━━ 6. 查订单详情 ━━━")
        od = await api.get_order_detail(pay.order_id)
        print(f"✅ orderNo={od.get('orderNo')}  status={od.get('orderStatus')}({od.get('orderStatusName')})")
        print(f"   autoCancel={od.get('orderAutoCancelTime')}  payAmount={od.get('payAmount')}")

        print("\n═══════════ Plan A 端到端真实下单全链路 PASS ═══════════")
        print(f"未支付订单 id={pay.order_id} / orderNo={od.get('orderNo')} —— 不付即取消")
        return 0

    except ApiError as e:
        print(f"\n❌ ApiError code={e.code} msg={e.msg}")
        print(f"   raw={json.dumps(e.raw, ensure_ascii=False)[:400]}")
        return 2
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
