"""
基于 PRAGMA user_version 的增量迁移。
CREATE IF NOT EXISTS 不会给旧库加列，新变更写在这里。
"""
from __future__ import annotations

import sqlite3
import logging

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

INDICATOR_DEFS = [
    ("GDP_CN", "中国GDP同比增速", "CN", "国民核算", "Y", "%", "国家统计局/国信"),
    ("CPI_CN", "中国CPI同比", "CN", "价格指数", "M", "%", "国家统计局/国信"),
    ("PPI_CN", "中国PPI同比", "CN", "价格指数", "M", "%", "国家统计局/国信"),
    ("M2_CN", "中国M2同比增速", "CN", "货币金融", "M", "%", "央行/国信"),
    ("PMI_CN", "中国制造业PMI", "CN", "产业运行", "M", "点", "统计局/国信"),
    ("LPR_1Y", "中国LPR1年期", "CN", "货币金融", "M", "%", "央行/国信"),
    ("LPR_5Y", "中国LPR5年期", "CN", "货币金融", "M", "%", "央行/国信"),
    ("CPI_US", "美国CPI同比", "US", "国际宏观", "M", "%", "国信"),
    ("FED_RATE", "美国联邦基准利率", "US", "国际宏观", "D", "%", "国信"),
]


def _seed_indicator_def(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """INSERT OR IGNORE INTO indicator_def
           (code, name, region, category, freq, unit, source)
           VALUES (?,?,?,?,?,?,?)""",
        INDICATOR_DEFS)


def migrate(conn: sqlite3.Connection) -> int:
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if ver < 1:
        conn.execute(f"PRAGMA user_version={1}")
        ver = 1
    if ver < 2:
        _seed_indicator_def(conn)
        from src.service.calendar import ensure_calendar
        ensure_calendar(conn)
        conn.execute(f"PRAGMA user_version={2}")
        ver = 2
        logger.info("迁移完成: user_version=%s", ver)
    conn.commit()
    return ver
