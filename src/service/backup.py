"""
SQLite 自动备份：VACUUM INTO 每日快照到 data/backups/，自动清理过期备份。

SQLite 单文件易损坏，每日备份是数据安全的底线。
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def backup_db(db_path: str = "", keep_days: int = 14) -> Path:
    """
    备份 stock.db 到 data/backups/stock-YYYYMMDD.db。
    当日已有备份则直接返回（幂等）。
    """
    db_path = db_path or str(DATA_DIR / "stock.db")
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d")
    target = backup_dir / f"stock-{stamp}.db"
    if target.exists():
        return target

    conn = sqlite3.connect(db_path)
    try:
        # VACUUM INTO 不支持绑定参数，需转义路径中的单引号
        safe = str(target).replace("'", "''")
        conn.execute(f"VACUUM INTO '{safe}'")
    finally:
        conn.close()

    # 清理过期备份，保留最近 keep_days 份
    backups = sorted(backup_dir.glob("stock-*.db"))
    for old in backups[:-keep_days]:
        old.unlink()
    return target
