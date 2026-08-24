"""
同步门面：行情 / K 线 / 分时 / 财务 / 宏观 / 拥挤度 / 资金流 / 预测。
CLI 与 UI 共用，禁止再复制 INSERT 语句。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime

from src.service.codes import build_code_map, guess_market, remap_code
from src.datasource.ratelimit import GS_QUOTA_CODE, QuotaExceededError

logger = logging.getLogger(__name__)

QUOTE_KEEP = 5


@dataclass
class StepResult:
    name: str
    ok: bool = True
    inserted: int = 0
    updated: int = 0
    fetched: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)
    message: str = ""

    def line(self) -> str:
        status = "✅" if self.ok else "❌"
        extra = self.message or f"写入 {self.inserted}"
        if self.errors:
            extra += f" / 错 {len(self.errors)}"
        return f"{status} {self.name}: {extra}"


def _codes(db: sqlite3.Connection, a_share_only: bool = False) -> list[str]:
    sql = "SELECT stock_code FROM portfolio_stock"
    if a_share_only:
        sql += " WHERE stock_code NOT LIKE 'H%'"
    return [r[0] for r in db.execute(sql)]


def _gs_failed(raw) -> bool:
    if not isinstance(raw, dict):
        return False
    result = raw.get("result")
    if isinstance(result, list) and result:
        code = result[0].get("code")
        return code in (GS_QUOTA_CODE, -1)
    return False


def prune_quotes(db: sqlite3.Connection, keep: int = QUOTE_KEEP) -> int:
    """每只股票只保留最近 keep 条行情快照。"""
    deleted = 0
    codes = [r[0] for r in db.execute(
        "SELECT DISTINCT stock_code FROM real_time_quote")]
    for code in codes:
        ids = [r[0] for r in db.execute(
            "SELECT id FROM real_time_quote WHERE stock_code=? "
            "ORDER BY fetched_at DESC, id DESC", (code,))]
        extra = ids[keep:]
        if extra:
            db.execute(
                f"DELETE FROM real_time_quote WHERE id IN ({','.join('?' * len(extra))})",
                extra)
            deleted += len(extra)
    db.commit()
    return deleted


def sync_quotes(db: sqlite3.Connection, codes: list[str] | None = None) -> StepResult:
    from src.datasource.sdicsc_client import get_batch_quote, quote_to_db_row
    codes = codes or _codes(db)
    r = StepResult(name="行情")
    if not codes:
        r.message = "无自选股"
        return r
    code_map = build_code_map(codes)
    try:
        raw_list = get_batch_quote(codes)
    except Exception as e:
        r.ok = False
        r.errors.append(str(e))
        r.message = str(e)
        return r
    r.fetched = len(raw_list)
    known = {c.lower(): c for c in codes}
    for raw in raw_list:
        sc = raw.get("stockCode") or raw.get("code") or ""
        orig = remap_code(sc, code_map)
        if orig.lower() not in known:
            continue
        orig = known[orig.lower()]
        row = quote_to_db_row(raw, orig)
        db.execute(
            """INSERT INTO real_time_quote(
                stock_code,price,change_amt,change_pct,prev_close,
                open,high,low,avg_price,volume,amount,turnover,
                amplitude,volume_ratio,pe,pe_dynamic,pe_ttm,
                market_value,circ_market_val,change_5d,change_20d,
                change_60d,change_120d,change_250d,susp_flag,
                trade_date,trade_time,fetched_at)
               VALUES (:stock_code,:price,:change_amt,:change_pct,:prev_close,
                :open,:high,:low,:avg_price,:volume,:amount,:turnover,
                :amplitude,:volume_ratio,:pe,:pe_dynamic,:pe_ttm,
                :market_value,:circ_market_val,:change_5d,:change_20d,
                :change_60d,:change_120d,:change_250d,:susp_flag,
                :trade_date,:trade_time,datetime('now','localtime'))""",
            row)
        r.inserted += 1
    prune_quotes(db)
    db.commit()
    r.message = f"{r.inserted}/{len(codes)} 条"
    return r


_KLINE_UPSERT = """
INSERT INTO kline_day(stock_code,trade_date,open,high,low,close,volume,amount)
VALUES (?,?,?,?,?,?,?,?)
ON CONFLICT(stock_code, trade_date) DO UPDATE SET
  open=excluded.open, high=excluded.high, low=excluded.low,
  close=excluded.close, volume=excluded.volume, amount=excluded.amount
"""


def sync_kline(db: sqlite3.Connection, codes: list[str] | None = None,
               days: int = 120) -> StepResult:
    from src.datasource.sdicsc_client import get_kline
    codes = codes if codes is not None else _codes(db, a_share_only=False)
    r = StepResult(name="K线")
    for code in codes:
        try:
            klines = get_kline(code, "day", days)
            if not isinstance(klines, list):
                klines = (klines or {}).get("kLineData") or []
            r.fetched += len(klines)
            for k in klines:
                cur = db.execute(
                    _KLINE_UPSERT,
                    (code, k["time"], k["open"], k["high"], k["low"],
                     k["close"], k.get("volume", 0), k.get("amount", 0)))
                if cur.rowcount > 0:
                    r.inserted += 1
            db.commit()
        except Exception as e:
            logger.warning("K线 %s: %s", code, e)
            r.errors.append(f"{code}: {e}")
    r.ok = not r.errors or r.inserted > 0
    r.message = f"{r.inserted} 条 ({len(codes)} 只)"
    return r


def sync_trend(db: sqlite3.Connection, codes: list[str] | None = None) -> StepResult:
    from src.datasource.sdicsc_client import get_trend
    codes = codes if codes is not None else [
        c for c in _codes(db) if not c.upper().startswith("H")]
    r = StepResult(name="分时")
    for code in codes:
        try:
            raw = get_trend(code)
            td = raw.get("timeData") or []
            date = (raw.get("meta") or {}).get("date") or ""
            r.fetched += len(td)
            for t in td:
                cur = db.execute(
                    """INSERT OR IGNORE INTO trend_data
                       (stock_code,trade_date,time_seq,price,avg_price,
                        volume,change_amt,change_pct)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (code, date, t["time"], t["price"], t.get("avgPrice"),
                     t.get("volume", 0), t.get("change", 0),
                     t.get("changePercent", "")))
                if cur.rowcount > 0:
                    r.inserted += 1
            db.commit()
        except Exception as e:
            logger.warning("分时 %s: %s", code, e)
            r.errors.append(f"{code}: {e}")
    r.ok = not r.errors or r.inserted > 0 or r.fetched >= 0
    r.message = f"{r.inserted} 点"
    return r


def _num(row: dict, key: str):
    v = row.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _period(year_str: str) -> tuple[str, str] | None:
    yr = year_str or ""
    if not yr:
        return None
    rt = ("Q4" if "-12-" in yr else "Q3" if "-09-" in yr
          else "Q2" if "-06-" in yr else "Q1")
    return rt, yr[:4]


def sync_financial(db: sqlite3.Connection, codes: list[str] | None = None) -> StepResult:
    from src.datasource.gs_client import (
        query_income_stmt, query_balance_sheet, query_cashflow,
    )
    codes = codes if codes is not None else [
        c for c in _codes(db) if not c.upper().startswith("H")]
    r = StepResult(name="财务")
    for code in codes:
        market = guess_market(code)
        try:
            income = query_income_stmt(code, market, count="20")
            if _gs_failed(income):
                r.ok = False
                r.message = "国信限额/熔断"
                r.errors.append(r.message)
                return r
            balance = query_balance_sheet(code, market, count="20")
            cashflow = query_cashflow(code, market, count="20")
            if _gs_failed(balance) or _gs_failed(cashflow):
                r.ok = False
                r.message = "国信限额/熔断"
                r.errors.append(r.message)
                return r

            by_key: dict[tuple[str, str], dict] = {}

            def acc(rows, mapper):
                for row in rows or []:
                    p = _period(row.get("year", ""))
                    if not p:
                        continue
                    by_key.setdefault(p, {}).update(mapper(row))

            acc(income.get("income") or [], lambda row: {
                "revenue": _num(row, "operatingRevenue"),
                "cost": _num(row, "operatingCost"),
                "gross_profit": _num(row, "grossProfit"),
                "net_profit": _num(row, "netProfit"),
                "non_gaap_net": _num(row, "npParentCompanyOwners"),
                "eps": _num(row, "basicEPS"),
            })
            acc(balance.get("balance") or [], lambda row: {
                "total_assets": _num(row, "totalAssets"),
                "current_assets": _num(row, "totalCurrentAssets"),
                "total_liab": _num(row, "totalLiabilities"),
                "current_liab": _num(row, "totalCurrentLiabilities"),
                "equity": _num(row, "totalEquity"),
            })
            acc(cashflow.get("cashFlow") or [], lambda row: {
                "oper_cf": _num(row, "netOperateCashFlow"),
                "invest_cf": _num(row, "netInvestCashFlow"),
                "finance_cf": _num(row, "netFinanceCashFlow"),
            })

            db.execute("BEGIN")
            for (rt, year), vals in by_key.items():
                rev, cost = vals.get("revenue"), vals.get("cost")
                gross_margin = (
                    round((rev - cost) / rev * 100, 2)
                    if rev and cost is not None and rev != 0 else None)
                ta, tl = vals.get("total_assets"), vals.get("total_liab")
                debt_ratio = (
                    round(tl / ta * 100, 2)
                    if ta and tl is not None and ta != 0 else None)
                eq, np_ = vals.get("equity"), vals.get("net_profit")
                roe = (round(np_ / eq * 100, 2)
                       if np_ is not None and eq else None)
                db.execute(
                    """INSERT INTO financial_statement
                       (stock_code,market,report_type,report_year,report_date,
                        revenue,cost,gross_profit,net_profit,non_gaap_net,eps,
                        gross_margin,total_assets,current_assets,total_liab,
                        current_liab,equity,debt_ratio,roe,
                        oper_cf,invest_cf,finance_cf,fetched_at)
                       VALUES (?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?, datetime('now','localtime'))
                       ON CONFLICT(stock_code, report_type, report_year) DO UPDATE SET
                         report_date=COALESCE(excluded.report_date, report_date),
                         revenue=COALESCE(excluded.revenue, revenue),
                         cost=COALESCE(excluded.cost, cost),
                         gross_profit=COALESCE(excluded.gross_profit, gross_profit),
                         net_profit=COALESCE(excluded.net_profit, net_profit),
                         non_gaap_net=COALESCE(excluded.non_gaap_net, non_gaap_net),
                         eps=COALESCE(excluded.eps, eps),
                         gross_margin=COALESCE(excluded.gross_margin, gross_margin),
                         total_assets=COALESCE(excluded.total_assets, total_assets),
                         current_assets=COALESCE(excluded.current_assets, current_assets),
                         total_liab=COALESCE(excluded.total_liab, total_liab),
                         current_liab=COALESCE(excluded.current_liab, current_liab),
                         equity=COALESCE(excluded.equity, equity),
                         debt_ratio=COALESCE(excluded.debt_ratio, debt_ratio),
                         roe=COALESCE(excluded.roe, roe),
                         oper_cf=COALESCE(excluded.oper_cf, oper_cf),
                         invest_cf=COALESCE(excluded.invest_cf, invest_cf),
                         finance_cf=COALESCE(excluded.finance_cf, finance_cf),
                         fetched_at=excluded.fetched_at""",
                    (code, market, rt, year, None,
                     rev, cost, vals.get("gross_profit"), np_,
                     vals.get("non_gaap_net"), vals.get("eps"),
                     gross_margin, ta, vals.get("current_assets"), tl,
                     vals.get("current_liab"), eq, debt_ratio, roe,
                     vals.get("oper_cf"), vals.get("invest_cf"),
                     vals.get("finance_cf")))
                r.inserted += 1
            db.commit()
            time.sleep(0.3)
        except QuotaExceededError as e:
            r.ok = False
            r.message = str(e)
            r.errors.append(str(e))
            try:
                db.rollback()
            except sqlite3.Error:
                pass
            return r
        except Exception as e:
            logger.warning("财务 %s: %s", code, e)
            r.errors.append(f"{code}: {e}")
            try:
                db.rollback()
            except sqlite3.Error:
                pass
    r.ok = not r.errors or r.inserted > 0
    r.message = r.message or f"{r.inserted} 期"
    return r


def sync_macro_articles(db: sqlite3.Connection) -> StepResult:
    from src.datasource.gs_client import query_macro
    queries = [
        ("中国GDP同比增速", "宏观·GDP"),
        ("中国CPI同比 2024年至2025年变化", "宏观·CPI"),
        ("中国PPI同比 2024年至2025年变化", "宏观·PPI"),
        ("中国M2同比增速 2024年至2025年趋势", "宏观·M2"),
        ("中国制造业PMI 2024年至2025年走势", "宏观·PMI"),
        ("中国LPR利率 2024年至2025年调整历史", "宏观·LPR"),
        ("美国CPI同比 2024年至2025年", "宏观·美国CPI"),
        ("美国联邦基准利率 2024年至2025年变化", "宏观·美联储"),
    ]
    r = StepResult(name="宏观文章")
    for query, cat in queries:
        try:
            raw = query_macro(query)
            if _gs_failed(raw):
                r.ok = False
                r.message = "国信限额/熔断"
                r.errors.append(r.message)
                return r
            content = ""
            for item in raw.get("data") or []:
                if isinstance(item, dict) and item.get("type") == "STREAM_MESSAGE":
                    content += item.get("content") or ""
            if content and len(content) > 50:
                db.execute(
                    "INSERT OR REPLACE INTO research_article"
                    "(category,title,content,source) VALUES(?,?,?,?)",
                    (cat, query, content[:5000], "国信证券AI"))
                db.commit()
                r.inserted += 1
            time.sleep(1)
        except QuotaExceededError as e:
            r.ok = False
            r.message = str(e)
            r.errors.append(str(e))
            return r
        except Exception as e:
            r.errors.append(f"{query[:20]}: {e}")
    r.message = f"{r.inserted}/{len(queries)} 篇"
    r.ok = not r.errors or r.inserted > 0
    return r


def sync_smart_picks(db: sqlite3.Connection) -> StepResult:
    from src.datasource.gs_client import query_smart_picks
    queries = [
        ("市盈率小于15且ROE大于15%的股票", "低估值优质"),
        ("主力资金净流入的股票", "资金流入"),
        ("今日涨幅大于3%的股票", "强势股"),
    ]
    r = StepResult(name="智能选股")
    for query, tag in queries:
        try:
            data = query_smart_picks(query)
            if _gs_failed(data):
                r.ok = False
                r.message = "国信限额/熔断"
                r.errors.append(r.message)
                return r
            for tbl in data.get("data") or []:
                table_data = tbl.get("table") or {}
                codes = table_data.get("股票代码") or []
                names = table_data.get("股票简称") or []
                if codes and names:
                    db.execute(
                        "INSERT OR REPLACE INTO research_article"
                        "(category,title,content,source) VALUES(?,?,?,?)",
                        (f"选股·{tag}", query,
                         json.dumps({"codes": codes[:20], "names": names[:20]},
                                    ensure_ascii=False)[:5000],
                         "国投证券智能选股"))
                    db.commit()
                    r.inserted += len(codes[:20])
            time.sleep(1)
        except QuotaExceededError as e:
            r.ok = False
            r.message = str(e)
            r.errors.append(str(e))
            return r
        except Exception as e:
            r.errors.append(f"{tag}: {e}")
    r.message = f"{r.inserted} 只推荐"
    r.ok = True
    return r


def sync_crowding(db: sqlite3.Connection) -> StepResult:
    """行业拥挤度 → sector_crowding（不再写入 research_article）。"""
    import os
    from src.datasource.sdicsc_client import query_crowding

    r = StepResult(name="拥挤度")
    key = os.environ.get("GT_CROWDING_DEGREE_API_KEY") or os.environ.get("GT_ZNXG_KEY")
    if not key:
        r.message = "跳过(无Key)"
        return r
    targets = [
        ("h30255.CSI", "医药"),
        ("399976.CSI", "证券公司"),
        ("h30186.CSI", "保险"),
        ("950096.CSI", "上海国企"),
        ("399319.SZ", "资源"),
        ("h30217.CSI", "医疗器械"),
    ]
    for code, name in targets:
        try:
            cd = query_crowding(code)
            if not cd:
                continue
            calc_time = str(cd.get("calcTime") or "")
            calc_date = calc_time[:10] if calc_time else datetime.now().strftime("%Y-%m-%d")
            row = {}
            for period_key, prefix in (("d5", "d5"), ("d20", "d20")):
                pd_data = cd.get(period_key) or {}
                for src_key, db_key in (
                    ("amountRatio", "amount"),
                    ("totalMarketValueRatio", "market_val"),
                    ("turnoverRatio", "turnover"),
                ):
                    stats = (pd_data.get(src_key) or {}).get("stats") or {}
                    row[f"{prefix}_{db_key}_now"] = stats.get("now")
                    row[f"{prefix}_{db_key}_quantile"] = stats.get("quantile")
            db.execute(
                """INSERT OR REPLACE INTO sector_crowding
                   (sector_code, sector_name, calc_date,
                    d5_amount_now, d5_amount_quantile,
                    d5_market_val_now, d5_market_val_quantile,
                    d5_turnover_now, d5_turnover_quantile,
                    d20_amount_now, d20_amount_quantile,
                    d20_market_val_now, d20_market_val_quantile,
                    d20_turnover_now, d20_turnover_quantile, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                (code, name, calc_date,
                 row.get("d5_amount_now"), row.get("d5_amount_quantile"),
                 row.get("d5_market_val_now"), row.get("d5_market_val_quantile"),
                 row.get("d5_turnover_now"), row.get("d5_turnover_quantile"),
                 row.get("d20_amount_now"), row.get("d20_amount_quantile"),
                 row.get("d20_market_val_now"), row.get("d20_market_val_quantile"),
                 row.get("d20_turnover_now"), row.get("d20_turnover_quantile")))
            db.commit()
            r.inserted += 1
            time.sleep(0.3)
        except Exception as e:
            r.errors.append(f"{code}: {e}")
    r.message = f"{r.inserted} 个行业"
    r.ok = not r.errors or r.inserted > 0
    return r


def sync_macro_indicators(db: sqlite3.Connection) -> StepResult:
    """结构化宏观数值。数值提取失败不写库，避免把年份当指标。"""
    import re
    from src.datasource.gs_client import query_macro
    indicators = [
        ("中国GDP同比增速 最新数据", "GDP_CN"),
        ("中国CPI同比 最新", "CPI_CN"),
        ("中国PPI同比 最新", "PPI_CN"),
        ("中国M2同比增速 最新", "M2_CN"),
        ("中国制造业PMI 最新", "PMI_CN"),
        ("中国LPR1年期 最新", "LPR_1Y"),
        ("中国LPR5年期 最新", "LPR_5Y"),
        ("美国CPI同比 最新", "CPI_US"),
        ("美国联邦基准利率 最新", "FED_RATE"),
    ]
    r = StepResult(name="宏观指标")
    period = datetime.now().strftime("%Y-%m")
    for query, code in indicators:
        try:
            raw = query_macro(query)
            if _gs_failed(raw):
                r.ok = False
                r.message = "国信限额/熔断"
                r.errors.append(r.message)
                return r
            value = None
            for item in raw.get("data") or []:
                if not (isinstance(item, dict) and item.get("type") == "STREAM_MESSAGE"):
                    continue
                text = item.get("content") or ""
                # 跳过纯年份（2010-2099 的四位数）作为唯一数字的情况
                nums = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
                for n in nums:
                    try:
                        v = float(n)
                    except ValueError:
                        continue
                    if 1900 <= v <= 2100 and v == int(v):
                        continue
                    value = v
                    break
                if value is not None:
                    break
            if value is not None:
                db.execute(
                    "INSERT OR REPLACE INTO macro_indicator"
                    "(indicator_code,period,value,fetched_at) VALUES(?,?,?,datetime('now','localtime'))",
                    (code, period, value))
                db.commit()
                r.inserted += 1
            time.sleep(1)
        except QuotaExceededError as e:
            r.ok = False
            r.message = str(e)
            r.errors.append(str(e))
            return r
        except Exception as e:
            r.errors.append(f"{code}: {e}")
    r.message = f"{r.inserted}/{len(indicators)}"
    r.ok = not r.errors or r.inserted > 0
    return r


def sync_fund_flow(db: sqlite3.Connection) -> StepResult:
    from src.datasource.gs_client import query_fund_flow
    codes = [r[0] for r in db.execute(
        "SELECT stock_code FROM portfolio_stock "
        "WHERE is_holding=1 AND stock_code NOT LIKE 'H%'")]
    r = StepResult(name="资金流向")
    if not codes:
        r.message = "无持仓股"
        return r
    for code in codes:
        try:
            set_code = 1 if guess_market(code) == "SH" else 0
            data = query_fund_flow(code, set_code=set_code, period=30)
            if _gs_failed(data):
                r.ok = False
                r.message = "国信限额/熔断"
                r.errors.append(r.message)
                return r
            items = ((data.get("data") or {}).get("items")) or []
            r.fetched += len(items)
            for item in items:
                cur = db.execute(
                    """INSERT OR IGNORE INTO fund_flow
                       (stock_code,trade_date,main_force_net,fetched_at)
                       VALUES (?,?,?,datetime('now','localtime'))""",
                    (code, item.get("date", ""), item.get("net_mf_amount", 0)))
                if cur.rowcount > 0:
                    r.inserted += 1
            db.commit()
            time.sleep(0.5)
        except QuotaExceededError as e:
            r.ok = False
            r.message = str(e)
            r.errors.append(str(e))
            return r
        except Exception as e:
            r.errors.append(f"{code}: {e}")
    r.message = f"{r.inserted} 条 / {len(codes)} 只"
    r.ok = not r.errors or r.inserted > 0
    return r


def sync_predictions(db: sqlite3.Connection) -> StepResult:
    from src.quant.prediction_loop import run_prediction_loop
    r = StepResult(name="预测闭环")
    try:
        out = run_prediction_loop(db)
        r.inserted = out.get("predicted", 0)
        r.updated = out.get("settled", 0)
        r.skipped = out.get("skipped", 0)
        r.message = (
            f"结算 {out['settled']} / 新预测 {out['predicted']} / 跳过 {out['skipped']}")
    except Exception as e:
        r.ok = False
        r.message = str(e)
        r.errors.append(str(e))
    return r


def persist_coverage(db: sqlite3.Connection) -> StepResult:
    from src.service.coverage import compute_coverage
    r = StepResult(name="覆盖率")
    rows = compute_coverage(db, persist=True)
    r.inserted = len(rows)
    r.message = f"{len(rows)} 只"
    return r


def write_sync_log(db: sqlite3.Connection, status: str,
                   inserted: int, duration_ms: int, errors: str | None = None) -> None:
    db.execute(
        """INSERT INTO sync_log
           (data_type,source,sync_mode,rows_inserted,status,duration_ms,errors)
           VALUES ('daily_sync','auto','daily',?,?,?,?)""",
        (inserted, status, duration_ms, errors))
    db.commit()


def run_daily(db: sqlite3.Connection, *, quick: bool = False) -> dict:
    """
    一键同步。返回 {ok, status, steps, logs, duration, failed}。
    status: success / partial / failed
    """
    t0 = time.time()
    steps: list[StepResult] = []
    logs: list[str] = []

    def run(fn, *a, **kw) -> StepResult:
        res = fn(db, *a, **kw)
        steps.append(res)
        logs.append(res.line())
        logger.info(res.line())
        return res

    run(sync_quotes)
    run(sync_kline, days=5 if quick else 120)
    run(sync_trend, codes=(_codes(db, a_share_only=True)[:3] if quick else None))
    run(sync_predictions)
    if not quick:
        run(sync_financial)
        run(sync_macro_articles)
        run(sync_smart_picks)
        run(sync_crowding)
        run(sync_macro_indicators)
        run(sync_fund_flow)
    run(persist_coverage)

    duration = time.time() - t0
    failed = [s for s in steps if not s.ok]
    hard_fail = any(
        s.name in ("行情",) and not s.ok for s in steps
    )
    if hard_fail or (failed and all(not s.ok for s in steps)):
        status = "failed"
    elif failed:
        status = "partial"
    else:
        status = "success"
    err_txt = json.dumps(
        [{"name": s.name, "errors": s.errors, "msg": s.message} for s in failed],
        ensure_ascii=False) if failed else None
    write_sync_log(db, status, sum(s.inserted for s in steps),
                   int(duration * 1000), err_txt)
    return {
        "ok": status == "success",
        "status": status,
        "steps": steps,
        "logs": logs,
        "duration": round(duration, 1),
        "failed": [s.name for s in failed],
    }
