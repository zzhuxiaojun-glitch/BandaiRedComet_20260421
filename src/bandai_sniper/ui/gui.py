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

                # 顺手 upsert 商品快照（_safe 吞错）
                if isinstance(detail, dict) and detail.get("id"):
                    from .. import db
                    db.upsert_product(
                        spu_id=str(detail.get("id")),
                        name_cn=detail.get("nameCn"),
                        name_jp=detail.get("nameJp") or detail.get("nameJa"),
                        price=detail.get("price"),
                        category_id=detail.get("categoryId"),
                        deposit_amount=detail.get("depositAmount"),
                        source="precheck",
                        raw={k: detail.get(k) for k in (
                            "id", "nameCn", "price", "stock", "saleStatus",
                            "saleStartTime", "saleEndTime", "depositAmount",
                            "categoryId", "spuType",
                        )},
                    )

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

    def search_products(self, ck: str, keyword: str, page_num: int = 1) -> dict:
        """关键词搜索商品（GUI "🔍 搜索" 按钮）。

        直接调万代的 spu/query 接口（参数 searchText），实时返回匹配商品。
        无本地缓存。返回的 product 字段格式与 har_utils.extract_products
        对齐，前端可复用 renderHarProducts 渲染。
        """
        if not ck:
            return {"ok": False, "error": "CK 未填写"}
        kw = (keyword or "").strip()
        if not kw:
            return {"ok": False, "error": "请输入关键词"}

        async def _do() -> dict:
            client = BandaiClient(ck=ck, timeout=8.0)
            try:
                api = BandaiApi(client)
                await api.sync_timestamp()
                result = await api.search_products(kw, page_num=page_num, page_size=30)
                items = result.get("list", []) if isinstance(result, dict) else []
                products = [
                    {
                        "spu_id": str(item.get("id")),
                        "name_cn": item.get("nameCn", ""),
                        "name_jp": item.get("nameJp") or item.get("nameJa") or "",
                        "price": item.get("price"),
                        "stock": None,  # 列表接口不返回库存，要点进详情才有
                        "status": None,  # 同上 saleStatus 也不在列表里
                        "sale_start": item.get("saleStartTime", ""),
                        "deposit": None,
                    }
                    for item in items
                ]
                total = result.get("total", 0) if isinstance(result, dict) else 0

                # 写 DB：搜索历史 + 商品 upsert（_safe 装饰器吞错，不影响响应）
                from .. import db
                db.add_search_history(kw, total)
                for item in items:
                    db.upsert_product(
                        spu_id=str(item.get("id", "")),
                        name_cn=item.get("nameCn"),
                        name_jp=item.get("nameJp") or item.get("nameJa"),
                        price=item.get("price"),
                        category_id=item.get("categoryId"),
                        source="search",
                        raw={k: item.get(k) for k in (
                            "id", "nameCn", "spuType", "categoryId", "price",
                            "saleStartTime", "saleEndTime", "saleTag",
                        )},
                    )

                return {
                    "ok": True,
                    "keyword": kw,
                    "page_num": page_num,
                    "total": total,
                    "products": products,
                }
            finally:
                await client.aclose()

        try:
            return asyncio.run(_do())
        except Exception as e:
            logger.exception("search_products 失败")
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

    def verify_ck(self, ck: str) -> dict:
        """快速验证 CK 有效性（GUI 启动时自动调 + 用户手动改 CK 后调）。

        策略：调最便宜的两个接口 sync_timestamp + whoami，能拿到
        memberId 就算通过。失败则返回结构化错误（前端走 classifyError）。
        """
        if not ck or not ck.strip():
            return {"ok": False, "error": "CK 为空"}

        async def _do() -> dict:
            client = BandaiClient(ck=ck.strip(), timeout=6.0)
            try:
                api = BandaiApi(client)
                await api.sync_timestamp()
                perms = await api.whoami()
                mids = {
                    it.get("memberId")
                    for it in perms
                    if isinstance(it, dict) and it.get("memberId")
                }
                return {"ok": True, "member_id": next(iter(mids), None)}
            finally:
                await client.aclose()

        try:
            return asyncio.run(_do())
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def import_ck_from_har(self) -> dict:
        """弹文件选择器让用户选 HAR，从中抽出最新 api-access-token 返回。

        给 GUI 账号卡片的"📁 从 HAR 导入 CK"链接用。前端拿到后填进
        ck textarea + 立即调 verify_ck 验证。
        """
        import webview

        from ..har_utils import extract_ck_from_har

        wins = webview.windows
        if not wins:
            return {"ok": False, "error": "窗口还没就绪"}
        paths = wins[0].create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("HAR Files (*.har)", "All Files (*.*)"),
            allow_multiple=False,
        )
        if not paths:
            return {"ok": False, "error": "已取消"}
        har_path = paths[0] if isinstance(paths, (list, tuple)) else paths
        try:
            ck = extract_ck_from_har(har_path)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if not ck:
            return {
                "ok": False,
                "error": "HAR 里没找到有效的 api-access-token。"
                         "确认抓包时打开过万代小程序，且不是脱敏后的 HAR。",
            }
        return {"ok": True, "ck": ck, "har_path": str(har_path)}

    # ───────────── 历史查询（DB 读路径）─────────────

    def list_orders(self, limit: int = 50) -> dict:
        """抢购订单历史，按时间倒序。"""
        from .. import db
        rows = db.list_orders(limit=limit) or []
        return {"ok": True, "orders": rows}

    def list_search_history(self, limit: int = 30) -> dict:
        """搜索关键词历史（去重 + 按最近搜索时间倒序）。"""
        from .. import db
        rows = db.list_search_history(limit=limit, unique=True) or []
        return {"ok": True, "items": rows}

    def list_seen_products(self, limit: int = 100) -> dict:
        """见过的商品快照列表（搜索 / 预检过的）。"""
        from .. import db
        rows = db.list_products(limit=limit) or []
        return {"ok": True, "products": rows}

    def clear_search_history(self) -> dict:
        from .. import db
        n = db.clear_search_history()
        return {"ok": True, "cleared": n or 0}

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

    def pick_har_and_list(self) -> dict:
        """弹原生文件选择器让用户选一个 HAR，解析后返回商品列表。
        给 GUI「从 HAR 选商品」按钮用。
        """
        import webview

        from ..har_utils import extract_products_from_har

        wins = webview.windows
        if not wins:
            return {"ok": False, "error": "窗口还没就绪"}
        paths = wins[0].create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("HAR Files (*.har)", "All Files (*.*)"),
            allow_multiple=False,
        )
        if not paths:
            return {"ok": False, "error": "已取消"}
        har_path = paths[0] if isinstance(paths, (list, tuple)) else paths
        try:
            products = extract_products_from_har(har_path)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if not products:
            return {
                "ok": False,
                "error": "HAR 里没商品。确认抓包时打开过至少一个商品详情页。",
            }
        return {"ok": True, "har_path": str(har_path), "products": products}

    # ───────────── 内部 ─────────────

    def _dict_to_config(self, d: dict) -> Config:
        """把前端 JSON 转成 Config pydantic 模型。

        所有 Optional 字段做 None → "" / 默认值的标准化，
        防止前端送进来的 null 触发 pydantic NoneType 报错。
        """
        from pydantic import ValidationError

        tz = d.get("timezone") or "Asia/Shanghai"
        st_raw = d.get("snipe_time")
        if not st_raw or not isinstance(st_raw, str):
            raise ValueError("开抢时间未填或格式不对")
        try:
            # 兼容 datetime-local 输出 'YYYY-MM-DDTHH:MM' 不带秒的情况：
            # - Python 3.11+ fromisoformat 支持
            # - Python 3.10 之前只支持完整 'YYYY-MM-DDTHH:MM:SS'
            # 统一在解析前补全 ":00"，跨 Python 版本都能跑（v1.1 朋友 fork 的修）
            normalized = st_raw.strip()
            if len(normalized) == 16 and normalized[13] == ":":
                normalized = normalized + ":00"
            snipe_time = datetime.fromisoformat(normalized).replace(tzinfo=ZoneInfo(tz))
        except Exception:
            raise ValueError(f"开抢时间格式不对: {st_raw!r}")

        # 全部字段防御性归一：None → 默认值 / 空字符串
        raw = {
            "ck": (d.get("ck") or "").strip(),
            "timezone": tz,
            "snipe_time": snipe_time,
            "target": {
                "spu_id": str(d.get("spu_id") or "").strip(),
                "sku_id": str(d.get("sku_id") or "").strip(),
                "num": int(d.get("num") or 1),
                "address_id": str(d["address_id"]).strip() if d.get("address_id") else None,
                "price_ceiling": float(d.get("price_ceiling") or 99999),
            },
            "strategy": {
                "pre_warmup_seconds": int(d.get("pre_warmup_seconds") or 60),
                "lead_ms": int(d.get("lead_ms") or 5),
                "max_retries": int(d.get("max_retries") or 8),
                "concurrency": int(d.get("concurrency") or 3),
                "retry_backoff_ms": int(d.get("retry_backoff_ms") or 50),
                "poll_stock": bool(d.get("poll_stock", True)),
                "poll_stock_interval_ms": int(d.get("poll_stock_interval_ms") or 150),
                "max_early_fire_ms": int(d.get("max_early_fire_ms") or 2000),
            },
            "notify": {
                "enabled": bool(d.get("notify_enabled", False)),
                "provider": (d.get("notify_provider") or "none"),
                "token": (d.get("notify_token") or ""),  # 关键：防 None
            },
            "log": {
                "level": d.get("log_level") or "INFO",
                "dir": d.get("log_dir") or "./logs",
            },
        }
        try:
            return Config.model_validate(raw)
        except ValidationError as ve:
            raise ValueError(_humanize_validation_error(ve))


# 字段路径 → 中文名字 映射
_FIELD_LABEL = {
    "ck": "CK",
    "snipe_time": "开抢时间",
    "target.spu_id": "SPU ID",
    "target.sku_id": "SKU",
    "target.num": "数量",
    "target.address_id": "地址",
    "target.price_ceiling": "价格护栏",
    "strategy.pre_warmup_seconds": "提前对时秒数",
    "strategy.lead_ms": "提前 fire 毫秒",
    "strategy.max_retries": "最大重试",
    "strategy.concurrency": "并发数",
    "notify.token": "通知 token",
    "notify.provider": "通知通道",
}


def _humanize_validation_error(err) -> str:
    """pydantic ValidationError → 中文人话清单。"""
    lines = []
    for e in err.errors():
        loc = ".".join(str(x) for x in e.get("loc", []))
        label = _FIELD_LABEL.get(loc, loc)
        msg = e.get("msg", "")
        # 常见 message 翻译
        m_lower = msg.lower()
        if "should be a valid string" in m_lower:
            human = "应为字符串"
        elif "should be a valid integer" in m_lower:
            human = "应为整数"
        elif "should be a valid number" in m_lower:
            human = "应为数字"
        elif "should be a valid datetime" in m_lower:
            human = "时间格式不对"
        elif "field required" in m_lower or "missing" in m_lower:
            human = "未填"
        elif "ck 未填写" in msg or "PASTE_" in msg:
            human = "CK 未填写或仍是占位符"
        else:
            human = msg
        lines.append(f"  • {label}: {human}")
    return "配置有误：\n" + "\n".join(lines)


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
