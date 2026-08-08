"""
国投证券行情 HTTP 客户端 (sdicsc)
基础地址: https://skills.sdicsc.com.cn/skill/hq
认证方式: X-API-Key Header
"""

import os
import json
import time
import logging
from typing import List, Optional
from datetime import datetime

import httpx

try:
    from src.datasource.ratelimit import api_call, APIError, RetryableError
except ImportError:
    from ratelimit import api_call, APIError, RetryableError

logger = logging.getLogger(__name__)

BASE_URL = "https://skills.sdicsc.com.cn/skill/hq"

# ── 市场代码映射（国投格式） ────────────────────
MARKET_PREFIX = {
    "SH": "sh", "SZ": "sz", "BJ": "bj", "HK": "hk"
}


def _api_key() -> str:
    key = os.environ.get("GT_ZNXG_KEY") or os.environ.get("GT_API_KEY")
    if not key:
        raise RuntimeError("GT_ZNXG_KEY 未配置，请写入 config/.env")
    return key


def _headers() -> dict:
    return {"X-API-Key": _api_key()}


def _normalize_code(code: str) -> str:
    """统一代码格式：600519 → sh600519"""
    # 如果已有前缀，直接返回
    if any(code.startswith(p) for p in ["sh", "sz", "bj", "hk", "SH", "SZ", "BJ", "HK"]):
        return code.lower()
    # H 股
    if code.startswith("H") or code.startswith("h"):
        return f"hk{code.lstrip('Hh')}"
    return code


# ── 行情 API ────────────────────────────────────

def _request_json(method: str, url: str, **kwargs) -> dict:
    """带指数退避重试的 JSON 请求（国投 429 瞬时限流自动重试）"""
    def do_request() -> dict:
        try:
            resp = httpx.request(method, url, **kwargs)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code in (429, 502, 503, 504):
                raise RetryableError(f"HTTP {code} {url}")
            raise APIError(f"HTTP {code} {url}")
        except httpx.TimeoutException as e:
            raise RetryableError(f"超时 {url} → {e}")
        return resp.json()
    return api_call(do_request, breaker_key="sdicsc")


def get_quote(code: str) -> dict:
    """
    获取单只股票实时行情
    GET /api/quote/:code
    """
    code = _normalize_code(code)
    url = f"{BASE_URL}/api/quote/{code}"
    data = _request_json("GET", url, headers=_headers(), timeout=10)
    return data.get("data") or data


def get_batch_quote(codes: List[str]) -> List[dict]:
    """
    批量获取实时行情（自选股列表刷新）
    POST /api/quote/batch
    """
    normalized = [_normalize_code(c) for c in codes]
    url = f"{BASE_URL}/api/quote/batch"
    data = _request_json("POST", url, headers=_headers(),
                         json={"codes": normalized}, timeout=15)
    return data.get("data", [])


# ── K线 API ─────────────────────────────────────

def get_kline(code: str, ktype: str = "day", count: int = 120) -> List[dict]:
    """
    获取K线数据
    GET /api/kline/:code?type=day&count=120
    ktype: day / week / month / year / 1min / 5min / 15min / 30min / 60min
    """
    code = _normalize_code(code)
    url = f"{BASE_URL}/api/kline/{code}"
    data = _request_json("GET", url, headers=_headers(),
                         params={"type": ktype, "count": count}, timeout=15)
    return data.get("kLineData", data.get("data", []))


# ── 分时 API ────────────────────────────────────

def get_trend(code: str) -> dict:
    """获取分时数据 GET /api/trend/:code"""
    code = _normalize_code(code)
    url = f"{BASE_URL}/api/trend/{code}"
    data = _request_json("GET", url, headers=_headers(), timeout=10)
    return data.get("data", {})


# ── 排名 API ────────────────────────────────────

def get_rank(sort: str = "changePercent", order: str = "desc",
             market: str = "", count: int = 20) -> List[dict]:
    """
    获取涨幅排名
    GET /api/rank/stock
    """
    params = {"sort": sort, "order": order, "count": count}
    if market:
        params["market"] = market
    url = f"{BASE_URL}/api/rank/stock"
    data = _request_json("GET", url, headers=_headers(), params=params, timeout=10)
    return data.get("data", [])


# ── 行情字段映射（国投→数据库） ─────────────────

def quote_to_db_row(raw: dict, db_code: str) -> dict:
    """将国投 API 返回的行情字段映射为数据库 real_time_quote 行"""
    return {
        "stock_code": db_code,
        "price": raw.get("price", 0),
        "change_amt": raw.get("change", 0),
        "change_pct": str(raw.get("changePercent", "0%")),
        "prev_close": raw.get("prevClose", 0),
        "open": raw.get("open"),
        "high": raw.get("high"),
        "low": raw.get("low"),
        "avg_price": raw.get("avgPrice"),
        "volume": str(raw.get("volume", "")),
        "amount": str(raw.get("amount", "")),
        "turnover": str(raw.get("turnover", "")),
        "amplitude": str(raw.get("amplitude", "")),
        "volume_ratio": raw.get("volumeRatio"),
        "outside": str(raw.get("outside", "")),
        "inside": str(raw.get("inside", "")),
        "pe": raw.get("pe"),
        "pe_dynamic": raw.get("peDynamic") or raw.get("pe_dynamic"),
        "pe_ttm": raw.get("peTtm") or raw.get("peTTM") or raw.get("pe_ttm"),
        "market_value": str(raw.get("totalMarketValue", raw.get("marketValue", ""))),
        "circ_market_val": str(raw.get("circulationMarketValue", raw.get("circ_market_val", ""))),
        "change_5d": str(raw.get("change5", "")),
        "change_20d": str(raw.get("change20", "")),
        "change_60d": str(raw.get("change60", "")),
        "change_120d": str(raw.get("change120", "")),
        "change_250d": str(raw.get("change250", "")),
        "change_ytd": str(raw.get("changeThisYear", "")),
        "change_month": str(raw.get("changeThisMonth", "")),
        "change_week": str(raw.get("changeThisWeek", "")),
        "susp_flag": str(raw.get("suspFlag", "")),
        "trade_date": datetime.now().strftime("%Y-%m-%d"),
        "trade_time": datetime.now().strftime("%H:%M:%S"),
    }


# ── 健康检查 ────────────────────────────────────

def health_check() -> bool:
    """检查 API 是否可用（用行情接口验证）"""
    try:
        resp = httpx.get(f"{BASE_URL}/api/quote/sh600519",
                         headers=_headers(), timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


if __name__ == "__main__":
    # 简单测试
    import dotenv
    dotenv.load_dotenv("config/.env")
    ok = health_check()
    print(f"健康检查: {'✅' if ok else '❌'}")
    if ok:
        q = get_quote("sh600519")
        print(f"贵州茅台: {json.dumps(quote_to_db_row(q, '600519'), ensure_ascii=False, indent=2)}")
