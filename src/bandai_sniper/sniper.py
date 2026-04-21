import asyncio
import time
from datetime import datetime

from loguru import logger

from .api import ApiError, BandaiApi, Order
from .client import BandaiClient
from .config import Config
from .notify import push
from .timer import sync_ntp_offset, to_timestamp, wait_until


class Sniper:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = BandaiClient(ck=cfg.ck)
        self.api = BandaiApi(self.client)

    async def aclose(self) -> None:
        await self.client.aclose()

    # ─── 阶段 1：预检 ────────────────────────────
    async def precheck(self) -> None:
        logger.info("预检: 验证 CK 有效性")
        try:
            who = await self.api.whoami()
            logger.info(f"预检通过: 用户信息 {who}")
        except Exception as e:
            logger.error(f"CK 无效或 whoami 接口失败: {e}")
            raise

        logger.info(f"预检: 商品可达性 sku={self.cfg.target.sku_id}")
        try:
            await self.api.get_product(self.cfg.target.sku_id)
        except ApiError as e:
            logger.warning(f"商品查询返回业务错误 code={e.code} msg={e.msg}（未开售时常见，继续）")
        except Exception as e:
            logger.error(f"商品查询异常: {e}")
            raise

    # ─── 阶段 2：倒计时 ──────────────────────────
    async def countdown(self) -> None:
        offset = sync_ntp_offset()
        target_ts = to_timestamp(self.cfg.snipe_time, self.cfg.timezone)
        now = time.time()
        wait_s = target_ts - now - offset
        logger.info(
            f"开抢时刻: {self.cfg.snipe_time} · 还有 {wait_s:.1f}s · NTP 偏差 {offset*1000:.1f}ms"
        )
        if wait_s > self.cfg.strategy.pre_warmup_seconds:
            sleep_until = target_ts - self.cfg.strategy.pre_warmup_seconds
            logger.info(f"先睡到预热期 (T-{self.cfg.strategy.pre_warmup_seconds}s)")
            await wait_until(sleep_until, offset=offset)
            logger.info("进入预热期")
        await wait_until(target_ts, offset=offset, lead_ms=5)

    # ─── 阶段 3：开火 ───────────────────────────
    async def _attempt(self, idx: int) -> Order:
        t = self.cfg.target
        logger.info(f"[#{idx}] 触发下单流程")
        # 是否需要 add_to_cart 取决于抓包；若抓包发现可直接 prepare_order，把下行注释掉。
        # await self.api.add_to_cart(t.sku_id, t.quantity)
        draft = await self.api.prepare_order(t.sku_id, t.quantity, t.address_id)
        if draft.total_price > t.price_ceiling:
            raise ApiError("PRICE_GUARD", f"结算价 {draft.total_price} 超过护栏 {t.price_ceiling}")
        order = await self.api.create_order(draft, t.sku_id, t.quantity, t.address_id)
        return order

    async def fire(self) -> Order:
        strat = self.cfg.strategy
        stop = asyncio.Event()
        winner: list[Order] = []
        errors: list[Exception] = []

        async def worker(i: int):
            for attempt in range(strat.max_retries):
                if stop.is_set():
                    return
                try:
                    order = await self._attempt(i * 100 + attempt)
                    winner.append(order)
                    stop.set()
                    return
                except ApiError as e:
                    errors.append(e)
                    if e.code not in strat.retryable_codes:
                        logger.warning(f"[worker#{i}] 业务错误 code={e.code} 不可重试，放弃")
                        return
                    logger.info(f"[worker#{i}] 可重试 code={e.code}，{strat.retry_backoff_ms}ms 后重试")
                    await asyncio.sleep(strat.retry_backoff_ms / 1000)
                except Exception as e:
                    errors.append(e)
                    logger.info(f"[worker#{i}] 网络异常重试: {e}")
                    await asyncio.sleep(strat.retry_backoff_ms / 1000)

        t0 = time.monotonic()
        await asyncio.gather(*(worker(i) for i in range(strat.concurrency)))
        dt = (time.monotonic() - t0) * 1000
        if winner:
            logger.success(f"🎉 下单成功 · 耗时 {dt:.0f}ms · 订单号 {winner[0].order_no}")
            return winner[0]
        raise RuntimeError(f"全部重试失败 · 最后错误: {errors[-1] if errors else '无'}")

    # ─── 编排 ───────────────────────────────────
    async def run(self) -> None:
        try:
            await self.precheck()
            await self.countdown()
            order = await self.fire()
            await push(
                self.cfg.notify,
                title="万代抢单成功",
                content=f"订单号 {order.order_no}，速去微信付款",
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
