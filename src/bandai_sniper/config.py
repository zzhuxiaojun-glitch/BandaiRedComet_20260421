from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class Target(BaseModel):
    sku_id: str
    spu_id: Optional[str] = None
    quantity: int = 1
    address_id: str
    price_ceiling: float = 9999.0


class Strategy(BaseModel):
    pre_warmup_seconds: int = 60
    poll_interval_ms: int = 200
    max_retries: int = 10
    concurrency: int = 3
    retry_backoff_ms: int = 50
    retryable_codes: List[str] = Field(default_factory=list)


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
    strategy: Strategy
    notify: Notify
    log: LogConfig = Field(default_factory=LogConfig)

    @field_validator("ck")
    @classmethod
    def _ck_not_placeholder(cls, v: str) -> str:
        if v.startswith("PASTE_") or v.startswith("TODO"):
            raise ValueError("ck 未填写，请粘贴从抓 Token 工具复制的 api-access-token")
        return v


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到配置文件: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config.model_validate(raw)
