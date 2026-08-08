"""预测-反馈闭环测试"""
import sqlite3

import numpy as np
import pandas as pd

from src.db.schema import init_db
from src.quant.prediction_loop import (
    settle_predictions, generate_predictions, run_prediction_loop,
)


def _make_db(tmp_path, n_days=90, seed=7):
    db_path = str(tmp_path / "pl.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO portfolio (id,name) VALUES (1,'组合')")
    conn.execute("INSERT INTO stock_basic (stock_code,name,market) VALUES ('000037','深南电A','SZ')")
    conn.execute("INSERT INTO portfolio_stock (portfolio_id,stock_code,market,is_holding) VALUES (1,'000037','SZ',1)")
    rng = np.random.default_rng(seed)
    close = np.maximum(10 + np.cumsum(rng.normal(0, 0.3, n_days)), 5)
    dates = pd.bdate_range("2026-03-01", periods=n_days).strftime("%Y-%m-%d")
    for i, d in enumerate(dates):
        o = close[i - 1] if i > 0 else close[i]
        conn.execute(
            "INSERT OR IGNORE INTO kline_day(stock_code,trade_date,open,high,low,close,volume,amount) VALUES(?,?,?,?,?,?,?,?)",
            ('000037', d, round(float(o), 2), round(float(max(o, close[i])), 2),
             round(float(min(o, close[i])), 2), round(float(close[i]), 2), 100000, 1e6))
    conn.commit()
    return conn, list(dates), close


def test_generate_predictions_inserts_once(tmp_path):
    conn, _, _ = _make_db(tmp_path)
    # 连续两次生成同一目标日 → 不重复插入（防重）
    assert generate_predictions(conn, "000037")
    assert generate_predictions(conn, "000037")
    n = conn.execute("SELECT COUNT(*) FROM prediction_log").fetchone()[0]
    assert n == 1
    conn.close()


def test_settle_on_target_date(tmp_path):
    conn, dates, close = _make_db(tmp_path)
    target = dates[-2]
    idx = dates.index(target)
    actual = "up" if (close[idx] - close[idx - 1]) / close[idx - 1] * 100 > 1 else "down"
    conn.execute(
        "INSERT INTO prediction_log(stock_code,trade_date,direction,confidence,predicted_price) VALUES('000037',?,?,0.5,10)",
        (target, actual))
    conn.commit()
    n = settle_predictions(conn, "000037")
    assert n == 1
    row = conn.execute("SELECT actual_direction, actual_price, correct FROM prediction_log").fetchone()
    assert row[0] == actual       # 结算方向与真实涨跌一致
    assert row[1] is not None     # 回填了实际价
    assert row[2] == 1            # 命中
    conn.close()


def test_settle_rolls_forward_for_weekend(tmp_path):
    """目标日在无K线的日期（周末）→ 顺延到其后最近交易日结算"""
    conn, dates, _ = _make_db(tmp_path)
    import datetime
    last_dt = datetime.date.fromisoformat(dates[-1])
    saturday = last_dt + datetime.timedelta(days=1)  # 周六，无K线
    # 补一根周一K线（构造 saturday 之后的交易日）
    monday = last_dt + datetime.timedelta(days=3)
    conn.execute(
        "INSERT OR IGNORE INTO kline_day(stock_code,trade_date,open,high,low,close,volume,amount) VALUES(?,?,?,?,?,?,?,?)",
        ('000037', monday.isoformat(), 10, 10.2, 9.8, 10.1, 100000, 1e6))
    conn.execute(
        "INSERT INTO prediction_log(stock_code,trade_date,direction,confidence,predicted_price) VALUES('000037',?,'up',0.5,10)",
        (saturday.isoformat(),))
    conn.commit()
    n = settle_predictions(conn, "000037")
    assert n == 1  # 顺延结算成功，不永久 pending
    row = conn.execute("SELECT actual_price FROM prediction_log").fetchone()
    assert row[0] == 10.1  # 用周一收盘价结算
    conn.close()


def test_run_prediction_loop_full(tmp_path):
    conn, _, _ = _make_db(tmp_path)
    r = run_prediction_loop(conn)
    assert r["predicted"] == 1
    assert r["skipped"] == 0
    conn.close()
