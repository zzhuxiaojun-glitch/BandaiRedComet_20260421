import asyncio
import time

from loguru import logger

from .api import Address, ApiError, BandaiApi, OrderDraft, PayParams
from .client import BandaiClient
from .config import Config
from .notify import push
from .timer import sync_ntp_offset, to_timestamp, wait_until


class Sniper:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = BandaiClient(ck=cfg.ck)
        self.api = BandaiApi(self.client)
        self._address: Address | None = None

    async def aclose(self) -> None:
        await self.client.aclose()

    # ─── 阶段 1：预检 ────────────────────────────
    async def precheck(self) -> None:
        logger.info("预检 1/4: 服务器对时")
        await self.api.sync_timestamp()

        logger.info("预检 2/4: CK 有效性")
        perms = await self.api.whoami()
        mids = {item.get("memberId") for item in perms if isinstance(item, dict)}
        logger.info(f"✅ CK 有效, memberId={mids}")

        logger.info(f"预检 3/4: 商品 spuId={self.cfg.target.spu_id}")
        try:
            detail = await self.api.get_spu_detail(self.cfg.target.spu_id)
            logger.info(
                f"✅ 商品「{detail.get('nameCn')}」"
                f" price={detail.get('price')} stock={detail.get('stock')}"
                f" saleStatus={detail.get('saleStatus')}"
                f" saleStartTime={detail.get('saleStartTime')}"
            )
        except ApiError as e:
            logger.warning(f"⚠️  商品查询业务错误 code={e.code} msg={e.msg}（未开售时常见，继续）")

        logger.info("预检 4/4: 地址")
        addrs = await self.api.list_addresses()
        if not addrs:
            raise RuntimeError("账户没有收货地址，先去小程序添加一个")
        if self.cfg.target.address_id:
            self._address = next(
                (a for a in addrs if str(a.id) == self.cfg.target.address_id), None
            )
            if self._address is None:
                raise RuntimeError(
                    f"配置的 address_id={self.cfg.target.address_id} 在地址列表里找不到；"
                    f"可用 id={[a.id for a in addrs]}"
                )
        else:
            self._address = addrs[0]
        logger.info(
            f"✅ 地址 id={self._address.id} {self._address.receiver}/"
            f"{self._address.receiver_phone} {self._address.address}"
        )

    # ─── 阶段 2：倒计时 ──────────────────────────
    async def countdown(self) -> None:
        strat = self.cfg.strategy
        ntp_offset = sync_ntp_offset()
        target_ts = to_timestamp(self.cfg.snipe_time, self.cfg.timezone)
        wait_s = target_ts - time.time() - ntp_offset
        logger.info(
            f"开抢时刻: {self.cfg.snipe_time} · 还有 {wait_s:.1f}s · "
            f"NTP 偏差 {ntp_offset*1000:.1f}ms"
        )

        if wait_s <= 0:
            logger.warning("开抢时刻已过，直接进入开火阶段")
            return

        # 先睡到预热窗口
        if wait_s > strat.pre_warmup_seconds:
            warmup_ts = target_ts - strat.pre_warmup_seconds
            logger.info(f"睡到预热窗口 T-{strat.pre_warmup_seconds}s")
            await wait_until(warmup_ts, offset=ntp_offset)

        # 预热：再拉一次服务器时间，比 NTP 更贴近对端
        logger.info("预热：刷新服务器时间 + keep-alive")
        await self.api.sync_timestamp()

        # 精确等到开抢时刻（提前 lead_ms 毫秒醒来）
        await wait_until(target_ts, offset=ntp_offset, lead_ms=strat.lead_ms)

    # ─── 阶段 3：开火 ───────────────────────────
    async def _attempt(self, idx: int) -> PayParams:
        assert self._address is not None, "precheck 没跑，地址没准备好"
        t = self.cfg.target
        sku_list = [{"skuId": t.sku_id, "num": str(t.num), "spuId": t.spu_id}]

        logger.info(f"[#{idx}] confirmOrder")
        draft: OrderDraft = await self.api.confirm_order(sku_list, address=self._address)
        logger.info(
            f"[#{idx}] draft orderAmount={draft.order_amount} "
            f"freight={draft.raw.get('freight')} deposit={draft.raw.get('depositAmount')}"
        )

        if draft.order_amount > t.price_ceiling:
            raise ApiError(
                "PRICE_GUARD",
                f"结算价 {draft.order_amount} 超过护栏 {t.price_ceiling}",
            )

        logger.info(f"[#{idx}] createOrder")
        pay = await self.api.create_order(draft, self._address)
        return pay

    async def fire(self) -> PayParams:
        strat = self.cfg.strategy
        stop = asyncio.Event()
        winner: list[PayParams] = []
        errors: list[Exception] = []

        async def worker(i: int):
            for attempt in range(strat.max_retries):
                if stop.is_set():
                    return
                idx = i * 100 + attempt
                try:
                    pay = await self._attempt(idx)
                    winner.append(pay)
                    stop.set()
                    return
                except ApiError as e:
                    errors.append(e)
                    if str(e.code) not in strat.retryable_codes:
                        logger.warning(
                            f"[worker#{i}] 业务错误 code={e.code} msg={e.msg} 不可重试"
                        )
                        return
                    logger.info(
                        f"[worker#{i}] 可重试 code={e.code} msg={e.msg}, "
                        f"{strat.retry_backoff_ms}ms 后重试"
                    )
                    await asyncio.sleep(strat.retry_backoff_ms / 1000)
                except Exception as e:
                    errors.append(e)
                    logger.info(f"[worker#{i}] 网络/未知异常: {e!r}")
                    await asyncio.sleep(strat.retry_backoff_ms / 1000)

        t0 = time.monotonic()
        await asyncio.gather(*(worker(i) for i in range(strat.concurrency)))
        dt_ms = (time.monotonic() - t0) * 1000

        if winner:
            p = winner[0]
            logger.success(
                f"🎉 抢单成功 · 耗时 {dt_ms:.0f}ms · "
                f"order_id={p.order_id} prepay_id={p.prepay_id}"
            )
            return p
        raise RuntimeError(
            f"全部 worker 重试失败 · 共 {len(errors)} 次错误 · 最后: {errors[-1] if errors else '?'}"
        )

    # ─── 编排 ───────────────────────────────────
    async def run(self) -> None:
        try:
            await self.precheck()
            await self.countdown()
            pay = await self.fire()
            await push(
                self.cfg.notify,
                title="万代抢单成功",
                content=(
                    f"订单 id={pay.order_id}\n"
                    f"prepay_id={pay.prepay_id}\n"
                    f"速去微信付款（15 分钟内不付自动取消）"
                ),
            )
        except Exception as e:
            logger.exception(f"抢单失败: {e}")
            await push(
                self.cfg.notify,
                title="万代抢单失败",
                content=str(e)[:200],
            )
            raise
        finally:
            await self.aclose()
