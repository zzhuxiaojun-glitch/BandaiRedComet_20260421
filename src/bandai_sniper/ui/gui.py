"""PyWebView 窗口入口 + Api 类。

Api 的所有 public 方法都会被 pywebview 自动暴露给前端 JS（通过 `window.pywebview.api`）。
每个方法返回的数据必须是可 JSON 序列化的（dict / list / primitive）。
抛异常时前端会 reject 对应的 Promise，可 try/catch。
"""
from __future__ import annotations
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from ..api import BandaiApi
from ..client import BandaiClient
from ..config import Config
from ..notify import push
from . import app_config
from .session import SnipeSession

WEB_DIR = Path(__file__).parent / "web"


class Api:
    """暴露给前端 JS 的方法集合。"""

    def __init__(self) -> None:
        self.session = SnipeSession()

    # ───────────── 表单页：预填 / 保存 ─────────────

    def load_saved(self) -> dict:
        """下次打开窗口时预填上次用过的字段。"""
        return app_config.load_state()

    def save_form(self, data: dict) -> dict:
        """用户每次改完表单都调一次，异常不影响 GUI。"""
        # 敏感字段默认不存
        scrubbed = {k: v for k, v in data.items() if k != "ck"}
        if data.get("remember_ck") and data.get("ck"):
            scrubbed["ck"] = data["ck"]
        try:
            app_config.save_state(scrubbed)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ───────────── 表单页：独立预检（UI 拉数据） ─────────────

    def precheck_only(self, cfg_dict: dict) -> dict:
        """表单页"先验证"按钮用。执行纯只读的 sync_timestamp / whoami /
        get_spu_detail / list_addresses，把结果打包返回给 UI 渲染。

        不走 SnipeSession —— 这是临时性的一次性调用。
        """
        ck = cfg_dict.get("ck", "")
        spu_id = cfg_dict.get("spu_id", "")
        if not ck:
            return {"ok": False, "error": "CK 未填写"}
        if not spu_id:
            return {"ok": False, "error": "SPU ID 未填写"}

        async def _do() -> dict:
            client = BandaiClient(ck=ck, timeout=8.0)
            try:
                api = BandaiApi(client)
                await api.sync_timestamp()
                perms = await api.whoami()
                mids = {
                    it.get("memberId")
                    for it in perms
                    if isinstance(it, dict) and it.get("memberId")
                }
                member_id = next(iter(mids), None)

                try:
                    detail = await api.get_spu_detail(spu_id)
                except Exception as e:
                    detail = {"error": str(e)}

                addrs = await api.list_addresses()
                return {
                    "ok": True,
                    "member_id": member_id,
                    "product": {
                        "id": detail.get("id"),
                        "nameCn": detail.get("nameCn"),
                        "nameJp": detail.get("nameJp") or detail.get("nameJa") or "",
                        "price": detail.get("price"),
                        "stock": detail.get("stock"),
                        "saleStatus": detail.get("saleStatus"),
                        "saleStartTime": detail.get("saleStartTime"),
                        "depositAmount": detail.get("depositAmount"),
                        "error": detail.get("error"),
                    },
                    "addresses": [
                        {
                            "id": str(a.id),
                            "receiver": a.receiver,
                            "phone": a.receiver_phone,
                            "summary": f"{a.province_name} {a.city_name} {a.district_name} {a.address}",
                        }
                        for a in addrs
                    ],
                }
            finally:
                await client.aclose()

        try:
            return asyncio.run(_do())
        except Exception as e:
            logger.exception("precheck_only 失败")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def list_skus(self, ck: str, spu_id: str) -> dict:
        """用户填了 SPU 后，拉一下 SKU 列表让他选规格。"""
        if not ck or not spu_id:
            return {"ok": False, "error": "需要 CK + SPU ID"}

        async def _do() -> dict:
            client = BandaiClient(ck=ck, timeout=8.0)
            try:
                api = BandaiApi(client)
                await api.sync_timestamp()
                sku_list = await api.get_sku_list(spu_id)
                return {
                    "ok": True,
                    "skus": [
                        {
                            "id": str(s.get("id")),
                            "name": s.get("nameCn"),
                            "price": s.get("pricePlusTaxRmb") or s.get("price"),
                            "stock": s.get("stock"),
                        }
                        for s in (sku_list or [])
                    ],
                }
            finally:
                await client.aclose()

        try:
            return asyncio.run(_do())
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ───────────── 抢购 ─────────────

    def start_snipe(self, cfg_dict: dict) -> dict:
        """开始抢购。把表单数据转 Config 后交给 session 后台跑。"""
        try:
            cfg = self._dict_to_config(cfg_dict)
        except Exception as e:
            return {"ok": False, "error": f"配置错: {e}"}
        try:
            self.session.start_snipe(cfg)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def stop_snipe(self) -> dict:
        self.session.stop_snipe()
        return {"ok": True}

    def reset(self) -> dict:
        try:
            self.session.reset()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ───────────── 状态 / 日志 ─────────────

    def get_snapshot(self) -> dict:
        """UI 定时拉（500ms 一次），拿到当前状态快照。"""
        return self.session.snapshot()

    def drain_logs(self) -> list[dict]:
        """UI 定时拉（200ms 一次），拿到累计日志。"""
        return self.session.drain_logs()

    # ───────────── 工具 ─────────────

    def open_wechat(self) -> dict:
        """Windows 协议打开微信。"""
        import subprocess
        try:
            if sys.platform == "win32":
                subprocess.Popen(["cmd", "/c", "start", "", "weixin://"], shell=False)
                return {"ok": True}
            return {"ok": False, "error": "仅 Windows 支持 weixin:// 协议"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_test_notify(self, provider: str, token: str) -> dict:
        """通知通道测试（Phase 2 功能前置），用户贴 token 后能立刻试发。"""
        from ..config import Notify

        if provider == "none" or not token:
            return {"ok": False, "error": "provider/token 未填"}
        cfg = Notify(enabled=True, provider=provider, token=token)

        async def _do():
            await push(cfg, "万代抢购器 · 测试推送", "通道连通")

        try:
            asyncio.run(_do())
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ───────────── 内部 ─────────────

    def _dict_to_config(self, d: dict) -> Config:
        """把前端 JSON 转成 Config pydantic 模型。"""
        tz = d.get("timezone") or "Asia/Shanghai"
        st_raw = d.get("snipe_time")
        if isinstance(st_raw, str):
            # 前端 datetime-local 格式：2026-05-10T20:00
            snipe_time = datetime.fromisoformat(st_raw).replace(tzinfo=ZoneInfo(tz))
        else:
            raise ValueError("snipe_time 未填")

        raw = {
            "ck": d["ck"],
            "timezone": tz,
            "snipe_time": snipe_time,
            "target": {
                "spu_id": str(d["spu_id"]),
                "sku_id": str(d["sku_id"]),
                "num": int(d.get("num", 1)),
                "address_id": str(d["address_id"]) if d.get("address_id") else None,
                "price_ceiling": float(d.get("price_ceiling", 99999)),
            },
            "strategy": {
                "pre_warmup_seconds": int(d.get("pre_warmup_seconds", 60)),
                "lead_ms": int(d.get("lead_ms", 5)),
                "max_retries": int(d.get("max_retries", 8)),
                "concurrency": int(d.get("concurrency", 3)),
                "retry_backoff_ms": int(d.get("retry_backoff_ms", 50)),
                "poll_stock": bool(d.get("poll_stock", True)),
                "poll_stock_interval_ms": int(d.get("poll_stock_interval_ms", 150)),
                "max_early_fire_ms": int(d.get("max_early_fire_ms", 2000)),
            },
            "notify": {
                "enabled": bool(d.get("notify_enabled", False)),
                "provider": d.get("notify_provider", "none"),
                "token": d.get("notify_token", ""),
            },
            "log": {
                "level": d.get("log_level", "INFO"),
                "dir": d.get("log_dir", "./logs"),
            },
        }
        return Config.model_validate(raw)


def launch() -> None:
    """命令行入口：`python -m bandai_sniper gui`。"""
    import webview

    api = Api()
    webview.create_window(
        title="万代抢购器",
        url=str((WEB_DIR / "index.html").resolve()),
        js_api=api,
        width=720,
        height=900,
        min_size=(640, 780),
        resizable=True,
    )
    # debug=True 在 dev 下方便看控制台
    webview.start(debug=("--debug" in sys.argv))
