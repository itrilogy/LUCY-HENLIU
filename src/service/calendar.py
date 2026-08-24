"""A 股交易日历：周末 + 法定休市。调度与下一交易日估算共用。"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Iterable

# 上交所/深交所休市日（不含周末）。覆盖近年即可，缺的年份退化为「仅周末」。
# 含调休后的连续休市区间；补班周六未单独打开（个人工具可接受）。
CLOSED_DATES: frozenset[str] = frozenset({
    # 2025
    "2025-01-01",
    "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
    "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",
    "2025-04-04", "2025-04-05", "2025-04-06",
    "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
    "2025-05-31", "2025-06-01", "2025-06-02",
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04",
    "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
    # 2026
    "2026-01-01", "2026-01-02",
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-09-25", "2026-09-26", "2026-09-27",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
    # 2027 元旦 + 春节占位（农历丁未年约 2 月 6 日）
    "2027-01-01",
    "2027-02-06", "2027-02-07", "2027-02-08", "2027-02-09",
    "2027-02-10", "2027-02-11", "2027-02-12", "2027-02-13", "2027-02-14",
})


def _as_date(d: date | datetime | str | None) -> date:
    if d is None:
        return date.today()
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def is_closed(d: date | datetime | str) -> bool:
    day = _as_date(d)
    if day.weekday() >= 5:
        return True
    return day.isoformat() in CLOSED_DATES


def is_trading_day(d: date | datetime | str | None = None,
                   db: sqlite3.Connection | None = None) -> bool:
    """优先读 trade_calendar；表空或无该日则用周末+法定假日规则。"""
    day = _as_date(d)
    iso = day.isoformat()
    if db is not None:
        row = db.execute(
            "SELECT is_open FROM trade_calendar WHERE trade_date=?", (iso,)
        ).fetchone()
        if row is not None:
            return int(row[0]) == 1
    return not is_closed(day)


def generate_default_calendar(year: int) -> list[tuple]:
    days: list[tuple] = []
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        iso = d.isoformat()
        weekend = d.weekday() >= 5
        holiday = iso in CLOSED_DATES
        if weekend:
            days.append((iso, "SH", 0, "周末"))
        elif holiday:
            days.append((iso, "SH", 0, "节假日"))
        else:
            days.append((iso, "SH", 1, "交易日"))
        d += timedelta(days=1)
    return days


def ensure_calendar(db: sqlite3.Connection, years: Iterable[int] | None = None) -> int:
    if years is None:
        y = date.today().year
        years = (y - 1, y, y + 1)
    inserted = 0
    for y in years:
        exists = db.execute(
            "SELECT 1 FROM trade_calendar WHERE trade_date LIKE ? LIMIT 1",
            (f"{y}-%",)).fetchone()
        if exists:
            # 已有年份：把法定假日标成休市（不覆盖已有自定义）
            for iso in CLOSED_DATES:
                if iso.startswith(f"{y}-"):
                    db.execute(
                        "UPDATE trade_calendar SET is_open=0, day_type='节假日' "
                        "WHERE trade_date=? AND is_open=1 AND day_type!='周末'",
                        (iso,))
            continue
        rows = generate_default_calendar(y)
        db.executemany(
            "INSERT OR IGNORE INTO trade_calendar "
            "(trade_date, market, is_open, day_type) VALUES (?,?,?,?)",
            rows)
        inserted += len(rows)
    db.commit()
    return inserted


def get_trade_days(db: sqlite3.Connection, start: str, end: str,
                   market: str = "SH") -> list[str]:
    cur = db.execute(
        "SELECT trade_date FROM trade_calendar "
        "WHERE market=? AND is_open=1 AND trade_date BETWEEN ? AND ? "
        "ORDER BY trade_date", (market, start, end))
    return [row[0] for row in cur]


def next_open_date(after: date | datetime | str,
                   db: sqlite3.Connection | None = None,
                   max_ahead: int = 15) -> str:
    """after 之后的下一个开市日（不含 after 当天）。"""
    day = _as_date(after) + timedelta(days=1)
    if db is not None:
        row = db.execute(
            "SELECT trade_date FROM trade_calendar "
            "WHERE is_open=1 AND trade_date>? ORDER BY trade_date LIMIT 1",
            (_as_date(after).isoformat(),)
        ).fetchone()
        if row:
            return str(row[0])
    for _ in range(max_ahead):
        if not is_closed(day):
            return day.isoformat()
        day += timedelta(days=1)
    return day.isoformat()
