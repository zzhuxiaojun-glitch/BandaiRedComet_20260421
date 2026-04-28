"""SQLite 持久化层单元测试 —— 用 monkeypatch 把 db 文件指到 tmp_path，
不污染真实 ~/.config/BandaiSniper/history.db。
"""
from __future__ import annotations
import pytest

from bandai_sniper import db as dbmod
from bandai_sniper.ui import app_config as ac


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """把 app_dir 指到 tmp_path，每个测试一个干净 DB。
    注意 db.py 用 `from ... import app_dir` 把符号拉进自己 namespace，
    要 patch 的是 dbmod.app_dir 不是 ac.app_dir。"""
    monkeypatch.setattr(dbmod, "app_dir", lambda: tmp_path)
    yield tmp_path


# ───────────── orders ─────────────

def test_insert_and_list_order(tmp_db):
    rid = dbmod.insert_order(
        order_id=10001, spu_id="6521", sku_id="9266", num=1,
        spu_name_cn="里歇尔", order_amount=154.0, deposit_amount=20.0,
        prepay_id="wxFAKE", pay_sign="SIG_FAKE",
        raw={"foo": "bar"},
    )
    assert rid is not None
    rows = dbmod.list_orders()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "10001"
    assert rows[0]["spu_name_cn"] == "里歇尔"
    assert rows[0]["status"] == "pending_pay"
    assert rows[0]["order_amount"] == 154.0


def test_orders_unique_by_order_id(tmp_db):
    """同 order_id 重复 insert 应该 OR REPLACE，最终只有一条。"""
    dbmod.insert_order(order_id=999, spu_id="A", sku_id=None, num=1,
                       spu_name_cn=None, order_amount=10.0, deposit_amount=None,
                       prepay_id=None, pay_sign=None)
    dbmod.insert_order(order_id=999, spu_id="A", sku_id=None, num=2,
                       spu_name_cn="新名字", order_amount=20.0, deposit_amount=None,
                       prepay_id=None, pay_sign=None)
    rows = dbmod.list_orders()
    assert len(rows) == 1
    assert rows[0]["num"] == 2
    assert rows[0]["spu_name_cn"] == "新名字"


def test_orders_sorted_desc(tmp_db):
    import time
    dbmod.insert_order(order_id=1, spu_id="A", sku_id=None, num=1,
                       spu_name_cn="第一", order_amount=None, deposit_amount=None,
                       prepay_id=None, pay_sign=None)
    time.sleep(1.1)  # iso 秒级精度
    dbmod.insert_order(order_id=2, spu_id="B", sku_id=None, num=1,
                       spu_name_cn="第二", order_amount=None, deposit_amount=None,
                       prepay_id=None, pay_sign=None)
    rows = dbmod.list_orders()
    assert rows[0]["spu_name_cn"] == "第二"
    assert rows[1]["spu_name_cn"] == "第一"


def test_update_order_status(tmp_db):
    dbmod.insert_order(order_id=42, spu_id="X", sku_id=None, num=1,
                       spu_name_cn=None, order_amount=None, deposit_amount=None,
                       prepay_id=None, pay_sign=None)
    dbmod.update_order_status(42, "paid")
    rows = dbmod.list_orders()
    assert rows[0]["status"] == "paid"


# ───────────── products upsert ─────────────

def test_upsert_product_first_seen_unchanged(tmp_db):
    """upsert 第二次 first_seen_at 不变，last_seen_at 更新。"""
    import time
    dbmod.upsert_product(spu_id="6521", name_cn="A", source="search")
    p1 = dbmod.get_product("6521")
    time.sleep(1.1)
    dbmod.upsert_product(spu_id="6521", name_cn="A 改名", source="precheck")
    p2 = dbmod.get_product("6521")
    assert p1["first_seen_at"] == p2["first_seen_at"]
    assert p2["last_seen_at"] > p1["last_seen_at"]
    assert p2["last_seen_source"] == "precheck"
    assert p2["name_cn"] == "A 改名"


def test_list_products_recent_first(tmp_db):
    import time
    dbmod.upsert_product(spu_id="OLD", name_cn="old")
    time.sleep(1.1)
    dbmod.upsert_product(spu_id="NEW", name_cn="new")
    rows = dbmod.list_products()
    assert rows[0]["spu_id"] == "NEW"
    assert rows[1]["spu_id"] == "OLD"


# ───────────── search_history ─────────────

def test_add_search_history(tmp_db):
    dbmod.add_search_history("里歇尔", 1)
    dbmod.add_search_history("里歇尔", 1)
    dbmod.add_search_history("高达", 396)
    items = dbmod.list_search_history()
    # unique 默认开
    assert len(items) == 2
    keywords = {it["keyword"] for it in items}
    assert keywords == {"里歇尔", "高达"}
    # 里歇尔 搜了 2 次
    rishelle = next(it for it in items if it["keyword"] == "里歇尔")
    assert rishelle["times"] == 2


def test_search_history_skips_empty(tmp_db):
    dbmod.add_search_history("", 0)
    dbmod.add_search_history("   ", 0)
    items = dbmod.list_search_history()
    assert len(items) == 0


def test_clear_search_history(tmp_db):
    dbmod.add_search_history("foo", 1)
    dbmod.add_search_history("bar", 1)
    cleared = dbmod.clear_search_history()
    assert cleared == 2
    assert dbmod.list_search_history() == []


# ───────────── 故障吞噬（DB 不影响主流程）─────────────

def test_db_failure_swallowed_returns_none(tmp_db, monkeypatch):
    """模拟 DB 故障：让 get_conn 抛异常，所有 _safe 装饰器函数应返回 None
    而不抛出。"""
    def boom():
        raise RuntimeError("DB 故障模拟")
    monkeypatch.setattr(dbmod, "get_conn", boom)
    # 各种调用都不应该抛
    assert dbmod.insert_order(order_id=1, spu_id="X", sku_id=None, num=1,
                              spu_name_cn=None, order_amount=None,
                              deposit_amount=None, prepay_id=None,
                              pay_sign=None) is None
    assert dbmod.list_orders() is None
    assert dbmod.upsert_product(spu_id="X") is None
    assert dbmod.add_search_history("foo", 1) is None
