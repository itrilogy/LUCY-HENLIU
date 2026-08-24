"""
统一 SQLite 连接：WAL / 外键 / busy_timeout。
所有读写入口应通过 open_db()，避免各脚本各开一套 PRAGMA。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "stock.db"
BUSY_TIMEOUT_MS = 30_000


def default_db_path() -> Path:
    return DEFAULT_DB


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")


def connect(path: str | Path | None = None, *,
            row_factory: bool = False,
            check_same_thread: bool = True) -> sqlite3.Connection:
    p = Path(path) if path else DEFAULT_DB
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=BUSY_TIMEOUT_MS / 1000,
                           check_same_thread=check_same_thread)
    _apply_pragmas(conn)
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn


def open_db(path: str | Path | None = None, *, app: bool = False) -> sqlite3.Connection:
    """建表 + 迁移 + 带 PRAGMA 的连接。app=True 供 Streamlit（跨线程）。"""
    from src.db.schema import init_db
    from src.db.migrations import migrate

    p = str(path or DEFAULT_DB)
    init_db(p)
    conn = connect(p, row_factory=app, check_same_thread=not app)
    migrate(conn)
    return conn
