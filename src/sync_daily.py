"""
一键全量同步 — 整合所有数据源
用法:  python3 src/sync_daily.py
       python3 src/sync_daily.py --quick   # 仅行情+K线(盘中快速)
       python3 src/sync_daily.py --full    # 全量(收盘后)
"""

import sys, os, json, time, sqlite3
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import urllib.request, ssl
from urllib.parse import urlencode
from src.datasource.sdicsc_client import get_batch_quote, get_kline, quote_to_db_row
from src.datasource.gs_client import _get, query_income_stmt, query_balance_sheet, query_cashflow

SSL_CTX = ssl.create_default_context()
try: SSL_CTX.options |= ssl.OP_LEGACY_SERVER_CONNECT
except AttributeError: pass

class SyncProgress:
    def __init__(self, total_steps):
        self.total = total_steps
        self.current = 0
        self.logs = []
        self.t0 = time.time()
    
    def step(self, msg):
        self.current += 1
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{self.current}/{self.total}] {msg}"
        self.logs.append(line)
        print(line, flush=True)
        return line
    
    def result(self):
        return {
            "steps": self.current,
            "total": self.total,
            "logs": self.logs,
            "duration": round(time.time() - self.t0, 1)
        }


def sync_quotes(db, prog) -> int:
    """1. 实时行情"""
    codes = [r[0] for r in db.execute("SELECT stock_code FROM portfolio_stock").fetchall()]
    code_map = {}
    for c in codes:
        if c.startswith("H") or c.startswith("h"): code_map[f"hk{c.lstrip('Hh')}"] = c
        else: code_map[c.lower()] = c
    try:
        raw = get_batch_quote(codes); ins = 0
        for r in raw:
            sc = r.get("stockCode","") or r.get("code","")
            if not sc: continue
            orig = code_map.get(sc.lower(), sc)
            row = quote_to_db_row(r, orig)
            db.execute("""INSERT INTO real_time_quote(stock_code,price,change_amt,change_pct,prev_close,open,high,low,volume,amount,turnover,volume_ratio,pe,pe_dynamic,pe_ttm,market_value,change_20d,change_60d,susp_flag,trade_date,trade_time,fetched_at) VALUES(:stock_code,:price,:change_amt,:change_pct,:prev_close,:open,:high,:low,:volume,:amount,:turnover,:volume_ratio,:pe,:pe_dynamic,:pe_ttm,:market_value,:change_20d,:change_60d,:susp_flag,:trade_date,:trade_time,datetime('now'))""", row); ins+=1
        db.commit()
        prog.step(f"📊 行情: {ins}/{len(codes)} 条")
        return ins
    except Exception as e:
        prog.step(f"❌ 行情: {e}")
        return 0

def sync_kline(db, prog, quick=False) -> int:
    """2. 日K线"""
    codes = [r[0] for r in db.execute("SELECT DISTINCT stock_code FROM portfolio_stock WHERE stock_code NOT LIKE 'H%'").fetchall()]
    total = 0
    days = 5 if quick else 120
    limit = 5 if quick else len(codes)
    for code in codes[:limit]:
        try:
            k = get_kline(code, 'day', days); ins = 0
            for row in k:
                cur = db.execute(
                    "INSERT OR IGNORE INTO kline_day(stock_code,trade_date,open,high,low,close,volume,amount) VALUES (?,?,?,?,?,?,?,?)",
                    (code,row['time'],row['open'],row['high'],row['low'],row['close'],row.get('volume',0),row.get('amount',0)))
                if cur.rowcount > 0: ins += 1
            db.commit(); total += ins
        except Exception as e:
            print(f"  ⚠️ K线 {code}: {e}", flush=True)
    prog.step(f"📈 K线: {total} 条新增 ({'快速' if quick else '全量'})")
    return total

def sync_trend(db, prog, quick=False) -> int:
    """3. 分时"""
    from src.datasource.sdicsc_client import get_trend
    codes = [r[0] for r in db.execute("SELECT DISTINCT stock_code FROM portfolio_stock WHERE stock_code NOT LIKE 'H%'").fetchall()]
    limit = 3 if quick else len(codes)
    total = 0
    for code in codes[:limit]:
        try:
            raw = get_trend(code)
            td = raw.get("timeData",[]); date = raw.get("meta",{}).get("date",""); ins = 0
            for t in td:
                cur = db.execute(
                    "INSERT OR IGNORE INTO trend_data(stock_code,trade_date,time_seq,price,avg_price,volume,change_amt,change_pct) VALUES (?,?,?,?,?,?,?,?)",
                    (code,date,t['time'],t['price'],t.get('avgPrice'),t.get('volume',0),t.get('change',0),t.get('changePercent',"")))
                if cur.rowcount > 0: ins += 1
            db.commit(); total += ins
        except Exception as e:
            print(f"  ⚠️ 分时 {code}: {e}", flush=True)
    prog.step(f"⏱ 分时: {total} 点")
    return total

def sync_financial(db, prog, quick=False) -> int:
    """4. 财务 (仅非快速模式)"""
    if quick: return prog.step("📋 财务: 跳过(快速模式)")
    codes = [r[0] for r in db.execute("SELECT DISTINCT stock_code FROM portfolio_stock WHERE stock_code NOT LIKE 'H%'").fetchall()]
    total = 0
    stmt_keys = {"利润表": "income", "负债表": "balance", "现金流": "cashFlow"}
    for code in codes:
        try:
            market = "SH" if code[0] in "56" else "SZ"
            for stmt, get_fn in [("利润表",query_income_stmt),("负债表",query_balance_sheet),("现金流",query_cashflow)]:
                r = get_fn(code, market, count="4")
                rows = r.get(stmt_keys[stmt], [])
                for row in rows:
                    yr = row.get("year","")
                    if not yr: continue
                    rt = "Q4" if "-12-" in yr else "Q3" if "-09-" in yr else "Q2" if "-06-" in yr else "Q1"
                    cur = db.execute("INSERT OR IGNORE INTO financial_statement(stock_code,market,report_type,report_year,report_date,fetched_at) VALUES(?,?,?,?,?,datetime('now'))",
                               (code,market,rt,yr[:4],yr))
                    if cur.rowcount > 0: total += 1
            db.commit()
            time.sleep(0.3)
        except Exception as e:
            print(f"  ⚠️ 财务 {code}: {e}", flush=True)
    prog.step(f"📋 财务: {total} 条新增")
    return total

def sync_macro_articles(db, prog) -> int:
    """5. 宏观经济文章"""
    queries = [
        ("中国GDP同比增速","宏观·GDP"),
        ("中国CPI同比 2024年至2025年变化","宏观·CPI"),
        ("中国PPI同比 2024年至2025年变化","宏观·PPI"),
        ("中国M2同比增速 2024年至2025年趋势","宏观·M2"),
        ("中国制造业PMI 2024年至2025年走势","宏观·PMI"),
        ("中国LPR利率 2024年至2025年调整历史","宏观·LPR"),
        ("美国CPI同比 2024年至2025年","宏观·美国CPI"),
        ("美国联邦基准利率 2024年至2025年变化","宏观·美联储"),
    ]
    api_key = os.environ.get("GS_API_KEY", "")
    if not api_key: return prog.step("🌏 宏观: 跳过(无Key)")
    ok = 0
    for query, cat in queries:
        try:
            r = _get("https://dgzt.guosen.com.cn/skills/agent/adapter/query",
                     {"text":query,"softName":"agent_skills"})
            content = ""
            for item in r.get("data", []):
                if item.get("type") == "STREAM_MESSAGE":
                    content += item.get("content","")
            if content and len(content) > 50:
                db.execute("INSERT OR REPLACE INTO research_article(category,title,content,source) VALUES(?,?,?,?)",
                           (cat, query, content[:5000], "国信证券AI"))
                db.commit(); ok += 1
            time.sleep(1)
        except Exception as e:
            print(f"  ⚠️ 宏观 {query[:30]}: {e}", flush=True)
    prog.step(f"🌏 宏观: {ok}/{len(queries)} 篇文章")
    return ok

def sync_smart_picks(db, prog) -> int:
    """6. 智能选股推荐"""
    api_key = os.environ.get("GS_API_KEY", "")
    if not api_key: return prog.step("🎯 智能选股: 跳过(无Key)")
    queries = [
        ("市盈率小于15且ROE大于15%的股票","低估值优质"),
        ("主力资金净流入的股票","资金流入"),
        ("今日涨幅大于3%的股票","强势股"),
    ]
    total = 0
    for query, tag in queries:
        try:
            url = f"https://dgzt.guosen.com.cn/skills/agent/mcp/smart_stock_picking"
            params = {"searchstring":query,"searchtype":"stock","apiKey":api_key,"softName":"agent_skills"}
            req = urllib.request.Request(f"{url}?{urlencode(params)}")
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as resp:
                data = json.loads(resp.read())
            tables = data.get("data", [])
            for tbl in tables:
                table_data = tbl.get("table", {})
                codes = table_data.get("股票代码", [])
                names = table_data.get("股票简称", [])
                if codes and names:
                    db.execute("INSERT OR REPLACE INTO research_article(category,title,content,source) VALUES(?,?,?,?)",
                               (f"选股·{tag}", query, json.dumps({"codes":codes[:20],"names":names[:20]},ensure_ascii=False)[:5000],
                                "国投证券智能选股"))
                    db.commit()
                    total += len(codes[:20])
            time.sleep(1)
        except Exception as e:
            print(f"  ⚠️ 选股 {query[:30]}: {e}", flush=True)
    prog.step(f"🎯 智能选股: {total} 只推荐")
    return total

def sync_crowding(db, prog):
    """7. 行业拥挤度"""
    key = os.environ.get("GT_CROWDING_DEGREE_API_KEY") or os.environ.get("GT_ZNXG_KEY")
    if not key: return prog.step("📊 拥挤度: 跳过")
    targets = ['h30255.CSI','399976.CSI','h30186.CSI','950096.CSI','399319.SZ','h30217.CSI']
    ok = 0
    for code in targets:
        try:
            url = f"https://skills.sdicsc.com.cn/skill/api/v1/calc/query?code={code}"
            req = urllib.request.Request(url, headers={"X-API-Key": key})
            with urllib.request.urlopen(req,context=SSL_CTX,timeout=10) as resp:
                raw = json.loads(resp.read())
            cd = raw.get("data",{}).get(code,{})
            if cd:
                db.execute("INSERT OR IGNORE INTO research_article(category,title,content,source) VALUES(?,?,?,?)",
                           ("行业拥挤度", f"拥挤度_{code}", json.dumps(cd,ensure_ascii=False)[:3000], "国投证券"))
                db.commit(); ok += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  ⚠️ 拥挤度 {code}: {e}", flush=True)
    prog.step(f"📊 拥挤度: {ok} 个行业")
    return ok


def sync_predictions(db, prog) -> int:
    """8. 预测-反馈闭环（结算到期预测 + 生成新一轮预测）"""
    from src.quant.prediction_loop import run_prediction_loop
    r = run_prediction_loop(db)
    prog.step(f"🔮 预测闭环: 结算 {r['settled']} / 新预测 {r['predicted']} / 跳过 {r['skipped']}")
    return r["predicted"]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="快速模式(仅行情+K线+分时)")
    parser.add_argument("--full", action="store_true", help="全量模式")
    args = parser.parse_args()
    
    quick = args.quick
    mode = "🔄 一键全量同步" if not quick else "⚡ 快速同步(行情+K线+分时)"
    
    db_path = str(Path(__file__).parent.parent / "data" / "stock.db")
    from src.db.schema import init_db
    init_db(db_path)
    db = sqlite3.connect(db_path)
    prog = SyncProgress(8 if not quick else 4)
    
    print(f"\n{'='*50}")
    print(f"{mode}")
    print(f"{'='*50}\n")
    
    sync_quotes(db, prog)
    sync_kline(db, prog, quick)
    sync_trend(db, prog, quick)
    sync_predictions(db, prog)
    
    if not quick:
        sync_financial(db, prog, quick)
        sync_macro_articles(db, prog)
        sync_smart_picks(db, prog)
        sync_crowding(db, prog)
    
    r = prog.result()
    print(f"\n{'='*50}")
    print(f"✅ 完成: {r['steps']} 步, {r['duration']}s")
    print(f"{'='*50}\n")
    
    # 写入同步日志
    db.execute("INSERT INTO sync_log(data_type,source,rows_inserted,sync_mode,duration_ms) VALUES(?,'auto',?,'daily',?)",
               ("daily_sync", r['steps'], int(r['duration']*1000)))
    db.commit()
    db.close()

if __name__ == "__main__":
    main()
