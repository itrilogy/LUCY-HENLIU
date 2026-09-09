"""分时全量同步。"""
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.connection import open_db
from src.service.lock import single_instance
from src.service.pipeline import sync_trend


def main() -> int:
    with single_instance("数据同步"):
        db = open_db()
        r = sync_trend(db)
        print(r.line(), flush=True)
        db.close()
        return 0 if r.ok else 2


if __name__ == "__main__":
    sys.exit(main())
