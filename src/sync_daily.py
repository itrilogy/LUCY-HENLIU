"""
一键全量同步
  python3 src/sync_daily.py
  python3 src/sync_daily.py --quick   # 行情+K线+分时+预测
  python3 src/sync_daily.py --full    # 与默认相同（保留兼容）
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.connection import open_db
from src.service.lock import single_instance
from src.service.logging_setup import setup_logging
from src.service.pipeline import run_daily


def _run(quick: bool) -> bool:
    mode = "⚡ 快速同步" if quick else "🔄 一键全量同步"
    print(f"\n{'='*50}\n{mode}\n{'='*50}\n")
    db = open_db()
    report = run_daily(db, quick=quick)
    db.close()
    for line in report["logs"]:
        print(line, flush=True)
    print(f"\n{'='*50}")
    print(f"{'✅' if report['ok'] else '⚠️'} {report['status']}: "
          f"{len(report['logs'])} 步, {report['duration']}s")
    if report["failed"]:
        print(f"失败步骤: {', '.join(report['failed'])}")
    print(f"{'='*50}\n")
    return report["ok"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="快速模式")
    parser.add_argument("--full", action="store_true", help="全量（默认）")
    args = parser.parse_args()
    setup_logging("src")

    with single_instance("数据同步"):
        ok = _run(quick=args.quick)
        try:
            from src.service.backup import backup_db
            print(f"💾 数据备份: {backup_db()}")
        except Exception as e:
            print(f"⚠️ 备份失败: {e}", file=sys.stderr)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
