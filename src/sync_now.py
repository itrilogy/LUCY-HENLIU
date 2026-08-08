"""
全量数据同步脚本 — 后台执行，日志写入文件
用法：
    python3 src/sync_now.py              # 前台执行
    nohup python3 src/sync_now.py &       # 后台执行
    tail -f data/sync.log                 # 查看进度
"""

import sys, os, json, time
from pathlib import Path
from datetime import datetime

# 加载 API Key
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))

sys.path.insert(0, str(Path(__file__).parent.parent))
import sqlite3
from src.datasource.sdicsc_client import get_batch_quote, get_kline, quote_to_db_row

LOG_FILE = Path(__file__).parent.parent / "data" / "sync.log"
DB_FILE = Path(__file__).parent.parent / "data" / "stock.db"


def log(msg: str):
    """写日志（同时 stdout 和文件）"""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    log("=" * 50)
    log("🚀 全量同步开始")

    from src.db.schema import init_db
    init_db(str(DB_FILE))
    db = sqlite3.connect(str(DB_FILE))
    codes = [r[0] for r in db.execute(
        "SELECT DISTINCT stock_code FROM portfolio_stock").fetchall()]
    log(f"📋 待同步股票: {len(codes)} 只")

    # ── 1. 实时行情 ──
    log("--- 📊 同步实时行情 ---")
    t0 = time.time()
    raw_list = []
    try:
        raw_list = get_batch_quote(codes)
        inserted = 0
        for raw in raw_list:
            sc = raw.get("stockCode", "") or raw.get("code", "")
            if not sc:
                continue
            row = quote_to_db_row(raw, sc)
            db.execute(
                """INSERT OR REPLACE INTO real_time_quote
                (stock_code,price,change_amt,change_pct,prev_close,
                 open,high,low,avg_price,volume,amount,turnover,
                 amplitude,volume_ratio,pe,pe_dynamic,pe_ttm,
                 market_value,circ_market_val,change_5d,change_20d,
                 change_60d,change_120d,change_250d,susp_flag,
                 trade_date,trade_time,fetched_at)
                VALUES (:stock_code,:price,:change_amt,:change_pct,:prev_close,
                 :open,:high,:low,:avg_price,:volume,:amount,:turnover,
                 :amplitude,:volume_ratio,:pe,:pe_dynamic,:pe_ttm,
                 :market_value,:circ_market_val,:change_5d,:change_20d,
                 :change_60d,:change_120d,:change_250d,:susp_flag,
                 :trade_date,:trade_time,datetime('now'))""",
                row,
            )
            inserted += 1
        db.commit()
        log(f"  ✅ 行情: {inserted}/{len(raw_list)} 条写入 ({time.time()-t0:.1f}s)")
    except Exception as e:
        log(f"  ❌ 行情失败: {e}")
        db.rollback()

    # ── 2. 日K线 ──
    log("--- 📈 同步日K线 ---")
    total_klines = 0
    for i, code in enumerate(codes):
        try:
            t0 = time.time()
            klines = get_kline(code, "day", 120)
            inserted = 0
            for k in klines:
                cur = db.execute(
                    """INSERT OR IGNORE INTO kline_day
                    (stock_code,trade_date,open,high,low,close,volume,amount)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (code, k["time"], k["open"], k["high"], k["low"],
                     k["close"], k.get("volume", 0), k.get("amount", 0)),
                )
                if cur.rowcount > 0:
                    inserted += 1
            db.commit()
            total_klines += inserted
            log(f"  [{i+1}/{len(codes)}] {code}: {inserted} 条 ({time.time()-t0:.1f}s)")
        except Exception as e:
            log(f"  [{i+1}/{len(codes)}] {code}: ❌ {e}")
            db.rollback()

    # ── 3. 写同步日志 ──
    db.execute(
        "INSERT INTO sync_log(data_type,source,rows_inserted,sync_mode) VALUES(?,'sdicsc',?,'full')",
        ("initial_sync", total_klines + len(raw_list)),
    )
    db.commit()
    db.close()

    log(f"✅ 全量同步完成！行情 {len(raw_list)} 条 + K线 {total_klines} 条")
    log("=" * 50)


if __name__ == "__main__":
    main()
