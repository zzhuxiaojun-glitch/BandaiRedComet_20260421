"""SQLite 持久化层。

文件位置：`%APPDATA%/BandaiSniper/history.db`（Win）/ `~/.config/BandaiSniper/`（Linux）

三张表：
  orders          抢购历史（每次 createOrder 成功落一行）
  products        商品快照（搜索 / 预检 / HAR 解析时 upsert）
  search_history  关键词搜索历史

设计原则：
  - 标准库 sqlite3，零依赖
  - 所有写入在主代码出错时 swallow（不让"存日志"干扰抢购主流程）
  - 用 `Path` 不写绝对路径，跨平台
"""
from __future__ import annotations
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from .ui.app_config import app_dir


_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        TEXT NOT NULL UNIQUE,
    spu_id          TEXT NOT NULL,
    sku_id          TEXT,
    num             INTEGER NOT NULL DEFAULT 1,
    spu_name_cn     TEXT,
    order_amount    REAL,
    deposit_amount  REAL,
    prepay_id       TEXT,
    pay_sign        TEXT,
    created_at      TEXT NOT NULL,
    status          TEXT DEFAULT 'pending_pay',
    raw_json        TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);

CREATE TABLE IF NOT EXISTS products (
    spu_id           TEXT PRIMARY KEY,
    name_cn          TEXT,
    name_jp          TEXT,
    price            REAL,
    category_id      INTEGER,
    deposit_amount   REAL,
    first_seen_at    TEXT NOT NULL,
    last_seen_at     TEXT NOT NULL,
    last_seen_source TEXT,
    raw_json         TEXT
);

CREATE TABLE IF NOT EXISTS search_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword      TEXT NOT NULL,
    result_count INTEGER,
    searched_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_search_keyword ON search_history(keyword);
"""


def db_path() -> Path:
    return app_dir() / "history.db"


def get_conn() -> sqlite3.Connection:
    """打开连接，第一次调用时自动建表。线程安全用 check_same_thread=False。"""
    conn = sqlite3.connect(str(db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe(fn):
    """装饰器：捕获所有异常 + 打 warning，不抛出（DB 故障不应影响主流程）。"""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            logger.warning(f"DB.{fn.__name__} 失败（已忽略）: {e}")
            return None
    return wrapper


# ───────────── orders ─────────────

@_safe
def insert_order(
    *,
    order_id: int | str,
    spu_id: str,
    sku_id: str | None,
    num: int,
    spu_name_cn: str | None,
    order_amount: float | None,
    deposit_amount: float | None,
    prepay_id: str | None,
    pay_sign: str | None,
    raw: dict | None = None,
) -> int | None:
    """新增一条抢购订单记录。order_id 唯一，重复时被 OR REPLACE。"""
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO orders
               (order_id, spu_id, sku_id, num, spu_name_cn, order_amount,
                deposit_amount, prepay_id, pay_sign, created_at, status, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(order_id), str(spu_id), str(sku_id) if sku_id else None,
                int(num), spu_name_cn, order_amount, deposit_amount,
                prepay_id, pay_sign, _now_iso(), "pending_pay",
                json.dumps(raw, ensure_ascii=False) if raw else None,
            ),
        )
        return cur.lastrowid


@_safe
def list_orders(limit: int = 50) -> list[dict]:
    """最近 N 条订单（默认 50），按 created_at 降序。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


@_safe
def update_order_status(order_id: int | str, status: str) -> None:
    """供未来调 getOrderDetail 后回写 paid / cancelled 用。"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET status = ? WHERE order_id = ?",
            (status, str(order_id)),
        )


# ───────────── products ─────────────

@_safe
def upsert_product(
    *,
    spu_id: str,
    name_cn: str | None = None,
    name_jp: str | None = None,
    price: float | None = None,
    category_id: int | None = None,
    deposit_amount: float | None = None,
    source: str = "unknown",  # search / precheck / har
    raw: dict | None = None,
) -> None:
    """upsert：first_seen_at 不变，更新 last_seen_at + 其他字段。"""
    now = _now_iso()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT first_seen_at FROM products WHERE spu_id = ?", (str(spu_id),)
        ).fetchone()
        first_seen = existing["first_seen_at"] if existing else now
        conn.execute(
            """INSERT OR REPLACE INTO products
               (spu_id, name_cn, name_jp, price, category_id, deposit_amount,
                first_seen_at, last_seen_at, last_seen_source, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(spu_id), name_cn, name_jp, price, category_id,
                deposit_amount, first_seen, now, source,
                json.dumps(raw, ensure_ascii=False) if raw else None,
            ),
        )


@_safe
def get_product(spu_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE spu_id = ?", (str(spu_id),)
        ).fetchone()
        return dict(row) if row else None


@_safe
def list_products(limit: int = 100) -> list[dict]:
    """最近见过的商品（last_seen_at 降序）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM products ORDER BY last_seen_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ───────────── search_history ─────────────

@_safe
def add_search_history(keyword: str, result_count: int = 0) -> None:
    if not keyword or not keyword.strip():
        return
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO search_history (keyword, result_count, searched_at)
               VALUES (?, ?, ?)""",
            (keyword.strip(), int(result_count), _now_iso()),
        )


@_safe
def list_search_history(limit: int = 20, unique: bool = True) -> list[dict]:
    """最近搜索关键词。unique=True 时按 keyword 去重 + 返回最近一次。"""
    with get_conn() as conn:
        if unique:
            rows = conn.execute(
                """SELECT keyword, MAX(searched_at) AS searched_at,
                          COUNT(*) AS times,
                          AVG(result_count) AS avg_result
                   FROM search_history
                   GROUP BY keyword
                   ORDER BY searched_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM search_history ORDER BY searched_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


@_safe
def clear_search_history() -> int | None:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM search_history")
        return cur.rowcount
