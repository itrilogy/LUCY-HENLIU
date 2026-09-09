from src.db.schema import init_db
from src.quant.prediction_loop import oos_stats
import sqlite3


def test_oos_stats_vs_majority(tmp_path):
    p = str(tmp_path / "o.db")
    init_db(p)
    db = sqlite3.connect(p)
    # 10 条：实际 7 flat / 3 up；预测全猜 up → 命中 3，基线 0.7
    for i, (pred, actual, ok) in enumerate([
        ("up", "flat", 0), ("up", "flat", 0), ("up", "flat", 0),
        ("up", "flat", 0), ("up", "flat", 0), ("up", "flat", 0),
        ("up", "flat", 0), ("up", "up", 1), ("up", "up", 1), ("up", "up", 1),
    ]):
        db.execute(
            "INSERT INTO prediction_log"
            "(stock_code,trade_date,direction,actual_direction,actual_price,correct) "
            "VALUES ('000037',?,?,?,?,?)",
            (f"2026-08-{i+1:02d}", pred, actual, 10.0, ok))
    db.commit()
    s = oos_stats(db)
    assert s["n"] == 10
    assert s["hits"] == 3
    assert s["majority_class"] == "flat"
    assert s["majority_baseline"] == 0.7
    assert s["vs_baseline"] == round(0.3 - 0.7, 4)
    db.close()


def test_oos_empty(tmp_path):
    p = str(tmp_path / "e.db")
    init_db(p)
    db = sqlite3.connect(p)
    s = oos_stats(db)
    assert s["n"] == 0
    assert s["accuracy"] is None
    db.close()
