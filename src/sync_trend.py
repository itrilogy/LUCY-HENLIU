"""
分时数据全量同步脚本 — 后台执行
用法：
    python3 src/sync_trend.py                     # 前台
    nohup python3 src/sync_trend.py > data/sync_trend.log 2>&1 &
    tail -f data/sync_trend.log                   # 看进度
"""

import sys, os, time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
from src.datasource.sdicsc_client import get_trend

LOG = Path(__file__).parent.parent / "data" / "sync_trend.log"
DB = Path(__file__).parent.parent / "data" / "stock.db"


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    log("=" * 50)
    log("🚀 分时全量同步开始")

    from src.db.schema import init_db
    init_db(str(DB))
    db = sqlite3.connect(str(DB))
    codes = [r[0] for r in db.execute(
        "SELECT DISTINCT stock_code FROM portfolio_stock").fetchall()]
    log(f"📋 待同步: {len(codes)} 只")

    ok, fail = 0, 0
    for i, code in enumerate(codes, 1):
        try:
            t0 = time.time()
            raw = get_trend(code)
            meta = raw.get("meta", {})
            date = meta.get("date", "")
            td = raw.get("timeData", [])
            ins = 0
            for t in td:
                cur = db.execute(
                    """INSERT OR IGNORE INTO trend_data
                    (stock_code,trade_date,time_seq,price,avg_price,
                     volume,change_amt,change_pct)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (code, date, t["time"], t["price"],
                     t.get("avgPrice"), t.get("volume", 0),
                     t.get("change", 0), t.get("changePercent", "")),
                )
                if cur.rowcount > 0:
                    ins += 1
            db.commit()
            log(f"  [{i}/{len(codes)}] {code}: {ins}/{len(td)} 点 ({time.time()-t0:.1f}s)")
            ok += 1
        except Exception as e:
            log(f"  [{i}/{len(codes)}] {code}: ❌ {e}")
            fail += 1

    db.close()
    log(f"✅ 完成: {ok} 成功, {fail} 失败")
    log("=" * 50)


if __name__ == "__main__":
    main()
