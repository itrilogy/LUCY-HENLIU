"""数据库 schema 测试"""
import sqlite3

from src.db.schema import init_db

# 全部 24 张表（schema.py 定义）
EXPECTED_TABLES = [
    "portfolio", "portfolio_stock", "stock_basic",
    "real_time_quote", "kline_day", "kline_minute",
    "trend_data", "financial_statement", "fund_flow",
    "macro_indicator", "indicator_def", "sector",
    "stock_sector_map", "trade_calendar",
    "sync_log", "data_coverage", "adjust_factor",
    "data_source_health",
    "pattern_library", "prediction_log",
    "prediction_models", "research_article",
    "tag_library", "sector_crowding",
]


def _tables(db_path):
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")}
    conn.close()
    return tables


def test_init_db_creates_all_tables(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    missing = [t for t in EXPECTED_TABLES if t not in _tables(db_path)]
    assert missing == [], f"缺少表: {missing}"


def test_init_db_idempotent(tmp_path):
    """重复初始化不报错、不改变已有表结构"""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    init_db(db_path)  # 第二次应无副作用
    assert len(_tables(db_path)) == len(EXPECTED_TABLES)


def test_key_tables_writable(tmp_path):
    """核心表（含预测闭环/研报/模式库）可写入"""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO portfolio (id,name) VALUES (1,'组合')")
    conn.execute("INSERT INTO portfolio_stock (portfolio_id,stock_code,market,is_holding) VALUES (1,'000037','SZ',1)")
    conn.execute("INSERT INTO prediction_log(stock_code,trade_date,direction,confidence,predicted_price) VALUES('000037','2026-08-10','up',0.5,10)")
    conn.execute("INSERT INTO pattern_library(stock_code,pattern_type,pattern_sig,direction) VALUES('000037','candlestick','x','up')")
    conn.commit()
    conn.close()
