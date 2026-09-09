"""
兼容层。旧 DailySyncScheduler / KlineSyncService 已由
scheduler.py + pipeline 取代；日历工具迁至 calendar.py。
"""
from src.service.calendar import (  # noqa: F401
    get_trade_days, generate_default_calendar, ensure_calendar,
    is_trading_day, next_open_date,
)
from src.service.pipeline import (  # noqa: F401
    sync_quotes, sync_kline, sync_trend, sync_financial, run_daily,
)
