"""
统一日志：data/logs/ 目录，按天轮转，控制台 + 文件双输出。

用法：
    from src.service.logging_setup import setup_logging
    logger = setup_logging("sync_daily")
    logger.info("同步开始")
"""
import logging
import logging.handlers
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "logs"


def setup_logging(name: str = "quantlab",
                  level: int = logging.INFO) -> logging.Logger:
    """获取（或初始化）统一 logger。幂等：重复调用不重复挂 handler。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    fh = logging.handlers.TimedRotatingFileHandler(
        LOG_DIR / f"{name}.log", when="midnight",
        backupCount=14, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    logger.propagate = False
    return logger
