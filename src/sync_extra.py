"""
全量辅助数据同步 — 行业拥挤度 + 宏观经济 + 资金流向
"""
import sys, os, json, time, re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3, urllib.request, ssl
from urllib.parse import urlencode

DB = Path(__file__).parent.parent / "data" / "stock.db"
LOG = Path(__file__).parent.parent / "data" / "sync_extra.log"
SSL_CTX = ssl.create_default_context()
try: SSL_CTX.options |= ssl.OP_LEGACY_SERVER_CONNECT
except AttributeError: pass

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"; print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(line+"\n")

# ── 1. 行业拥挤度 ──
def sync_crowding(db):
    """同步行业拥挤度（写入 sector_crowding 表）"""
    key = os.environ.get("GT_CROWDING_DEGREE_API_KEY") or os.environ.get("GT_ZNXG_KEY")
    if not key: return log("  ❌ 缺少 GT_CROWDING_DEGREE_API_KEY")
    
    # 与自选股相关的行业（备选目标，用于行业映射缺失时兜底）
    sectors = {
        "h20797.CSI":"互联网","399319.SZ":"资源","h30217.CSI":"医疗器械",
        "931546.CSI":"金融","h30255.CSI":"医药","950096.CSI":"上海国企",
        "h30186.CSI":"保险","399976.CSI":"证券公司","931148.CSI":"ESG80",
    }
    # 通过行业名称搜索
    try:
        with open(Path.home()/".reasonix/skills/sdicsc-crowding-degree/industry_info.json") as f:
            ind_data = json.load(f)
        ind_map = {i["S_INFO_WINDCODE"]: i["S_INFO_NAME"] for i in ind_data.get("industry_info",[])}
    except Exception as e:
        log(f"  ⚠️ 行业映射加载失败: {e}")
        ind_map = {}

    # 搜索关键词
    keywords = ["半导体","电力","银行","医药","化工","军工","机械","包装","白酒","证券"]
    matched_codes = set()
    for kw in keywords:
        for code, name in ind_map.items():
            if kw in name: matched_codes.add(code)
    
    matched = list(matched_codes)[:30]  # 最多30个行业
    if not matched: matched = list(sectors.keys())[:10]
    
    log(f"📊 同步拥挤度: {len(matched)} 个行业")
    ok = 0
    for i, code in enumerate(matched):
        try:
            url = f"https://skills.sdicsc.com.cn/skill/api/v1/calc/query?code={code}"
            req = urllib.request.Request(url, headers={"X-API-Key": key})
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as resp:
                data = json.loads(resp.read())
            # 真实返回: data 为 {code: {code, calcTime, d5, d20}}（驼峰字段）
            cd = data.get("data", {})
            cd = cd.get(code, {}) if isinstance(cd, dict) else {}
            if not cd:
                log(f"  ⚠️ {code}: 无数据")
                continue
            name = ind_map.get(code, code)
            calc_time = str(cd.get("calcTime") or "")
            calc_date = calc_time[:10] if calc_time else datetime.now().strftime("%Y-%m-%d")
            row = {}
            for period_key, prefix in [("d5","d5"),("d20","d20")]:
                pd_data = cd.get(period_key, {}) or {}
                for src_key, db_key in [("amountRatio","amount"),
                                        ("totalMarketValueRatio","market_val"),
                                        ("turnoverRatio","turnover")]:
                    stats = (pd_data.get(src_key) or {}).get("stats", {}) or {}
                    row[f"{prefix}_{db_key}_now"] = stats.get("now")
                    row[f"{prefix}_{db_key}_quantile"] = stats.get("quantile")
            db.execute("""INSERT OR REPLACE INTO sector_crowding
                (sector_code, sector_name, calc_date,
                 d5_amount_now, d5_amount_quantile,
                 d5_market_val_now, d5_market_val_quantile,
                 d5_turnover_now, d5_turnover_quantile,
                 d20_amount_now, d20_amount_quantile,
                 d20_market_val_now, d20_market_val_quantile,
                 d20_turnover_now, d20_turnover_quantile,
                 fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (code, name, calc_date,
                 row.get("d5_amount_now"), row.get("d5_amount_quantile"),
                 row.get("d5_market_val_now"), row.get("d5_market_val_quantile"),
                 row.get("d5_turnover_now"), row.get("d5_turnover_quantile"),
                 row.get("d20_amount_now"), row.get("d20_amount_quantile"),
                 row.get("d20_market_val_now"), row.get("d20_market_val_quantile"),
                 row.get("d20_turnover_now"), row.get("d20_turnover_quantile")))
            db.commit()
            ok += 1
        except Exception as e:
            log(f"  ⚠️ {code}: {e}")
        time.sleep(0.3)
    log(f"  ✅ 拥挤度: {ok}/{len(matched)} 完成")

# ── 2. 宏观经济 ──
def sync_macro(db):
    """同步关键宏观经济指标"""
    api_key = os.environ.get("GS_API_KEY", "")
    if not api_key: return log("  ❌ 缺少 GS_API_KEY")
    
    indicators = [
        ("中国GDP同比增速", "GDP_CN"), ("中国CPI同比", "CPI_CN"), ("中国PPI同比", "PPI_CN"),
        ("中国M2同比增速", "M2_CN"), ("中国制造业PMI", "PMI_CN"),
        ("中国LPR1年期", "LPR_1Y"), ("中国LPR5年期", "LPR_5Y"),
        ("美国CPI同比", "CPI_US"), ("美国联邦基准利率", "FED_RATE"),
    ]
    
    log(f"🌏 同步宏观经济: {len(indicators)} 个指标")
    ok = 0
    for query, code in indicators:
        try:
            url = f"https://dgzt.guosen.com.cn/skills/agent/adapter/query"
            params = {"text": f"{query} 最新数据", "softName": "agent_skills", "apiKey": api_key}
            req = urllib.request.Request(f"{url}?{urlencode(params)}")
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as resp:
                result = resp.read().decode("utf-8")
            # adapter 返回 JSON，正文在 STREAM_MESSAGE 项的 content 中
            value = None
            try:
                payload = json.loads(result)
                for item in (payload.get("data") or []):
                    if isinstance(item, dict) and item.get("type") == "STREAM_MESSAGE":
                        m = re.search(r"[-+]?\d+(?:\.\d+)?", item.get("content", ""))
                        if m:
                            value = float(m.group())
                            break
            except (ValueError, TypeError):
                pass
            if value is not None:
                db.execute("INSERT OR REPLACE INTO macro_indicator(indicator_code,period,value,fetched_at) VALUES(?,?,?,datetime('now'))",
                           (code, datetime.now().strftime("%Y-%m"), value))
                ok += 1
            else:
                log(f"  ⚠️ {code}: 未提取到数值")
        except Exception as e:
            log(f"  ⚠️ {code}: {e}")
        time.sleep(1)
    log(f"  ✅ 宏观: {ok}/{len(indicators)} 完成")

# ── 3. 资金流向 ──
def sync_fund_flow(db):
    """同步持仓股资金流向"""
    api_key = os.environ.get("GS_API_KEY", "")
    if not api_key: return
    codes = [r[0] for r in db.execute("SELECT stock_code FROM portfolio_stock WHERE is_holding=1 AND stock_code NOT LIKE 'H%'").fetchall()]
    if not codes: return log("  📭 无持仓股")
    log(f"💰 同步资金流向: {len(codes)} 只持仓")
    ok = 0
    for code in codes:
        try:
            market = "SH" if code[0] in "56" else "SZ"
            set_code = 1 if code[0] in "56" else 0
            url = f"https://dgzt.guosen.com.cn/skills/gsnews/market/agentbot/queryFundFlow/1.0"
            params = {"code":code,"setCode":str(set_code),"period":"30","softName":"agent_skills","apiKey":api_key}
            req = urllib.request.Request(f"{url}?{urlencode(params)}")
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as resp:
                data = json.loads(resp.read())
            flow_data = data.get("data", {}).get("items", []) or []
            ins = 0
            for item in flow_data:
                cur = db.execute("""INSERT OR IGNORE INTO fund_flow(stock_code,trade_date,main_force_net,fetched_at)
                    VALUES(?,?,?,datetime('now'))""", (code, item.get("date",""), item.get("net_mf_amount",0)))
                if cur.rowcount > 0: ins += 1
            db.commit()
            ok += 1
            log(f"    {code}: {ins} 条")
        except Exception as e:
            log(f"  ⚠️ {code}: {e}")
        time.sleep(0.5)
    log(f"  ✅ 资金流向: {ok}/{len(codes)} 完成")

def main():
    log("="*50)
    log("🚀 辅助数据全量同步")
    from src.db.schema import init_db
    init_db(str(DB))
    db = sqlite3.connect(str(DB))
    sync_crowding(db)
    db.commit()
    sync_macro(db)
    db.commit()
    sync_fund_flow(db)
    db.commit()
    db.close()
    log("✅ 全部完成")
    log("="*50)

if __name__ == "__main__":
    main()
