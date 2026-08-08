"""
财务报表全量同步脚本
来源：国信证券 gs_client
覆盖：最近 4 个报告期的利润表 + 资产负债表 + 现金流量表
用法：
    python3 src/sync_financial.py
"""

import sys, os, time, json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
from src.datasource.gs_client import (
    query_income_stmt, query_balance_sheet, query_cashflow
)

LOG = Path(__file__).parent.parent / "data" / "sync_fin.log"
DB = Path(__file__).parent.parent / "data" / "stock.db"

# 关键财务字段映射（国信API → 数据库）
INCOME_FIELDS = {
    "operatingRevenue": "revenue",
    "netProfit": "net_profit",
    "npParentCompanyOwners": "non_gaap_net",
    "basicEPS": "eps",
    "operatingCost": "cost",
    "grossProfit": "gross_profit",
}
BALANCE_FIELDS = {
    "totalAssets": "total_assets",
    "totalCurrentAssets": "current_assets",
    "totalLiabilities": "total_liab",
    "totalCurrentLiabilities": "current_liab",
    "totalEquity": "equity",
}
CASHFLOW_FIELDS = {
    "netOperateCashFlow": "oper_cf",
    "netInvestCashFlow": "invest_cf",
    "netFinanceCashFlow": "finance_cf",
}


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def extract(row: dict, field_map: dict) -> dict:
    """从API返回行中提取字段"""
    result = {}
    for api_key, db_key in field_map.items():
        val = row.get(api_key)
        if val and val not in ["", "0", "0.00"]:
            try:
                result[db_key] = float(val)
            except (ValueError, TypeError):
                result[db_key] = val
        else:
            result[db_key] = None
    return result


def guess_market(code: str) -> str:
    return "HK" if code.startswith("H") else "SH" if code.startswith("6") or code.startswith("68") else "SZ"


def main():
    log("=" * 50)
    log("🚀 财务报表全量同步")

    from src.db.schema import init_db
    init_db(str(DB))
    db = sqlite3.connect(str(DB))
    codes = [r[0] for r in db.execute(
        "SELECT DISTINCT stock_code FROM portfolio_stock").fetchall()]
    log(f"📋 待同步: {len(codes)} 只")

    total_income, total_balance, total_cf = 0, 0, 0
    skip_hk = 0

    for i, code in enumerate(codes, 1):
        if code.startswith("H"):
            log(f"  [{i}/{len(codes)}] {code}: 港股暂跳过")
            skip_hk += 1
            continue

        market = guess_market(code)

        # 利润表
        try:
            r = query_income_stmt(code, market, count="20")
            rows = r.get("income", [])
            ins = 0
            for row in rows:
                yr = row.get("year", "")
                if not yr: continue
                report_type = "Q4" if "-12-" in yr else "Q3" if "-09-" in yr else "Q2" if "-06-" in yr else "Q1"
                report_year = yr[:4]
                vals = extract(row, INCOME_FIELDS)
                if vals["revenue"] is None:
                    continue
                # 计算毛利率
                if vals["revenue"] and vals["cost"]:
                    vals["gross_margin"] = round((vals["revenue"] - vals["cost"]) / vals["revenue"] * 100, 2)
                db.execute("""INSERT OR REPLACE INTO financial_statement
                    (stock_code,market,report_type,report_year,report_date,
                     revenue,cost,gross_profit,net_profit,non_gaap_net,eps,gross_margin,
                     fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                    (code, market, report_type, report_year, yr,
                     vals.get("revenue"), vals.get("cost"),
                     vals.get("gross_profit"), vals.get("net_profit"),
                     vals.get("non_gaap_net"), vals.get("eps"),
                     vals.get("gross_margin")))
                ins += 1
            db.commit()
            total_income += ins
            log(f"  [{i}/{len(codes)}] {code}: 利润表 {ins} 期")
        except Exception as e:
            log(f"  [{i}/{len(codes)}] {code}: 利润表 ❌ {e}")

        # 资产负债表
        try:
            r = query_balance_sheet(code, market, count="20")
            rows = r.get("balance", [])
            ins = 0
            for row in rows:
                yr = row.get("year", "")
                if not yr: continue
                report_type = "Q4" if "-12-" in yr else "Q3" if "-09-" in yr else "Q2" if "-06-" in yr else "Q1"
                report_year = yr[:4]
                vals = extract(row, BALANCE_FIELDS)
                if vals["total_assets"] is None:
                    continue
                # 计算资产负债率
                debt_ratio = None
                if vals["total_liab"] and vals["total_assets"] and vals["total_assets"] > 0:
                    debt_ratio = round(vals["total_liab"] / vals["total_assets"] * 100, 2)
                # 更新到 financial_statement（UPSERT：无骨架行时自动建行）
                db.execute("""INSERT INTO financial_statement
                    (stock_code,market,report_type,report_year,
                     total_assets,current_assets,total_liab,current_liab,equity,debt_ratio,
                     fetched_at)
                    VALUES (?,?,?,?, ?,?,?,?,?,?, datetime('now'))
                    ON CONFLICT(stock_code, report_type, report_year) DO UPDATE SET
                      total_assets=excluded.total_assets,
                      current_assets=excluded.current_assets,
                      total_liab=excluded.total_liab,
                      current_liab=excluded.current_liab,
                      equity=excluded.equity,
                      debt_ratio=excluded.debt_ratio""",
                    (code, market, report_type, report_year,
                     vals["total_assets"], vals["current_assets"],
                     vals["total_liab"], vals["current_liab"],
                     vals["equity"], debt_ratio))
                ins += 1
            db.commit()
            total_balance += ins
            log(f"  [{i}/{len(codes)}] {code}: 资产负债表 {ins} 期")
        except Exception as e:
            log(f"  [{i}/{len(codes)}] {code}: 资产负债表 ❌ {e}")

        # 现金流量表
        try:
            r = query_cashflow(code, market, count="20")
            rows = r.get("cashFlow", [])
            ins = 0
            for row in rows:
                yr = row.get("year", "")
                if not yr: continue
                report_type = "Q4" if "-12-" in yr else "Q3" if "-09-" in yr else "Q2" if "-06-" in yr else "Q1"
                report_year = yr[:4]
                vals = extract(row, CASHFLOW_FIELDS)
                if vals["oper_cf"] is None:
                    continue
                db.execute("""INSERT INTO financial_statement
                    (stock_code,market,report_type,report_year,
                     oper_cf,invest_cf,finance_cf,
                     fetched_at)
                    VALUES (?,?,?,?, ?,?,?, datetime('now'))
                    ON CONFLICT(stock_code, report_type, report_year) DO UPDATE SET
                      oper_cf=excluded.oper_cf,
                      invest_cf=excluded.invest_cf,
                      finance_cf=excluded.finance_cf""",
                    (code, market, report_type, report_year,
                     vals["oper_cf"], vals["invest_cf"], vals["finance_cf"]))
                ins += 1
            db.commit()
            total_cf += ins
            log(f"  [{i}/{len(codes)}] {code}: 现金流量表 {ins} 期")
        except Exception as e:
            log(f"  [{i}/{len(codes)}] {code}: 现金流量表 ❌ {e}")

    db.close()
    log(f"✅ 完成: 利润表 {total_income} 条 / 资产负债表 {total_balance} 条 / 现金流量表 {total_cf} 条")
    log(f"   港股跳过: {skip_hk} 只")
    log("=" * 50)


if __name__ == "__main__":
    main()
