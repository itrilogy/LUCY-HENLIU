"""同步门面：代码映射、K 线 UPSERT、财务不抹列、行情修剪。"""
from src.db.connection import open_db
from src.service.pipeline import prune_quotes, sync_kline, write_sync_log


def _seed_stock(db, code="000037"):
    db.execute("INSERT INTO stock_basic (stock_code,name,market) VALUES (?,?,?)",
               (code, "测试", "SZ"))
    db.execute("INSERT INTO portfolio (id,name) VALUES (1,'组合')")
    db.execute(
        "INSERT INTO portfolio_stock (portfolio_id,stock_code,market) VALUES (1,?,?)",
        (code, "SZ"))
    db.commit()


def test_kline_upsert_updates_close(tmp_path, monkeypatch):
    db = open_db(tmp_path / "p.db")
    _seed_stock(db)
    db.execute(
        "INSERT INTO kline_day(stock_code,trade_date,open,high,low,close,volume,amount) "
        "VALUES ('000037','2026-08-11',10,11,9,10.5,100,1000)")
    db.commit()

    def fake_kline(code, ktype="day", count=120):
        return [{"time": "2026-08-11", "open": 10, "high": 12, "low": 9,
                 "close": 11.2, "volume": 200, "amount": 2000}]

    import src.datasource.sdicsc_client as sc
    monkeypatch.setattr(sc, "get_kline", fake_kline)
    r = sync_kline(db, ["000037"], days=5)
    assert r.ok
    close = db.execute(
        "SELECT close, volume FROM kline_day WHERE stock_code='000037' AND trade_date='2026-08-11'"
    ).fetchone()
    assert close[0] == 11.2
    assert close[1] == 200
    n = db.execute("SELECT COUNT(*) FROM kline_day").fetchone()[0]
    assert n == 1
    db.close()


def test_financial_upsert_keeps_balance_columns(tmp_path):
    db = open_db(tmp_path / "f.db")
    _seed_stock(db)
    db.execute(
        """INSERT INTO financial_statement
           (stock_code,market,report_type,report_year,revenue,total_assets,oper_cf)
           VALUES ('000037','SZ','Q4','2025',100,500,30)""")
    db.commit()
    db.execute(
        """INSERT INTO financial_statement
           (stock_code,market,report_type,report_year,revenue)
           VALUES ('000037','SZ','Q4','2025',120)
           ON CONFLICT(stock_code, report_type, report_year) DO UPDATE SET
             revenue=COALESCE(excluded.revenue, revenue)""")
    db.commit()
    row = db.execute(
        "SELECT revenue,total_assets,oper_cf FROM financial_statement "
        "WHERE stock_code='000037'").fetchone()
    assert row[0] == 120
    assert row[1] == 500
    assert row[2] == 30
    db.close()


def test_prune_quotes_keeps_latest(tmp_path):
    db = open_db(tmp_path / "q.db")
    _seed_stock(db)
    for i in range(8):
        db.execute(
            "INSERT INTO real_time_quote"
            "(stock_code,price,change_amt,change_pct,prev_close,trade_date,trade_time,fetched_at) "
            "VALUES ('000037',10,0,'0%',10,'2026-08-11','10:00:00',?)",
            (f"2026-08-11 10:0{i}:00",))
    db.commit()
    n = prune_quotes(db, keep=3)
    assert n == 5
    left = db.execute("SELECT COUNT(*) FROM real_time_quote").fetchone()[0]
    assert left == 3
    db.close()


def test_sync_log_records_partial(tmp_path):
    db = open_db(tmp_path / "l.db")
    write_sync_log(db, "partial", 3, 1000, '[{"name":"财务"}]')
    row = db.execute(
        "SELECT status,rows_inserted,errors FROM sync_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row[0] == "partial"
    assert row[1] == 3
    assert "财务" in row[2]
    db.close()
