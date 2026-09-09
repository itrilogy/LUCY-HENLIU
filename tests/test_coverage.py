"""数据覆盖率服务测试"""
import sqlite3

from src.db.schema import init_db
from src.service.coverage import compute_coverage


def test_compute_coverage_writes_and_returns(tmp_path):
    db_path = str(tmp_path / "c.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO portfolio (id,name) VALUES (1,'组合')")
    conn.execute("INSERT INTO portfolio_stock (portfolio_id,stock_code,market,is_holding) VALUES (1,'000037','SZ',1)")
    conn.execute("INSERT INTO kline_day(stock_code,trade_date,open,high,low,close,volume,amount) VALUES('000037','2026-08-06',10,10,10,10,100,1000)")
    conn.execute("INSERT INTO kline_day(stock_code,trade_date,open,high,low,close,volume,amount) VALUES('000037','2026-08-07',10,10,10,10,100,1000)")
    conn.execute("INSERT INTO financial_statement(stock_code,market,report_type,report_year,revenue) VALUES('000037','SZ','Q4','2025',100)")
    conn.commit()

    rows = compute_coverage(conn)
    assert len(rows) == 1
    assert rows[0]["K线天数"] == 2
    assert rows[0]["K线止"] == "2026-08-07"
    assert rows[0]["财务期数"] == 1

    # 落库到 data_coverage（K线/财务两种 data_type）
    n = conn.execute("SELECT COUNT(*) FROM data_coverage").fetchone()[0]
    assert n == 2
    conn.close()


def test_compute_coverage_persist_false_is_readonly(tmp_path):
    """persist=False（UI 浏览路径）不写库、不刷新 last_synced_at"""
    db_path = str(tmp_path / "c.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO portfolio (id,name) VALUES (1,'组合')")
    conn.execute("INSERT INTO portfolio_stock (portfolio_id,stock_code,market,is_holding) VALUES (1,'000037','SZ',1)")
    conn.execute("INSERT INTO kline_day(stock_code,trade_date,open,high,low,close,volume,amount) VALUES('000037','2026-08-07',10,10,10,10,100,1000)")
    conn.commit()
    rows = compute_coverage(conn, persist=False)
    assert len(rows) == 1
    assert conn.execute("SELECT COUNT(*) FROM data_coverage").fetchone()[0] == 0  # 未落库
    conn.close()


def test_guess_market_bond_segments():
    """可转债/可交换债市场细分：沪 110/113/118/132/120，深 123/128"""
    from src.service.codes import guess_market
    assert guess_market("110059") == "SH"   # 沪市可转债
    assert guess_market("113050") == "SH"
    assert guess_market("120002") == "SH"   # 沪市可交换债
    assert guess_market("123185") == "SZ"   # 深市可转债
    assert guess_market("128096") == "SZ"
    assert guess_market("600519") == "SH"
    assert guess_market("000001") == "SZ"
    assert guess_market("H02380") == "HK"
