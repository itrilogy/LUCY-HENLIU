"""
国信证券 HTTP 客户端 (gs)
基础地址: https://dgzt.guosen.com.cn/skills
认证方式: apiKey 查询参数
"""

import os
import json
import logging
from typing import Optional
from urllib.parse import urlencode
import urllib.request
import ssl

logger = logging.getLogger(__name__)

BASE_URL = "https://dgzt.guosen.com.cn/skills"
SOFT_NAME = "agent_skills"

# 国信服务器仅支持 legacy renegotiation（OpenSSL 3 默认拒绝）。
# 正确做法：保持证书验证，仅显式开启 OP_LEGACY_SERVER_CONNECT，而非禁用验证。
SSL_CTX = ssl.create_default_context()
try:
    SSL_CTX.options |= ssl.OP_LEGACY_SERVER_CONNECT
except AttributeError:
    pass


def _api_key() -> str:
    key = os.environ.get("GS_API_KEY")
    if not key:
        raise RuntimeError("GS_API_KEY 未配置，请写入 config/.env")
    return key


def _get(url: str, params: dict) -> dict:
    """GET 请求工具"""
    params["apiKey"] = _api_key()
    params["softName"] = SOFT_NAME
    full = f"{url}?{urlencode(params)}"
    try:
        with urllib.request.urlopen(full, context=SSL_CTX, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"GS API 请求失败: {url} → {e}")
        return {"result": [{"code": -1, "msg": str(e)}], "data": None}


# ── 财务 API ────────────────────────────────────

def query_income_stmt(code: str, market: str,
                      report_type: str = "Q0",
                      report_year: str = "",
                      count: str = "1") -> dict:
    """A股利润表"""
    url = f"{BASE_URL}/gsnews/gsf10/financial/incomeStatement/1.0"
    return _get(url, {"code": code, "market": market,
                       "reportType": report_type, "reportYear": report_year,
                       "count": count})


def query_balance_sheet(code: str, market: str,
                        report_type: str = "Q0",
                        report_year: str = "",
                        count: str = "1") -> dict:
    """A股资产负债表"""
    url = f"{BASE_URL}/gsnews/gsf10/financial/balanceSheet/1.0"
    return _get(url, {"code": code, "market": market,
                       "reportType": report_type, "reportYear": report_year,
                       "count": count})


def query_cashflow(code: str, market: str,
                   report_type: str = "Q0",
                   report_year: str = "",
                   count: str = "1") -> dict:
    """A股现金流量表"""
    url = f"{BASE_URL}/gsnews/gsf10/financial/cashFlowStatement/1.0"
    return _get(url, {"code": code, "market": market,
                       "reportType": report_type, "reportYear": report_year,
                       "count": count})


def query_hk_income_stmt(code: str, count: str = "1") -> dict:
    """港股利润表"""
    url = f"{BASE_URL}/gsnews/hkf10/financial/incomeStatement/1.0"
    return _get(url, {"code": code, "market": "HK", "count": count})


def query_hk_balance_sheet(code: str, count: str = "1") -> dict:
    """港股资产负债表"""
    url = f"{BASE_URL}/gsnews/hkf10/financial/balanceSheet/1.0"
    return _get(url, {"code": code, "market": "HK", "count": count})


def query_hk_cashflow(code: str, count: str = "1") -> dict:
    """港股现金流量表"""
    url = f"{BASE_URL}/gsnews/hkf10/financial/cashFlowStatement/1.0"
    return _get(url, {"code": code, "market": "HK", "count": count})


# ── 资金流向 API ───────────────────────────────

def query_fund_flow(code: str, set_code: int = 0, period: int = 10) -> dict:
    """查询资金流向"""
    url = f"{BASE_URL}/gsnews/market/agentbot/queryFundFlow/1.0"
    return _get(url, {"code": code, "setCode": str(set_code),
                       "period": str(period)})


# ── 财务字段提取工具 ────────────────────────────

def extract_financial_data(raw: dict) -> dict:
    """
    从国信 API 返回的 info 数组中提取关键财务指标
    返回结构化的 dict
    """
    result = {"revenue": None, "net_profit": None, "eps": None,
              "total_assets": None, "total_liab": None, "equity": None,
              "oper_cf": None, "roe": None, "gross_margin": None,
              "debt_ratio": None}
    info_list = raw.get("data", {}).get("info", [])
    for item in info_list:
        # 字段名在 item["key"] 中，值在 item["value"] 或 item["data"] 中
        pass  # 具体解析取决于国信 API 的实际返回格式
    return result


if __name__ == "__main__":
    import dotenv
    dotenv.load_dotenv("config/.env")
    r = query_income_stmt("600519", "SH", report_type="Q4", report_year="2024")
    print(json.dumps(r, ensure_ascii=False, indent=2)[:500])
