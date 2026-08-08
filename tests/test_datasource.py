"""数据源客户端字段映射测试（不发起网络请求）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.datasource.sdicsc_client import quote_to_db_row


def test_quote_to_db_row_maps_fields():
    raw = {
        "code": "000037",
        "name": "深南电A",
        "price": 10.5,
        "change": 0.2,              # 国投字段：change / changePercent / prevClose
        "changePercent": 1.94,
        "prevClose": 10.3,
        "open": 10.4,
        "high": 10.6,
        "low": 10.2,
        "volume": 123456,
        "amount": 1.29e7,
        "turnover": 1.5,
        "volumeRatio": 1.1,
        "pe": 20.0,
        "peDynamic": 18.0,
        "peTtm": 19.0,
        "totalMarketValue": 105.2,
        "change20": 3.1,
        "change60": -2.4,
        "suspFlag": 0,
    }
    row = quote_to_db_row(raw, "000037")
    assert row["stock_code"] == "000037"
    assert row["price"] == 10.5
    assert row["change_amt"] == 0.2
    assert row["change_pct"] == "1.94"
    assert row["prev_close"] == 10.3
    assert row["volume"] == "123456"
    assert row["pe"] == 20.0
    assert row["pe_dynamic"] == 18.0
    assert row["pe_ttm"] == 19.0
    assert row["market_value"] == "105.2"
    assert row["change_20d"] == "3.1"
    assert row["trade_date"]  # 非空（fetched_at 由 SQL 侧 datetime('now') 生成，不在映射中）


def test_quote_to_db_row_handles_missing_keys():
    row = quote_to_db_row({}, "000037")
    assert row["stock_code"] == "000037"
    assert row["change_pct"] == "0%"
    assert row["price"] == 0
