import datetime

from src.service.calendar import is_trading_day, next_open_date, generate_default_calendar
from src.db.connection import open_db


def test_weekend_and_holiday():
    assert not is_trading_day(datetime.date(2026, 8, 8))   # 周六
    assert is_trading_day(datetime.date(2026, 8, 10))      # 周一
    assert not is_trading_day(datetime.date(2026, 10, 1))  # 国庆
    assert not is_trading_day(datetime.date(2026, 10, 8))


def test_next_open_skips_national_day():
    # 2026-09-30 周三之后是国庆连休至 10-08
    assert next_open_date("2026-09-30") == "2026-10-09"


def test_open_db_seeds_calendar(tmp_path):
    db = open_db(tmp_path / "c.db")
    n = db.execute("SELECT COUNT(*) FROM trade_calendar").fetchone()[0]
    assert n >= 365
    n_open = db.execute(
        "SELECT COUNT(*) FROM trade_calendar WHERE is_open=1 AND trade_date LIKE '2026-%'"
    ).fetchone()[0]
    assert 220 < n_open < 260
    defs = db.execute("SELECT COUNT(*) FROM indicator_def").fetchone()[0]
    assert defs >= 8
    db.close()


def test_generate_year_has_weekends():
    rows = generate_default_calendar(2026)
    assert len(rows) == 365
    sat = [r for r in rows if r[0] == "2026-08-08"][0]
    assert sat[2] == 0
