from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class Target(BaseModel):
    spu_id: str  # 商品 SPU（必填，查库存 / 构造 skuList）
    sku_id: str  # 具体规格 SKU（有多规格时必须选一个）
    num: int = 1  # 购买数量
    address_id: Optional[str] = None  # 不填则用地址列表第一条
    price_ceiling: float = 99999.0  # confirmOrder 返回 orderAmount 超过此值则弃单


class Strategy(BaseModel):
    pre_warmup_seconds: int = 60  # 提前 N 秒预热（重对时、建 keep-alive）
    lead_ms: int = 5  # 比开抢时刻提前 N 毫秒醒来抵消 TTFB
    max_retries: int = 10  # 单 worker 失败后重试次数
    concurrency: int = 3  # 并发 worker 数
    retry_backoff_ms: int = 50  # 每次失败后 sleep 多少 ms 再重试
    # 默认空：只有网络/超时异常会重试，业务错误（如库存不足 / 限购）立即 fail，
    # 避免在真抢购时因单次误判把 max_retries 烧完。实战抓到 "未开抢" 的真实 code 再填。
    retryable_codes: List[str] = Field(default_factory=list)

    # ── 预热期库存轮询（瞬爆款优化）──
    # 启用后，预热期每 poll_stock_interval_ms 打一次 spu/detail，
    # 发现 stock 跳变 / saleStatus 变 0 / sellOutFlag 变 false 时，
    # 只要 now >= snipe_time - max_early_fire_ms 就提前 fire（不等官方准点）。
    poll_stock: bool = True
    poll_stock_interval_ms: int = 150
    # 最早能比 snipe_time 提前多少 ms fire。太早服务端可能还没开 —— 设成服务器
    # 提前量的保守估计；0 表示必须等到 snipe_time 才 fire（只用轮询避免 busy-wait）
    max_early_fire_ms: int = 2000


class Notify(BaseModel):
    enabled: bool = False
    provider: Literal["bark", "server_chan", "feishu", "none"] = "none"
    token: str = ""


class LogConfig(BaseModel):
    level: str = "INFO"
    dir: str = "./logs"


class Config(BaseModel):
    ck: str
    timezone: str = "Asia/Shanghai"
    snipe_time: datetime
    target: Target
    strategy: Strategy = Field(default_factory=Strategy)
    notify: Notify = Field(default_factory=Notify)
    log: LogConfig = Field(default_factory=LogConfig)

    @field_validator("ck")
    @classmethod
    def _ck_not_placeholder(cls, v: str) -> str:
        if v.startswith("PASTE_") or v.startswith("TODO") or v.startswith("${"):
            raise ValueError("ck 未填写，粘贴从抓 Token 工具或 HAR 拿到的 api-access-token")
        return v


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到配置文件: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config.model_validate(raw)
