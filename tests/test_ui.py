"""GUI 层单元测试 —— 不启动真 webview，只测 Python 逻辑。"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone

import pytest
from loguru import logger

from bandai_sniper.ui.session import LogEntry, SnipeSession, State
from bandai_sniper.ui.gui import Api


# ═══════════════════════════════════════════════════════════════
# SnipeSession
# ═══════════════════════════════════════════════════════════════

def test_session_initial_snapshot_is_idle():
    s = SnipeSession()
    snap = s.snapshot()
    assert snap["state"] == "idle"
    assert snap["pay_params"] is None
    assert snap["error"] is None
    assert snap["addresses"] == []


def test_session_drain_logs_empty():
    s = SnipeSession()
    assert s.drain_logs() == []


def test_session_captures_loguru_logs():
    s = SnipeSession()
    logger.info("hello from test")
    logs = s.drain_logs()
    # 可能会捕到其他 logger 调用，但至少包含我们的消息
    assert any("hello from test" in l["message"] for l in logs)
    # 每个 entry 有标准字段
    for l in logs:
        assert set(l.keys()) >= {"ts", "level", "message"}


def test_session_log_queue_bounded():
    """log_queue 满了以后，新日志应替换最旧，不抛异常。"""
    s = SnipeSession()
    # 塞很多条，多于 maxsize (2000)
    for i in range(2500):
        logger.info(f"msg #{i}")
    logs = s.drain_logs(max_items=3000)
    assert 1 <= len(logs) <= 2000


def test_session_reset_when_idle_ok():
    s = SnipeSession()
    s.reset()  # 不应抛


# ═══════════════════════════════════════════════════════════════
# Api._dict_to_config
# ═══════════════════════════════════════════════════════════════

def _make_form(**overrides):
    """最小合法表单数据，可用 overrides 覆盖。"""
    snipe_future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    base = {
        "ck": "eyJ0dGVzdF90b2tlbl9mb3JfdW5pdF90ZXN0X29ubHk",
        "spu_id": "6521",
        "sku_id": "9266",
        "num": 1,
        "address_id": "695133",
        "snipe_time": snipe_future,
        "concurrency": 3,
        "max_retries": 8,
        "pre_warmup_seconds": 60,
        "max_early_fire_ms": 2000,
        "price_ceiling": 500.0,
        "poll_stock": True,
        "notify_enabled": False,
        "notify_provider": "none",
        "notify_token": "",
    }
    base.update(overrides)
    return base


def test_dict_to_config_minimal():
    api = Api()
    cfg = api._dict_to_config(_make_form())
    assert cfg.target.spu_id == "6521"
    assert cfg.target.sku_id == "9266"
    assert cfg.target.num == 1
    assert cfg.target.address_id == "695133"
    assert cfg.strategy.concurrency == 3
    assert cfg.strategy.poll_stock is True


def test_dict_to_config_rejects_missing_snipe_time():
    api = Api()
    form = _make_form()
    form["snipe_time"] = None
    with pytest.raises(Exception):
        api._dict_to_config(form)


def test_dict_to_config_rejects_bad_ck():
    api = Api()
    form = _make_form(ck="PASTE_CK_HERE")
    with pytest.raises(Exception):
        api._dict_to_config(form)


# ═══════════════════════════════════════════════════════════════
# Api.save_form / load_saved
# ═══════════════════════════════════════════════════════════════

def test_save_form_scrubs_ck_by_default(tmp_path, monkeypatch):
    # 指向临时目录，不污染真实 AppData
    import bandai_sniper.ui.app_config as ac
    monkeypatch.setattr(ac, "app_dir", lambda: tmp_path)

    api = Api()
    form = _make_form(ck="secret_token", remember_ck=False)
    r = api.save_form(form)
    assert r["ok"]

    # 直接读落盘文件，确认 ck 没被保存
    data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "ck" not in data
    assert data["spu_id"] == "6521"


def test_save_form_keeps_ck_if_remember(tmp_path, monkeypatch):
    import bandai_sniper.ui.app_config as ac
    monkeypatch.setattr(ac, "app_dir", lambda: tmp_path)

    api = Api()
    form = _make_form(ck="secret_token", remember_ck=True)
    r = api.save_form(form)
    assert r["ok"]

    data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert data["ck"] == "secret_token"


def test_load_saved_empty_when_no_file(tmp_path, monkeypatch):
    import bandai_sniper.ui.app_config as ac
    monkeypatch.setattr(ac, "app_dir", lambda: tmp_path)

    api = Api()
    assert api.load_saved() == {}
