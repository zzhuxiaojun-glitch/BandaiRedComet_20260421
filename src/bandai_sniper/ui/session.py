"""SnipeSession — GUI 和核心抢购逻辑之间的解耦层。

关键设计：
  - 抢购在**独立 thread** 里跑自己的 asyncio event loop；UI 在主线程跑 webview
  - 两者之间只有两种通信：
      Python Api → session.start_snipe(cfg)  # 单向触发
      session → log_queue → UI poll           # 单向读取
  - 状态机 State 用枚举，UI 根据 state 切换视图
  - 关键：UI 的任何阻塞或崩溃都**不影响** asyncio 事件循环里的抢购精度
"""
from __future__ import annotations
import asyncio
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from loguru import logger

from ..api import PayParams
from ..config import Config
from ..sniper import Sniper


class State(str, Enum):
    IDLE = "idle"
    PRECHECKING = "prechecking"
    WAITING = "waiting"       # 倒计时 / 预热 / 轮询中
    FIRING = "firing"
    SUCCESS = "success"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class LogEntry:
    ts: float
    level: str
    message: str


@dataclass
class Snapshot:
    """UI 拉一次就能渲染全视图的状态快照。"""
    state: State = State.IDLE
    phase_msg: str = ""           # 当前阶段给用户看的一句话
    target_ts: Optional[float] = None  # 开抢时刻 UNIX 秒，前端算倒计时
    pay_params: Optional[dict] = None   # 抢中的订单数据
    error: Optional[str] = None         # 失败原因
    member_id: Optional[int] = None     # precheck 结果
    product: Optional[dict] = None      # precheck 结果：nameCn/price/stock/saleStatus
    addresses: list[dict] = field(default_factory=list)
    pinned_address_id: Optional[str] = None


class SnipeSession:
    """一个会话对象对应"打开 GUI 到关闭"整个生命周期。
    内部 lock 保护 state / snapshot，log_queue 线程安全。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = Snapshot()
        self._log_queue: queue.Queue[LogEntry] = queue.Queue(maxsize=2000)
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._current_sniper: Optional[Sniper] = None
        # loguru sink，把日志送进 queue 供 UI 消费
        self._sink_id = logger.add(
            self._enqueue_log,
            level="INFO",
            format="{message}",
        )

    # ─── log handling ────────────────────────────
    def _enqueue_log(self, message) -> None:
        """loguru 调的 sink。message 是 loguru Record 对象（str() 后是格式化后的行）。"""
        record = message.record
        entry = LogEntry(
            ts=record["time"].timestamp(),
            level=record["level"].name,
            message=record["message"],
        )
        try:
            self._log_queue.put_nowait(entry)
        except queue.Full:
            # 丢弃最旧的一条，保证 queue 不爆
            try:
                self._log_queue.get_nowait()
                self._log_queue.put_nowait(entry)
            except queue.Empty:
                pass

    def drain_logs(self, max_items: int = 200) -> list[dict]:
        """UI 每 N ms 拉一次。返回已累计的日志 entry 列表，清空 queue。"""
        out: list[dict] = []
        while len(out) < max_items:
            try:
                e = self._log_queue.get_nowait()
            except queue.Empty:
                break
            out.append({"ts": e.ts, "level": e.level, "message": e.message})
        return out

    # ─── state handling ────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            s = self._snapshot
            return {
                "state": s.state.value,
                "phase_msg": s.phase_msg,
                "target_ts": s.target_ts,
                "pay_params": s.pay_params,
                "error": s.error,
                "member_id": s.member_id,
                "product": s.product,
                "addresses": list(s.addresses),
                "pinned_address_id": s.pinned_address_id,
            }

    def _update(self, **kw: Any) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self._snapshot, k, v)

    # ─── actions (被 Api 调) ────────────────────
    def start_snipe(self, cfg: Config) -> None:
        """在后台 thread 起 asyncio loop 跑 Sniper.run。"""
        if self._thread and self._thread.is_alive():
            raise RuntimeError("已有抢购正在进行")
        self._update(
            state=State.PRECHECKING,
            phase_msg="准备中...",
            error=None,
            pay_params=None,
        )

        def _run():
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._run_sniper(cfg))
            finally:
                loop.close()
                self._loop = None

        self._thread = threading.Thread(target=_run, name="sniper", daemon=True)
        self._thread.start()

    async def _run_sniper(self, cfg: Config) -> None:
        sniper = Sniper(cfg)
        self._current_sniper = sniper
        try:
            self._update(state=State.PRECHECKING, phase_msg="预检中")
            await sniper.precheck()
            # 预检通过，切到等待态。member_id / product / addresses 在 UI 更早
            # 通过 Api.precheck_only 单独取过了，这里不二次请求。
            self._update(
                state=State.WAITING,
                phase_msg="等待开抢",
                target_ts=cfg.snipe_time.timestamp(),
            )

            await sniper.countdown()
            self._update(state=State.FIRING, phase_msg="下单中")
            pay = await sniper.fire()
            self._update(
                state=State.SUCCESS,
                phase_msg="抢单成功",
                pay_params={
                    "order_id": pay.order_id,
                    "prepay_id": pay.prepay_id,
                    "timestamp": pay.timestamp,
                    "nonce_str": pay.nonce_str,
                    "package": pay.package,
                    "sign_type": pay.sign_type,
                    "pay_sign": pay.pay_sign,
                },
            )
        except Exception as e:
            logger.exception(f"会话异常: {e}")
            self._update(
                state=State.FAILED,
                phase_msg="抢单失败",
                error=str(e),
            )
        finally:
            self._current_sniper = None
            await sniper.aclose()

    def stop_snipe(self) -> None:
        """请求中止当前抢购。实现：取消 event loop 里的所有 task。"""
        if self._loop and self._loop.is_running():
            # 安全取消：loop.call_soon_threadsafe 发个取消指令
            def _cancel_all():
                for t in asyncio.all_tasks(self._loop):
                    t.cancel()
            try:
                self._loop.call_soon_threadsafe(_cancel_all)
            except Exception:
                pass
        self._update(state=State.STOPPED, phase_msg="已中止")

    def reset(self) -> None:
        """抢完或失败后点"返回"时清状态。"""
        if self._thread and self._thread.is_alive():
            raise RuntimeError("有抢购正在进行，先中止")
        self._update(
            state=State.IDLE,
            phase_msg="",
            target_ts=None,
            pay_params=None,
            error=None,
        )
