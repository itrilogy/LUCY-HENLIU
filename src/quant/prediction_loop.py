"""
预测-反馈闭环（PatternDiscoveryEngine 在线收敛）

职责：
1. settle_predictions —— 按预测目标日的实际K线结算已到期的未结算预测
2. generate_predictions —— 基于最新状态生成下一交易日预测并入库（防重复）

接入方式：在每日同步（sync_daily.py）末尾调用 run_prediction_loop(db)，
实现 README 所述「预测 → 对比实际 → 更新模式库 → 收敛提升」闭环。
"""

import sqlite3
from typing import List, Optional

import pandas as pd

from src.quant.pattern_discovery import PatternDiscoveryEngine


def _load_kline(db: sqlite3.Connection, code: str) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT * FROM kline_day WHERE stock_code=? ORDER BY trade_date",
        db, params=(code,))


def settle_predictions(db: sqlite3.Connection, code: str) -> int:
    """
    结算该股票所有已到期（目标日已有K线）的未结算预测。

    与预测方向定义一致：目标日 T 相对前一交易日 T-1 的涨跌。
    连续多日未同步时，各条预测按其自身目标日的收盘价逐条结算，不混用最新价。
    """
    pending = db.execute(
        """SELECT id, direction, predicted_price, trade_date FROM prediction_log
           WHERE stock_code=? AND actual_price IS NULL""",
        (code,)).fetchall()
    n = 0
    for pid, pred_dir, pred_price, target_date in pending:
        # 目标日有 K 线则按当日结算；无 K 线（节假日/停牌）顺延到其后最近交易日
        target_row = db.execute(
            "SELECT close FROM kline_day WHERE stock_code=? AND trade_date=?",
            (code, target_date)).fetchone()
        if target_row is not None:
            settle_date, actual_close = target_date, float(target_row[0])
        else:
            next_row = db.execute(
                """SELECT trade_date, close FROM kline_day
                   WHERE stock_code=? AND trade_date > ? ORDER BY trade_date LIMIT 1""",
                (code, target_date)).fetchone()
            if next_row is None:
                continue  # 之后尚无交易日数据，保留 pending 待下次结算
            settle_date, actual_close = str(next_row[0]), float(next_row[1])
        prev_row = db.execute(
            """SELECT close FROM kline_day WHERE stock_code=? AND trade_date<?
               ORDER BY trade_date DESC LIMIT 1""",
            (code, settle_date)).fetchone()
        if prev_row is None:
            continue
        prev_close = float(prev_row[0])
        ret = (actual_close - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        actual_dir = "up" if ret > 1 else "down" if ret < -1 else "flat"
        correct = int(actual_dir == pred_dir)
        db.execute(
            """UPDATE prediction_log
               SET actual_direction=?, actual_price=?, correct=?, error_pct=?
               WHERE id=?""",
            (actual_dir, actual_close, correct, round(abs(ret), 2), pid))
        n += 1
    db.commit()
    return n


def _db_path(db: sqlite3.Connection) -> str:
    row = db.execute("PRAGMA database_list").fetchone()
    return row[2] if row else ""


def generate_predictions(db: sqlite3.Connection, code: str) -> bool:
    """基于最新K线生成下一交易日预测并入库（防重复）。模式写入 pattern_library。"""
    kdf = _load_kline(db, code)
    if len(kdf) < 50:
        return False
    pde = PatternDiscoveryEngine(code, db_path=_db_path(db))
    if not pde.fit(kdf):
        return False
    pde.discover_patterns()
    pred = pde.predict()
    if pred is None:
        return False
    used = ",".join(pred.patterns_used[:4]) if pred.patterns_used else None
    exists = db.execute(
        """SELECT id FROM prediction_log
           WHERE stock_code=? AND trade_date=? AND actual_price IS NULL""",
        (pred.stock_code, pred.trade_date)).fetchone()
    if exists:
        db.execute(
            """UPDATE prediction_log
               SET direction=?, confidence=?, predicted_price=?,
                   engine_version=?, pattern_type=?
               WHERE id=?""",
            (pred.direction, pred.confidence, pred.predicted_price,
             pred.engine_version, used, exists[0]))
        db.commit()
        return True
    db.execute(
        """INSERT INTO prediction_log
           (stock_code, trade_date, direction, confidence,
            predicted_price, engine_version, pattern_type)
           VALUES (?,?,?,?,?,?,?)""",
        (pred.stock_code, pred.trade_date, pred.direction,
         pred.confidence, pred.predicted_price, pred.engine_version, used))
    db.commit()
    return True


def oos_stats(db: sqlite3.Connection) -> dict:
    """已结算预测的样本外统计，对比多数类基线（不是 33%）。"""
    rows = db.execute(
        """SELECT direction, actual_direction, correct
           FROM prediction_log WHERE actual_price IS NOT NULL"""
    ).fetchall()
    n = len(rows)
    if n == 0:
        return {"n": 0, "hits": 0, "accuracy": None,
                "majority_class": None, "majority_baseline": None,
                "vs_baseline": None}
    hits = sum(int(r[2] or 0) for r in rows)
    from collections import Counter
    actuals = Counter(r[1] for r in rows)
    maj_cls, maj_n = actuals.most_common(1)[0]
    baseline = maj_n / n
    acc = hits / n
    return {
        "n": n,
        "hits": hits,
        "accuracy": round(acc, 4),
        "majority_class": maj_cls,
        "majority_baseline": round(baseline, 4),
        "vs_baseline": round(acc - baseline, 4),
        "by_actual": dict(actuals),
        "by_pred": dict(Counter(r[0] for r in rows)),
    }


def run_prediction_loop(db: sqlite3.Connection,
                        codes: Optional[List[str]] = None) -> dict:
    """完整闭环：先结算到期预测，再生成新一轮预测。"""
    if codes is None:
        codes = [r[0] for r in db.execute(
            "SELECT stock_code FROM portfolio_stock").fetchall()]
    result = {"settled": 0, "predicted": 0, "skipped": 0}
    for code in codes:
        try:
            result["settled"] += settle_predictions(db, code)
            if generate_predictions(db, code):
                result["predicted"] += 1
            else:
                result["skipped"] += 1
        except Exception as e:  # 单只失败不影响整体
            print(f"  ⚠️ 预测闭环 {code}: {e}", flush=True)
            result["skipped"] += 1
    return result
