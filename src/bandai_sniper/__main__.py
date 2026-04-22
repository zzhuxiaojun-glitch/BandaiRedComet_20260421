import asyncio
import sys
from pathlib import Path

import click
from loguru import logger

from .config import load_config
from .sniper import Sniper
from .timer import sync_ntp_offset


def _setup_logger(level: str, log_dir: str) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=level, format="<green>{time:HH:mm:ss.SSS}</green> <level>{level:<7}</level> {message}")
    logger.add(
        f"{log_dir}/run_{{time:YYYYMMDD_HHmmss}}.log",
        level="DEBUG",
        rotation="50 MB",
        retention="30 days",
        encoding="utf-8",
    )
    # HTTP 请求单独落 jsonl
    logger.add(
        f"{log_dir}/requests_{{time:YYYYMMDD_HHmmss}}.jsonl",
        level="INFO",
        filter=lambda rec: rec["extra"].get("tag") == "http",
        format="{message}",
        rotation="50 MB",
        retention="30 days",
        encoding="utf-8",
    )


@click.group()
@click.option("-c", "--config", "config_path", default="config.yaml", show_default=True)
@click.pass_context
def cli(ctx, config_path):
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


def _load(ctx):
    cfg = load_config(ctx.obj["config_path"])
    _setup_logger(cfg.log.level, cfg.log.dir)
    ctx.obj["cfg"] = cfg
    return cfg


@cli.command(help="抢单主流程")
@click.pass_context
def run(ctx):
    cfg = _load(ctx)
    sniper = Sniper(cfg)
    asyncio.run(sniper.run())


@cli.command(help="仅做 CK + 商品 + 地址 的预检，不抢")
@click.pass_context
def check(ctx):
    cfg = _load(ctx)
    sniper = Sniper(cfg)

    async def _do():
        try:
            await sniper.precheck()
            logger.success("预检通过，可以等时间")
        finally:
            await sniper.aclose()

    asyncio.run(_do())


@cli.command("ntp", help="测一下本机与 NTP 的时间偏差")
def ntp_cmd():
    offset = sync_ntp_offset()
    click.echo(f"本机时间偏差: {offset*1000:.1f}ms")


if __name__ == "__main__":
    cli(obj={})
