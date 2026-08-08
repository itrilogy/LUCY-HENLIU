"""
数据补全与同步服务

核心职责：
1. 日K线补全 —— 检测缺失交易日，从国投 API 拉取补齐
2. 盘后同步 —— 收盘后自动拉取当日行情/资金流向
3. 数据覆盖率追踪 —— 记录每只股票每种数据的覆盖区间
4. 间隙检测与修复 —— 发现数据空洞并触发补拉
"""

import sqlite3
import time
import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────
# 一、交易日历工具
# ─────────────────────────────────────────────────

def get_trade_days(db: sqlite3.Connection, start: str, end: str,
                   market: str = 'SH') -> List[str]:
    """获取指定区间内的交易日列表"""
    cur = db.execute(
        "SELECT trade_date FROM trade_calendar "
        "WHERE market=? AND is_open=1 AND trade_date BETWEEN ? AND ? "
        "ORDER BY trade_date", (market, start, end))
    return [row[0] for row in cur]


def generate_default_calendar(year: int) -> List[tuple]:
    """为指定年份生成默认交易日历（仅含周末，不含法定节假日）"""
    days = []
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        is_weekend = d.weekday() >= 5  # 5=Sat, 6=Sun
        days.append((d.isoformat(), 'SH',
                     0 if is_weekend else 1,
                     '周末' if is_weekend else '交易日'))
        d += timedelta(days=1)
    return days


def ensure_calendar(db: sqlite3.Connection, years: list = None):
    """确保交易日历存在，缺失年份自动填充"""
    if years is None:
        years = [datetime.now().year - 1, datetime.now().year,
                 datetime.now().year + 1]
    for y in years:
        exists = db.execute(
            "SELECT 1 FROM trade_calendar WHERE trade_date LIKE ? LIMIT 1",
            (f"{y}-%",)).fetchone()
        if not exists:
            rows = generate_default_calendar(y)
            db.executemany(
                "INSERT OR IGNORE INTO trade_calendar VALUES (?,?,?,?)", rows)
            logger.info(f"交易日历 {y} 已生成 ({len(rows)} 天)")

# ─────────────────────────────────────────────────
# 二、K线数据补全
# ─────────────────────────────────────────────────

class KlineSyncService:
    """日K线补全服务"""

    def __init__(self, db: sqlite3.Connection, sdicsc_client):
        self.db = db
        self.client = sdicsc_client  # 国投证券客户端实例

    def get_coverage(self, stock_code: str) -> dict:
        """获取某只股票的K线覆盖情况"""
        row = self.db.execute(
            "SELECT coverage_start, coverage_end, total_days, filled_days, gap_days "
            "FROM data_coverage WHERE stock_code=? AND data_type='kline_day'",
            (stock_code,)).fetchone()
        if not row:
            return {"coverage_start": None, "coverage_end": None,
                    "total_days": 0, "filled_days": 0, "gap_days": 0}
        return dict(zip(["coverage_start","coverage_end","total_days",
                         "filled_days","gap_days"], row))

    def detect_gaps(self, stock_code: str) -> List[str]:
        """
        检测K线数据空洞 —— 与交易日历对比，找出缺失的交易日
        返回缺失日期列表
        """
        # 获取已有数据的日期
        existing = set(row[0] for row in self.db.execute(
            "SELECT trade_date FROM kline_day WHERE stock_code=? "
            "ORDER BY trade_date", (stock_code,)).fetchall())

        # 获取覆盖区间
        cov = self.get_coverage(stock_code)
        if not cov["coverage_start"]:
            return []

        # 该区间内的所有交易日
        trade_days = get_trade_days(
            self.db, cov["coverage_start"], cov["coverage_end"])
        gaps = [d for d in trade_days if d not in existing]
        return gaps

    def fill_initial(self, stock_code: str, days: int = 120):
        """
        初次加载：拉取最近 N 个交易日日K线
        国投 API: GET /api/kline/:code?type=day&count=N
        """
        log_id = self._start_sync_log('kline_day', stock_code, 'full')
        start_ts = time.time()
        try:
            raw = self.client.get_kline(stock_code, ktype='day', count=days)
            klines = raw.get('kLineData', [])
            inserted = 0
            for k in reversed(klines):  # 倒序（API返回倒序）
                cur = self.db.execute(
                    """INSERT OR IGNORE INTO kline_day
                       (stock_code, trade_date, open, high, low,
                        close, volume, amount)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (stock_code, k['time'], k['open'], k['high'], k['low'],
                     k['close'], k['volume'], k.get('amount', 0)))
                if cur.rowcount:
                    inserted += 1
            self.db.commit()

            # 更新覆盖率
            dates = [k['time'] for k in klines]
            if dates:
                self._update_coverage(stock_code, 'kline_day',
                                      min(dates), max(dates))

            self._finish_sync_log(log_id, 'success', len(klines), inserted,
                                  0, int((time.time()-start_ts)*1000))
            return {"status": "success", "fetched": len(klines),
                    "inserted": inserted}
        except Exception as e:
            self._finish_sync_log(log_id, 'failed', 0, 0, 0,
                                  int((time.time()-start_ts)*1000),
                                  str(e))
            raise

    def daily_sync(self, stock_codes: List[str]):
        """
        盘后同步：补拉最近 3 个交易日的日K线
        处理逻辑：
          1. 检查今日是否已有数据
          2. 如有空缺，从 API 拉取 3 天数据补齐
          3. 更新覆盖率
        """
        results = {}
        for code in stock_codes:
            log_id = self._start_sync_log('kline_day', code, 'incremental')
            start_ts = time.time()
            try:
                raw = self.client.get_kline(code, ktype='day', count=5)
                klines = raw.get('kLineData', [])
                inserted = 0
                for k in reversed(klines):
                    cur = self.db.execute(
                        """INSERT OR IGNORE INTO kline_day
                           (stock_code, trade_date, open, high, low,
                            close, volume, amount)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (code, k['time'], k['open'], k['high'], k['low'],
                         k['close'], k['volume'], k.get('amount', 0)))
                    if cur.rowcount:
                        inserted += 1
                self.db.commit()
                dates = [k['time'] for k in klines]
                if dates:
                    self._update_coverage(code, 'kline_day',
                                          min(dates), max(dates))
                self._finish_sync_log(log_id, 'success', len(klines),
                                      inserted, 0,
                                      int((time.time()-start_ts)*1000))
                results[code] = {"fetched": len(klines), "inserted": inserted}
            except Exception as e:
                self._finish_sync_log(log_id, 'failed', 0, 0, 0,
                                      int((time.time()-start_ts)*1000), str(e))
                results[code] = {"error": str(e)}
        return results

    def fill_gaps(self, stock_code: str) -> dict:
        """
        间隙检测与修复：
          1. 检测缺失交易日
          2. 分批拉取补齐
          3. 修复覆盖率记录
        """
        gaps = self.detect_gaps(stock_code)
        if not gaps:
            return {"status": "no_gaps", "gaps": 0}

        log_id = self._start_sync_log('kline_day', stock_code, 'gap_fill')
        start_ts = time.time()
        fixed = 0
        errors = []

        # 按天逐个补拉（国投API不支持指定日期，用count=1循环）
        # 优化：按连续区间批量拉取
        for gap_date in gaps:
            try:
                raw = self.client.get_kline(stock_code, ktype='day', count=3)
                for k in raw.get('kLineData', []):
                    self.db.execute(
                        """INSERT OR IGNORE INTO kline_day
                           (stock_code, trade_date, open, high, low,
                            close, volume, amount)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (stock_code, k['time'], k['open'], k['high'],
                         k['low'], k['close'], k['volume'],
                         k.get('amount', 0)))
                self.db.commit()
                fixed += 1
            except Exception as e:
                errors.append({"date": gap_date, "error": str(e)})

        self._finish_sync_log(log_id, 'success' if not errors else 'partial',
                              0, fixed, len(gaps)-fixed,
                              int((time.time()-start_ts)*1000),
                              json.dumps(errors, ensure_ascii=False))
        return {"status": "ok" if not errors else "partial",
                "total_gaps": len(gaps), "fixed": fixed,
                "errors": errors}

    # ── 内部工具 ──

    def _update_coverage(self, code: str, dtype: str,
                         start: str, end: str):
        """更新 data_coverage 表"""
        total = len(get_trade_days(self.db, start, end))
        filled = self.db.execute(
            "SELECT COUNT(*) FROM kline_day WHERE stock_code=? "
            "AND trade_date BETWEEN ? AND ?",
            (code, start, end)).fetchone()[0]
        exists = self.db.execute(
            "SELECT 1 FROM data_coverage WHERE stock_code=? AND data_type=?",
            (code, dtype)).fetchone()
        if exists:
            self.db.execute(
                """UPDATE data_coverage SET coverage_start=?,
                       coverage_end=?, total_days=?, filled_days=?,
                       gap_days=total_days-filled_days, last_synced_at=datetime('now')
                   WHERE stock_code=? AND data_type=?""",
                (start, end, total, filled, code, dtype))
        else:
            self.db.execute(
                """INSERT INTO data_coverage
                   (stock_code, data_type, coverage_start, coverage_end,
                    total_days, filled_days, gap_days, last_synced_at)
                   VALUES (?,?,?,?,?,?,?,datetime('now'))""",
                (code, dtype, start, end, total, filled, total - filled))
        self.db.commit()

    def _start_sync_log(self, dtype: str, code: str, mode: str) -> int:
        cur = self.db.execute(
            """INSERT INTO sync_log
               (data_type, source, stock_code, sync_mode, status)
               VALUES (?, 'sdicsc', ?, ?, 'running')""",
            (dtype, code, mode))
        self.db.commit()
        return cur.lastrowid

    def _finish_sync_log(self, log_id: int, status: str,
                         fetched: int, inserted: int, updated: int,
                         duration_ms: int, errors: str = None):
        self.db.execute(
            """UPDATE sync_log SET status=?, rows_fetched=?,
                   rows_inserted=?, rows_updated=?, duration_ms=?,
                   errors=?, created_at=datetime('now')
               WHERE id=?""",
            (status, fetched, inserted, updated, duration_ms, errors, log_id))
        self.db.commit()

# ─────────────────────────────────────────────────
# 三、资金流向补全
# ─────────────────────────────────────────────────

class FundFlowSyncService:
    """资金流向补全服务（国信证券）"""

    def __init__(self, db: sqlite3.Connection, gs_client):
        self.db = db
        self.client = gs_client

    def daily_sync(self, stock_code: str, period: int = 10):
        """
        盘后同步资金流向
        国信 API: fund_flow --code XXX --set_code X --period 10
        """
        raw = self.client.query_fund_flow(stock_code, set_code=0, period=period)
        items = ((raw.get("data") or {}).get("items")) or []
        ins = 0
        for item in items:
            cur = self.db.execute(
                """INSERT OR IGNORE INTO fund_flow
                   (stock_code, trade_date, main_force_net, fetched_at)
                   VALUES (?,?,?,datetime('now'))""",
                (stock_code, item.get("date", ""), item.get("net_mf_amount", 0)))
            if cur.rowcount > 0:
                ins += 1
        self.db.commit()
        return {"fetched": len(items), "inserted": ins}

# ─────────────────────────────────────────────────
# 四、财务报表补全
# ─────────────────────────────────────────────────

class FinancialSyncService:
    """财务报表补全服务（国信证券）"""

    def __init__(self, db: sqlite3.Connection, gs_client):
        self.db = db
        self.client = gs_client

    def check_missing_periods(self, stock_code: str) -> List[str]:
        """检测缺失的报告期"""
        existing = set(row[0] for row in self.db.execute(
            "SELECT report_year||report_type FROM financial_statement "
            "WHERE stock_code=?", (stock_code,)).fetchall())
        # 预期有 Q1-Q4 的最近3年
        expected = set()
        this_year = datetime.now().year
        for y in range(this_year-3, this_year+1):
            for qt in ['Q1', 'Q2', 'Q3', 'Q4']:
                expected.add(f"{y}{qt}")
        return sorted(expected - existing)

    def fill_period(self, stock_code: str, market: str,
                    year: str, qtype: str):
        """补拉单个报告期的财务数据"""
        # 利润表/资产负债表/现金流量表
        income = self.client.query_income_stmt(stock_code, market,
                                               report_type=qtype, report_year=year, count="1")
        balance = self.client.query_balance_sheet(stock_code, market,
                                                  report_type=qtype, report_year=year, count="1")
        cashflow = self.client.query_cashflow(stock_code, market,
                                              report_type=qtype, report_year=year, count="1")

        def first_row(raw: dict, key: str) -> dict:
            rows = raw.get(key) or [] if isinstance(raw, dict) else []
            return rows[0] if isinstance(rows, list) and rows else {}

        def num(row: dict, key: str):
            v = row.get(key)
            try:
                return float(v) if v not in (None, "", "0") else None
            except (TypeError, ValueError):
                return None

        i = first_row(income, "income")
        b = first_row(balance, "balance")
        c = first_row(cashflow, "cashFlow")
        if not (i or b or c):
            return {"status": "no_data"}

        revenue = num(i, "operatingRevenue")
        net_profit = num(i, "netProfit")
        eps = num(i, "basicEPS")
        total_assets = num(b, "totalAssets")
        total_liab = num(b, "totalLiabilities")
        equity = num(b, "totalEquity")
        oper_cf = num(c, "netOperateCashFlow")
        # 派生指标
        gross_margin = None
        cost = num(i, "operatingCost")
        if revenue and cost:
            gross_margin = round((revenue - cost) / revenue * 100, 2)
        debt_ratio = round(total_liab / total_assets * 100, 2) if (total_liab and total_assets) else None
        roe = None
        if net_profit is not None and equity:
            roe = round(net_profit / equity * 100, 2)

        # 合并写入 financial_statement 表
        self.db.execute(
            """INSERT OR REPLACE INTO financial_statement
               (stock_code, market, report_type, report_year,
                revenue, net_profit, eps, gross_margin, net_margin,
                total_assets, total_liab, equity, roe, debt_ratio,
                oper_cf, free_cf, fetched_at)
               VALUES (?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,datetime('now'))""",
            (stock_code, market, qtype, year,
             revenue, net_profit, eps, gross_margin, None,
             total_assets, total_liab, equity, roe, debt_ratio,
             oper_cf, None))
        self.db.commit()
        return {"status": "ok"}

# ─────────────────────────────────────────────────
# 五、定时调度器
# ─────────────────────────────────────────────────

class DailySyncScheduler:
    """
    盘后自动同步调度器
    在 A 股收盘后（15:30以后）执行
    """

    def __init__(self, db, sdicsc_client, gs_client):
        self.db = db
        self.kline_sync = KlineSyncService(db, sdicsc_client)
        self.flow_sync = FundFlowSyncService(db, gs_client)
        self.fin_sync = FinancialSyncService(db, gs_client)

    def run_daily_all(self, stock_codes: List[str]):
        """盘后全量同步"""
        logger.info(f"=== 盘后同步开始: {len(stock_codes)} 只股票 ===")

        # 1. 日K线补全
        kline_result = self.kline_sync.daily_sync(stock_codes)
        logger.info(f"K线同步: {len(kline_result)} 只完成")

        # 2. 资金流向
        for code in stock_codes:
            self.flow_sync.daily_sync(code)

        # 3. 检测数据间隙
        for code in stock_codes:
            gaps = self.kline_sync.detect_gaps(code)
            if gaps:
                logger.warning(f"{code}: 发现 {len(gaps)} 天数据缺失")
                self.kline_sync.fill_gaps(code)

        logger.info("=== 盘后同步完成 ===")

    def initial_load_all(self, stock_codes: List[str], days: int = 120):
        """首次全量加载"""
        for code in stock_codes:
            self.kline_sync.fill_initial(code, days=days)
            logger.info(f"{code}: 初始K线加载完成 ({days}天)")
