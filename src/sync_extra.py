"""辅助数据：拥挤度 + 宏观指标 + 资金流向。"""
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.connection import open_db
from src.service.lock import single_instance
from src.service.pipeline import sync_crowding, sync_fund_flow, sync_macro_indicators


def main() -> int:
    with single_instance("数据同步"):
        db = open_db()
        results = [sync_crowding(db), sync_macro_indicators(db), sync_fund_flow(db)]
        for r in results:
            print(r.line(), flush=True)
        db.close()
        return 0 if all(r.ok for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
