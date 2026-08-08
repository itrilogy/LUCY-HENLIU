"""
数据覆盖率：计算每只自选股的 K线/分时/财务覆盖情况，
写入 data_coverage 表（供 UI 展示与数据健康检查）。
"""
import sqlite3
from typing import List


def compute_coverage(db: sqlite3.Connection) -> List[dict]:
    """
    计算并落库每只自选股的覆盖率，返回可展示的报告行。
    data_coverage 表结构见 src/db/schema.py（UNIQUE(stock_code, data_type)）。
    """
    stocks = db.execute("SELECT stock_code FROM portfolio_stock").fetchall()
    rows: List[dict] = []
    for (code,) in stocks:
        # K线覆盖
        k = db.execute(
            "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM kline_day WHERE stock_code=?",
            (code,)).fetchone()
        # 分时覆盖（最近交易日 + 点数）
        t = db.execute(
            "SELECT MAX(trade_date), COUNT(*) FROM trend_data WHERE stock_code=?",
            (code,)).fetchone()
        # 财务期数
        f = db.execute(
            "SELECT COUNT(*) FROM financial_statement WHERE stock_code=?", (code,)).fetchone()

        k_start, k_end, k_days = k
        if k_days:
            db.execute(
                """INSERT OR REPLACE INTO data_coverage
                   (stock_code, data_type, coverage_start, coverage_end,
                    total_days, filled_days, last_synced_at)
                   VALUES (?,?,?,?,?,?,datetime('now'))""",
                (code, "kline_day", k_start, k_end, k_days or 0, k_days or 0))
        if t[0]:
            db.execute(
                """INSERT OR REPLACE INTO data_coverage
                   (stock_code, data_type, coverage_start, coverage_end,
                    total_days, filled_days, last_synced_at)
                   VALUES (?,?,?,?,?,?,datetime('now'))""",
                (code, "trend_data", t[0], t[0], t[1] or 0, t[1] or 0))
        if f[0]:
            db.execute(
                """INSERT OR REPLACE INTO data_coverage
                   (stock_code, data_type, coverage_start, coverage_end,
                    total_days, filled_days, last_synced_at)
                   VALUES (?,?,?,?,?,?,datetime('now'))""",
                (code, "financial", None, None, f[0] or 0, f[0] or 0))
        rows.append({
            "股票": code,
            "K线天数": k_days or 0,
            "K线起": k_start or "-",
            "K线止": k_end or "-",
            "分时点数": t[1] or 0,
            "财务期数": f[0] or 0,
        })
    db.commit()
    return rows
