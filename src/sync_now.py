"""行情 + 日K 同步（sync_daily --quick 的子集）。"""
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.connection import open_db
from src.service.lock import single_instance
from src.service.pipeline import sync_kline, sync_quotes


def main() -> int:
    with single_instance("数据同步"):
        db = open_db()
        q = sync_quotes(db)
        print(q.line(), flush=True)
        k = sync_kline(db)
        print(k.line(), flush=True)
        db.close()
        return 0 if q.ok else 2


if __name__ == "__main__":
    sys.exit(main())
