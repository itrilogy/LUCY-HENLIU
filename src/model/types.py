"""共享数据类（报价/同步结果等）。"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QuoteRow:
    stock_code: str
    price: float
    change_amt: float
    change_pct: str
    prev_close: float
    trade_date: str
    trade_time: str
