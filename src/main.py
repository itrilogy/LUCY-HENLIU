"""
QuantLab — 量化交易数据分析工具
数据源: 国投证券(行情) + 国信证券(财务)
量化引擎: GMM状态分类 / 马尔可夫链 / 动量分析
"""
import os, sys, sqlite3, math
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import json
import csv
import io
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from src.datasource.sdicsc_client import get_batch_quote, get_kline, quote_to_db_row, health_check
from src.quant.engine import RegimeClassifier, MarkovTransition, MomentumAnalyzer, PortfolioAnalyzer
from src.quant.pattern_discovery import PatternDiscoveryEngine
from src.db.schema import init_db

# ── 配色 ────────────────────────────────────────
UP, DOWN, FLAT = "#ef4444", "#22c55e", "#94a3b8"
BG, CARD = "#0f172a", "#3a4c68"
TEXT, MUTED, ACCENT = "#e2e8f0", "#8fa3bf", "#60a5fa"
GRID = "#2e3f5c"                       # 图表网格（隐约可辨）
UP_FILL, DOWN_FILL = "rgba(239,68,68,0.45)", "rgba(34,197,94,0.45)"  # 蜡烛半透明
st.set_page_config(page_title="QuantLab", layout="wide",
                   page_icon=str(Path(__file__).parent / "assets" / "favicon-32x32.png"))
st.markdown(f"""<style>
/* Streamlit 主题变量：统一全部组件的前景/背景色（修复组件默认深灰文字落在深色背景上对比不足） */
:root {{
  --text-color: {TEXT};
  --background-color: {BG};
  --secondary-background-color: {CARD};
  --primary-color: {ACCENT};
}}
.stApp {{ background:{BG}; color:{TEXT}; }}
.stButton>button {{ background:{ACCENT}; color:#0f172a; font-weight:600; border:none; border-radius:4px; }}
h1,h2,h3, .stMarkdown {{ color:{TEXT} !important; }}
/* 弱文字与指标 */
.stMetric label {{ color:{MUTED} !important; }}
div[data-testid="stMetricValue"] {{ color:{TEXT} !important; font-size:1.2rem !important; }}
div[data-testid="stCaptionContainer"] p {{ color:{MUTED} !important; }}
/* Tab 标签（Streamlit 1.60：tab 为 div[data-testid="stTab"]，非 button） */
[data-testid="stTabs"] [data-testid="stTab"] {{ color:{MUTED} !important; }}
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] {{ color:{TEXT} !important; }}
/* 折叠面板标题 */
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary p {{ color:{TEXT} !important; }}
/* 输入/选择控件文字（selectbox 为 React Aria ComboBox 结构） */
.stSelectbox div[data-baseweb="select"] {{ background:{CARD}; border-color:#40536e; }}
.stSelectbox div[data-baseweb="select"] span, .stSelectbox div[data-baseweb="select"] div {{ color:{TEXT} !important; }}
[data-testid="stSelectbox"] input, [data-testid="stSelectbox"] [role="combobox"] {{ color:{TEXT} !important; }}
.stTextInput input, .stTextArea textarea {{ background:{CARD}; color:{TEXT} !important; border-color:#40536e; }}
.stRadio label, .stCheckbox label {{ color:{TEXT} !important; }}
/* 控件标签（stWidgetLabel：selectbox/textinput/multiselect 等的标题）：
   修复浅色主题深灰文字残留（如「当前分析标的」「分类」） */
[data-testid="stWidgetLabel"] {{ color:{TEXT} !important; }}
[data-testid="stWidgetLabel"] p {{ color:{TEXT} !important; }}
/* ── 输入控件统一规范（全局）：背景/边框/文字/占位符 ── */
/* 输入区：比卡片深一档的内凹背景 + 1px 边框，与页面/卡片形成三级层次 */
[data-testid="stSelectbox"] [role="combobox"],
[data-testid="stSelectbox"] input,
[data-testid="stMultiselect"] input,
[data-testid="stNumberInput"] input,
.stTextInput input,
.stTextArea textarea {{
  background:#263449 !important;
  border:1px solid #40536e !important;
  border-radius:6px !important;
  color:{TEXT} !important;
}}
input::placeholder, textarea::placeholder {{ color:{MUTED} !important; }}
/* 下拉列表弹出层（React Aria portal） */
#stFloatingOverlayPortal [role="listbox"],
#portal [role="listbox"] {{
  background:#263449 !important;
  color:{TEXT} !important;
  border:1px solid #40536e !important;
  border-radius:6px !important;
}}
#stFloatingOverlayPortal [role="option"],
#portal [role="option"] {{ color:{TEXT} !important; }}
#stFloatingOverlayPortal [role="option"][aria-selected="true"],
#portal [role="option"][aria-selected="true"] {{
  background:rgba(96,165,250,0.25) !important;
  color:{TEXT} !important;
}}
/* 单选框/复选框：深色胶囊（修复浅色主题白底残留） */
[data-testid="stRadio"] [role="radio"] {{
  color:{TEXT} !important;
  background:transparent !important;
}}
[data-testid="stRadio"] [role="radio"][aria-checked="true"] {{
  color:{ACCENT} !important;
  background:rgba(96,165,250,0.12) !important;
}}
[data-testid="stCheckbox"] label {{ color:{TEXT} !important; }}
/* 数据表格单元格 */
div[data-testid="stDataFrame"] {{ background:{CARD}; color:{TEXT}; }}
div[data-testid="stDataFrame"] td, div[data-testid="stDataFrame"] th {{ color:{TEXT} !important; }}
section[data-testid="stSidebar"] {{ background:{CARD}; border-right:1px solid #40536e; }}
</style>""", unsafe_allow_html=True)

# ── 数据库 ──────────────────────────────────────
@st.cache_resource
def get_db():
    p = Path(__file__).parent.parent / "data" / "stock.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    init_db(str(p))  # 统一 DDL：与 src/db/schema.py 保持一致
    c = sqlite3.connect(str(p), check_same_thread=False)
    c.row_factory = sqlite3.Row; c.execute("PRAGMA journal_mode=WAL"); _seed(c); return c

STOCKS = [("301707","展芯股份","SZ"),("688825","C长鑫科技","SH"),("002916","深南电路","SZ"),("000037","深南电A","SZ"),
    ("H02380","中国电力","HK"),("600875","东方电气","SH"),("300122","智飞生物","SZ"),("601229","上海银行","SH"),
    ("600309","万华化学","SH"),("605060","联德股份","SH"),("603507","振江股份","SH"),("605123","派克新材","SH"),
    ("688239","贵州航宇科技","SH"),("000534","万泽股份","SZ"),("603308","应流股份","SH"),("300829","金丹科技","SZ"),
    ("600143","金发科技","SH"),("301501","恒鑫生活","SZ"),("002831","裕同科技","SZ"),("002228","合兴包装","SZ"),
    ("601998","中信银行","SH"),("159611","电力ETF广发","SZ"),("600900","长江电力","SH"),("300034","钢研高纳","SZ"),
    ("600399","抚顺特钢","SH"),("601727","上海电气","SH")]
HOLD = {"002831","600143","600309","600875","600900","603308"}

def _seed(db):
    """首次初始化组合（命名列，兼容完整版表结构）"""
    if db.execute("SELECT 1 FROM portfolio LIMIT 1").fetchone(): return
    pid = db.execute("INSERT INTO portfolio (id,name) VALUES (1,'组合')").lastrowid
    for c,n,m in STOCKS:
        db.execute("INSERT OR IGNORE INTO stock_basic (stock_code,name,market) VALUES (?,?,?)",(c,n,m))
        db.execute("INSERT INTO portfolio_stock (portfolio_id,stock_code,market,is_holding) VALUES (?,?,?,?)",(pid,c,m,1 if c in HOLD else 0))
    db.commit()

# ── 数据加载 ────────────────────────────────────
@st.cache_data(ttl=30)
def load_quotes(_db):
    return pd.read_sql("""
        SELECT q.stock_code, sb.name, q.price, q.change_pct, q.change_amt, q.pe_ttm,
               q.market_value, q.turnover, q.change_20d, q.change_60d, q.volume_ratio,
               q.prev_close, q.open, q.high, q.low, q.volume, q.amount, ps.is_holding
        FROM real_time_quote q JOIN stock_basic sb ON q.stock_code=sb.stock_code
        JOIN portfolio_stock ps ON q.stock_code=ps.stock_code
        WHERE q.fetched_at=(SELECT MAX(fetched_at) FROM real_time_quote)
    """, _db)

@st.cache_data(ttl=300)
def load_kline_df(_db, code):
    return pd.read_sql("SELECT * FROM kline_day WHERE stock_code=? ORDER BY trade_date", _db, params=(code,))

@st.cache_data(ttl=300)
def load_fin_df(_db, code):
    return pd.read_sql("SELECT report_year||report_type AS period,revenue,net_profit,eps,gross_margin,roe,debt_ratio FROM financial_statement WHERE stock_code=? ORDER BY report_year,report_type", _db, params=(code,))

def toggle_holding(db, code):
    db.execute("UPDATE portfolio_stock SET is_holding=1-is_holding WHERE stock_code=?",(code,)); db.commit()
    st.cache_data.clear()

def guess_market(code: str) -> str:
    """按代码前缀推断市场（H→HK，6/5→SH，4/8→BJ，其余→SZ）"""
    c = code.strip().upper()
    if c.startswith("H"): return "HK"
    if c[0] in "56": return "SH"
    if c[0] in "48": return "BJ"
    # 可转债/可交换债按具体代码段细分
    # 沪市：110/113/118/132（可转债）、120/122/124（可交换债）
    if c.startswith(("110", "113", "118", "132", "120", "122", "124")):
        return "SH"
    # 深市：123/125/127/128/129（可转债）等 → 默认 SZ
    return "SZ"

def add_stock(db, code: str) -> str:
    """添加自选股：调用行情 API 验证股票存在，写入 stock_basic + portfolio_stock"""
    code = code.strip().upper()
    if not code: return "请输入股票代码"
    if db.execute("SELECT 1 FROM portfolio_stock WHERE stock_code=?", (code,)).fetchone():
        return f"{code} 已在自选中"
    try:
        from src.datasource.sdicsc_client import get_quote
        q = get_quote(code)
        name = q.get("name") or code
        market = guess_market(code)
    except Exception as e:
        return f"股票验证失败: {e}"
    db.execute("INSERT OR IGNORE INTO stock_basic (stock_code,name,market) VALUES (?,?,?)", (code, name, market))
    db.execute("INSERT OR IGNORE INTO portfolio_stock (portfolio_id,stock_code,market,is_holding) VALUES (1,?,?,0)", (code, market))
    db.commit()
    st.cache_data.clear()
    return f"✅ 已添加 {name} ({code})"

def remove_stock(db, code: str):
    """从自选移除（保留历史行情/K线数据）"""
    db.execute("DELETE FROM portfolio_stock WHERE stock_code=?", (code,))
    db.commit()
    st.cache_data.clear()

@st.cache_data(ttl=600)
def cached_backtest(code: str, last_date: str, cols: tuple, rows: tuple) -> dict:
    """滑动窗口回测（缓存：K线数据未更新则不重算，避免每次渲染全量重跑）"""
    kdf = pd.DataFrame(list(rows), columns=list(cols))
    pde = PatternDiscoveryEngine(code)
    pde.fit(kdf)
    return pde.backtest(window=50, step=2)

# ── 同步 ────────────────────────────────────────
def sync_data(db, codes):
    code_map = {}
    for c in codes:
        c = c.strip()
        if c.startswith("H") or c.startswith("h"): code_map[f"hk{c.lstrip('Hh')}"] = c
        else: code_map[c.lower()] = c
    try:
        raw = get_batch_quote(codes); ins = 0
        for r in raw:
            sc = r.get("stockCode","") or r.get("code","")
            if not sc: continue
            orig = code_map.get(sc.lower(), sc)
            row = quote_to_db_row(r, orig)
            db.execute("INSERT INTO real_time_quote(stock_code,price,change_amt,change_pct,prev_close,open,high,low,volume,amount,turnover,volume_ratio,pe,pe_dynamic,pe_ttm,market_value,change_20d,change_60d,susp_flag,trade_date,trade_time,fetched_at) VALUES(:stock_code,:price,:change_amt,:change_pct,:prev_close,:open,:high,:low,:volume,:amount,:turnover,:volume_ratio,:pe,:pe_dynamic,:pe_ttm,:market_value,:change_20d,:change_60d,:susp_flag,:trade_date,:trade_time,datetime('now'))", row); ins+=1
        db.commit()
        # 顺带拉K线
        for c in codes[:5]:
            k = get_kline(c, 'day', 120)
            for row in k:
                db.execute("INSERT OR IGNORE INTO kline_day(stock_code,trade_date,open,high,low,close,volume,amount) VALUES (?,?,?,?,?,?,?,?)",
                           (c,row['time'],row['open'],row['high'],row['low'],row['close'],row.get('volume',0),row.get('amount',0)))
            db.commit()
        return {"ok": True, "inserted": ins}
    except Exception as e: return {"ok": False, "msg": str(e)}

def sync_kline_one(db, code, days=60):
    """同步单只股票的日K线"""
    try:
        from src.datasource.sdicsc_client import get_kline
        k = get_kline(code, 'day', days); ins = 0
        for row in k:
            cur = db.execute(
                "INSERT OR IGNORE INTO kline_day(stock_code,trade_date,open,high,low,close,volume,amount) VALUES (?,?,?,?,?,?,?,?)",
                (code,row['time'],row['open'],row['high'],row['low'],
                 row['close'],row.get('volume',0),row.get('amount',0)))
            if cur.rowcount > 0: ins += 1
        db.commit()
        return ins
    except Exception as e:
        return 0

# ── 图表 ────────────────────────────────────────
def _tag_summary(db):
    """获取标签统计"""
    rows = db.execute("SELECT category, COUNT(*) as cnt, MAX(fetched_at) as last FROM research_article GROUP BY category ORDER BY cnt DESC").fetchall()
    return [{"category": r[0], "cnt": r[1], "last": r[2]} for r in rows]


def plot_quant_kline(df, name):
    if df.empty or len(df) < 30: return None
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.02,
                         row_heights=[0.5,0.15,0.35])
    fig.add_trace(go.Candlestick(x=df["trade_date"],open=df["open"],high=df["high"],
                  low=df["low"],close=df["close"],name="",showlegend=False,
                  increasing_line_color=UP, increasing_fillcolor=UP_FILL,
                  decreasing_line_color=DOWN, decreasing_fillcolor=DOWN_FILL), row=1, col=1)
    for m,c,n in [(5,"#f97316","MA5"),(20,"#facc15","MA20"),(60,"#8b5cf6","MA60")]:
        if len(df) >= m: fig.add_trace(go.Scatter(x=df["trade_date"],y=df["close"].rolling(m).mean(),
                      line=dict(color=c,width=1),name=n), row=1, col=1)
    bc = [UP if r["close"]>=r["open"] else DOWN for _,r in df.iterrows()]
    fig.add_trace(go.Bar(x=df["trade_date"],y=df["volume"],marker_color=bc,name=""), row=2, col=1)
    rsi = calc_rsi(df)
    if rsi is not None:
        t = df["trade_date"].values[-len(rsi):]
        fig.add_trace(go.Scatter(x=t, y=rsi, line=dict(color="#22d3ee",width=1),name="RSI(14)"), row=3, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color=UP, row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color=DOWN, row=3, col=1)
    fig.update_layout(height=450, template="plotly_dark", margin=dict(l=10,r=10,t=10,b=10),
                      xaxis_rangeslider_visible=False, hovermode="x unified",
                      paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color=TEXT))
    fig.update_xaxes(gridcolor=GRID); fig.update_yaxes(gridcolor=GRID)
    return fig

def calc_rsi(df, n=14):
    if len(df) < n+1: return None
    d = df["close"].diff(); g=d.clip(0); l=-d.clip(0)
    return (100-100/(1+g.rolling(n).mean()/l.rolling(n).mean())).values

def plot_fin_trend(df):
    if df.empty: return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["period"],y=df["revenue"]/1e8,mode="lines+markers",name="营收(亿)",line=dict(color="#3b82f6")))
    fig.add_trace(go.Scatter(x=df["period"],y=df["net_profit"]/1e8,mode="lines+markers",name="净利润(亿)",line=dict(color="#f59e0b")))
    fig.update_layout(height=250, template="plotly_dark", margin=dict(l=10,r=10,t=10,b=10),
                      paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color=TEXT,size=10),
                      xaxis=dict(gridcolor="#1e293b"), yaxis=dict(gridcolor="#1e293b"))
    return fig

# ── 格式化 ──────────────────────────────────────
def fmt(val, d=2):
    if val is None or (isinstance(val,float) and math.isnan(val)): return "-"
    try: return f"{float(val):.{d}f}"
    except: return str(val) if str(val).strip() else "-"

def cor(s):
    """涨跌颜色"""
    if not s or s == "-": return FLAT
    s = str(s).replace("%","")
    try: return UP if float(s)>0 else DOWN if float(s)<0 else FLAT
    except: return FLAT

# ── 主界面 ──────────────────────────────────────
def main():
    db = get_db()
    
    # 顶栏
    r1, r2, r3, r4 = st.columns([2,0.5,1.5,0.5])
    with r1: st.markdown(f"<h1 style='color:{TEXT}'>📊 QuantLab</h1>", unsafe_allow_html=True)
    with r2:
        if st.button("🔄", help="一键同步"):
            with st.status("⏳ 同步中...", expanded=True) as status:
                codes = [r[0] for r in db.execute("SELECT stock_code FROM portfolio_stock").fetchall()]
                # 行情
                status.update(label="📊 同步行情...")
                r = sync_data(db, codes)
                if r["ok"]: st.toast(f"✅ 行情 {r['inserted']} 条"); st.cache_data.clear()
                else: st.error(r["msg"])
                # K线(快速3只)
                status.update(label="📈 同步K线...")
                for c in codes[:3]: sync_kline_one(db, c, 5)
                # 分时(第一只)
                status.update(label="⏱ 同步分时...")
                try:
                    from src.datasource.sdicsc_client import get_trend
                    raw = get_trend(codes[0]); td = raw.get("timeData",[]); date = raw.get("meta",{}).get("date","")
                    for t in td:
                        db.execute("INSERT OR IGNORE INTO trend_data(stock_code,trade_date,time_seq,price,avg_price,volume,change_amt,change_pct) VALUES (?,?,?,?,?,?,?,?)",
                                   (codes[0],date,t['time'],t['price'],t.get('avgPrice'),t.get('volume',0),t.get('change',0),t.get('changePercent',"")))
                    db.commit()
                except Exception as e:
                    st.toast(f"⚠️ 分时同步失败: {e}")
                status.update(label="✅ 同步完成", state="complete")
                st.rerun()
    with r3: search = st.text_input("🔍", placeholder="过滤名称/代码", label_visibility="collapsed")
    with r4: view = st.segmented_control("",["📋全部","⭐自选","🔴持仓","📰研报"],default="📋全部",key="v",label_visibility="collapsed")

    qdf = load_quotes(db)
    
    # 研报模式 — 独立阅览，不依赖选股
    if "研报" in view:
        st.subheader("📰 宏观研报 & 智能选股")
        c1, c2 = st.columns([3,1])
        with c2:
            if st.button("📥 拉取研报", type="primary", use_container_width=True):
                from src.analyst.research import run_daily_research
                with st.spinner("⏳ 拉取中... 约需60秒"):
                    r = run_daily_research(str(Path(__file__).parent.parent / "data" / "stock.db"))
                st.success(f"✅ 完成: {sum(r.values())} 篇")
                st.cache_data.clear(); st.rerun()
        with c1:
            cnt = db.execute("SELECT COUNT(*) FROM research_article").fetchone()[0]
            st.caption(f"共 {cnt} 篇 · 点击下方展开阅读")
        
        # 标签筛选
        tags = db.execute("SELECT tag, category FROM tag_library WHERE is_active=1 ORDER BY category,tag").fetchall()
        tag_cats = {}
        for t in tags: tag_cats.setdefault(t["category"], []).append(t["tag"])
        sel_cat = st.selectbox("分类", ["全部"] + sorted(tag_cats.keys()))
        
        if sel_cat != "全部":
            articles = db.execute("SELECT title,content,fetched_at,category FROM research_article WHERE category=? OR category LIKE ? ORDER BY fetched_at DESC LIMIT 30",
                                 (sel_cat, f"{sel_cat}·%")).fetchall()
        else:
            articles = db.execute("SELECT title,content,fetched_at,category FROM research_article ORDER BY fetched_at DESC LIMIT 30").fetchall()
        
        if articles:
            for a in articles:
                with st.expander(f"[{a['category']}] {a['title'][:80]} ({a['fetched_at'][:10]})"):
                    st.markdown(a["content"])
        else:
            st.info("暂无研报，点击「📥 拉取研报」按钮获取")
        
        # 标签统计
        with st.expander("📊 标签统计"):
            for row in _tag_summary(db):
                st.caption(f"{row['category']}: {row['cnt']} 篇")
        
        # 研报模式下不显示股票内容
        st.stop()

    if qdf.empty: st.info("点击 🔄 同步数据"); return
    
    if "自选" in view: qdf = qdf[qdf["is_holding"]==0]
    elif "持仓" in view: qdf = qdf[qdf["is_holding"]==1]
    if search: qdf = qdf[qdf["name"].str.contains(search,na=False)|qdf["stock_code"].str.contains(search,na=False)]

    # ── 股票选择器（同时控制下方所有面板） ──
    # 确保选中仍在过滤后的列表中
    if "sel_stock" in st.session_state:
        if st.session_state.sel_stock not in qdf["stock_code"].tolist():
            st.session_state.sel_stock = qdf["stock_code"].iloc[0]
    sel_code = st.selectbox(
        "当前分析标的",
        qdf["stock_code"].tolist(),
        format_func=lambda c: f"{qdf[qdf['stock_code']==c]['name'].values[0]} ({c})",
        key="sel_stock"
    )
    
    # 数据表格（可滚动参考）+ 高亮选中行
    cols = {"stock_code":"代码","name":"名称","price":"最新","change_pct":"涨跌幅",
            "pe_ttm":"PE","market_value":"市值","change_20d":"20日","turnover":"换手"}
    display = qdf[list(cols.keys())].copy()
    display.columns = list(cols.values())
    
    # 高亮选中行
    def highlight(s):
        try:
            row_val = display.loc[s.name, "代码"]
            is_sel = row_val == sel_code
        except (KeyError, IndexError):
            is_sel = False
        return ["background-color: #2e4d7d"] * len(s) if is_sel else [""] * len(s)
    
    st.dataframe(display.style.apply(highlight, axis=1),
                 use_container_width=True, height=200,
                 column_config={
                     "涨跌幅": st.column_config.TextColumn("涨跌幅"),
                     "最新": st.column_config.NumberColumn("最新", format="%.2f"),
                     "PE": st.column_config.NumberColumn("PE", format="%.1f"),
                 })

    st.caption(f"共 {len(qdf)} 只 · 选中: {sel_code} ↗ 下方分析面板联動更新")

    # ── 选中股票的信息 ──
    sel = qdf[qdf["stock_code"]==sel_code].iloc[0]
    is_h = bool(sel["is_holding"])
    kdf = load_kline_df(db, sel_code)
    fdf = load_fin_df(db, sel_code)

    # ── 主选项卡 ──
    tabs = st.tabs(["📊 因子 & 信号", "📈 技术图表", "📋 量化分析", "💹 财务趋势", "📰 宏观研报", "🏷️ 操作"])

    # ── Tab 1: 因子信号 ──
    with tabs[0]:
        mom = MomentumAnalyzer.compute(kdf) if not kdf.empty else {}
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("价格", fmt(sel["price"]), sel["change_pct"])
            st.markdown(f"<div style='color:{MUTED};font-size:0.8rem'>{sel['name']} · {sel_code}</div>", unsafe_allow_html=True)
        with c2:
            st.metric("PE_TTM", fmt(sel["pe_ttm"],1))
            st.metric("量比", fmt(sel["volume_ratio"],2))
        with c3:
            if mom:
                st.metric("5日动量", f"{mom['ret_5d']}%", delta_color="off")
                st.markdown(f"<div style='color:{ACCENT}'>{mom['trend']}</div>", unsafe_allow_html=True)
        with c4:
            if mom:
                st.metric("趋势信号", mom['signal'])
                st.metric("动量强度", mom['strength'])

        # 组合概览
        st.divider()
        st.subheader("组合概览")
        ps = PortfolioAnalyzer.summary(qdf)
        if ps:
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("总股票", ps["total"])
            c2.metric("上涨", f"{ps['up']}/{ps['total']} ({ps['up_ratio']}%)")
            c3.metric("下跌", ps["down"])
            c4.metric("持仓", ps["hold"])
            c5.metric("持仓涨跌", f"{ps['hold_pnl']}%")

        # ── 预测面板 ──
        st.divider()
        st.subheader("🔮 下一交易日预测")
        if not kdf.empty and len(kdf) >= 50:
            pde = PatternDiscoveryEngine(sel_code)
            pde.fit(kdf)
            pde.discover_patterns()
            pred = pde.predict()
            summ = pde.summary()
            if pred:
                c1,c2,c3,c4 = st.columns(4)
                dir_icon = {"up":"📈 上涨","down":"📉 下跌","flat":"➡️ 盘整"}
                dir_col = {"up":UP,"down":DOWN,"flat":FLAT}
                c1.markdown(f"<div style='color:{dir_col[pred.direction]};font-size:1.5rem;font-weight:700'>{dir_icon[pred.direction]}</div>", unsafe_allow_html=True)
                c2.metric("置信度", f"{pred.confidence*100:.0f}%")
                c3.metric("预测价格", f"{pred.predicted_price:.2f}")
                c4.markdown(f"<small style='color:{MUTED}'>基于 {len(pred.patterns_used)} 种模式</small><br/>{', '.join(pred.patterns_used[:4])}", unsafe_allow_html=True)
            if summ:
                bt = cached_backtest(sel_code, str(kdf.iloc[-1]["trade_date"]),
                                     tuple(kdf.columns),
                                     tuple(kdf.itertuples(index=False, name=None)))
                if 'accuracy' in bt:
                    st.caption(f"回测准确率: {bt['accuracy']*100:.1f}% ({bt['correct']}/{bt['total']}) · 模式库: {summ['patterns_found']}条 · 收敛: {'✅ 收敛' if summ['is_converged'] else '⏳ 训练中'}")
                    with st.expander("📈 回测绩效（含交易成本）"):
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("累计收益", f"{bt.get('total_return', 0)*100:.1f}%")
                        c2.metric("最大回撤", f"{bt.get('max_drawdown', 0)*100:.1f}%")
                        c3.metric("夏普比率", f"{bt.get('sharpe', 0):.2f}")
                        c4.metric("换仓次数", f"{bt.get('trades', 0)}")
                        pp = bt.get("per_pattern") or {}
                        if pp:
                            st.markdown("**分模式胜率 Top5**")
                            st.dataframe(pd.DataFrame(
                                [{"模式": k, "胜率": f"{v['rate']*100:.1f}%",
                                  "样本": v["total"], "命中": v["hits"]}
                                 for k, v in pp.items()]),
                                use_container_width=True, hide_index=True)
        else:
            st.info("需要≥50个交易日数据训练预测模型")

    # ── Tab 2: 技术图表 ──
    with tabs[1]:
        fig = plot_quant_kline(kdf, sel["name"])
        if fig: st.plotly_chart(fig, use_container_width=True)
        else: st.info("K线数据不足")
        if not kdf.empty and len(kdf) >= 15:
            rsi_arr = calc_rsi(kdf)
            if rsi_arr is not None:
                cur = rsi_arr[-1]
                tag = "超买 🔴" if cur>70 else "超卖 🟢" if cur<30 else "正常 ⚪"
                c1,c2,c3 = st.columns(3)
                c1.metric("RSI(14)", f"{cur:.1f}", tag)
                # MACD 简易金叉死叉
                close = kdf["close"].values
                ema12 = pd.Series(close).ewm(span=12).mean().values
                ema26 = pd.Series(close).ewm(span=26).mean().values
                dif = ema12 - ema26
                dea = pd.Series(dif).ewm(span=9).mean().values
                bar = 2*(dif - dea)
                c2.metric("MACD DIF", f"{dif[-1]:.2f}")
                sig = "金叉 🟢" if bar[-1]>0 and bar[-2]<=0 else "死叉 🔴" if bar[-1]<0 and bar[-2]>=0 else "-"
                c3.metric("MACD信号", sig)

    # ── Tab 3: 量化分析 ──
    with tabs[2]:
        if kdf.empty or len(kdf) < 30:
            st.info("需要至少30个交易日K线数据")
        else:
            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("🏷️ 市场状态 (GMM)")
                rc = RegimeClassifier(4)
                rc.fit(kdf)
                if rc._fitted:
                    regimes = rc.get_regime_series(kdf)
                    if regimes:
                        # 最新状态
                        latest_regime = regimes[-1][1]
                        st.metric("当前状态", latest_regime)
                        # 状态分布
                        from collections import Counter
                        cnt = Counter(r[1] for r in regimes)
                        tot = sum(cnt.values())
                        st.markdown("**历史状态分布**")
                        for name, count in cnt.most_common():
                            st.markdown(f"{name}: {count}/{tot} ({count/tot*100:.0f}%)")
                else:
                    st.info("数据不足以分类")
            with c2:
                st.subheader("🔄 马尔可夫转移")
                mt = MarkovTransition()
                if len(kdf) > 50:
                    returns = kdf.sort_values("trade_date")["close"].pct_change().dropna().values * 100
                    mt.fit(returns)
                    if mt.transition_matrix is not None:
                        st.metric("市场持续性", f"{mt.get_persistence():.2f}")
                        st.markdown("**下一日状态概率**")
                        probs = mt.next_state_prob(returns[-1] if len(returns) > 0 else 0)
                        for state, prob in probs.items():
                            st.markdown(f"{state}: {prob*100:.1f}%")
                        st.markdown("**稳态分布**")
                        if mt.steady_state is not None:
                            for i, s in enumerate(mt.states):
                                if i < len(mt.steady_state):
                                    st.markdown(f"{s}: {mt.steady_state[i]*100:.1f}%")
            
            # 动量热图
            st.divider()
            st.subheader("📊 多周期动量矩阵")
            show_hold = st.checkbox("仅显示持仓", value=False, key="mom_hold_only")
            codes = (qdf[qdf["is_holding"]==1]["stock_code"].tolist()
                     if show_hold else qdf["stock_code"].tolist())
            name_map = dict(zip(qdf["stock_code"], qdf["name"]))
            mom_data = []
            for code in codes:
                k = load_kline_df(db, code)
                if k.empty: continue
                m = MomentumAnalyzer.compute(k)
                if m:
                    mom_data.append({"名称": name_map.get(code, code),
                                     "5日": f"{m['ret_5d']}%", "20日": f"{m['ret_20d']}%",
                                     "60日": f"{m['ret_60d']}%",
                                     "趋势": m['trend'], "信号": m['signal']})
            if mom_data:
                st.dataframe(pd.DataFrame(mom_data), use_container_width=True, hide_index=True)
            else:
                st.caption("暂无动量数据")

    # ── Tab 4: 财务趋势 ──
    with tabs[3]:
        if not fdf.empty:
            fig = plot_fin_trend(fdf)
            if fig: st.plotly_chart(fig, use_container_width=True)
            L = fdf.iloc[-1]
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("营收", f"{L['revenue']/1e8:.1f}亿" if pd.notna(L['revenue']) else "-")
            c2.metric("净利润", f"{L['net_profit']/1e8:.1f}亿" if pd.notna(L['net_profit']) else "-")
            c3.metric("EPS", f"{L['eps']:.2f}" if pd.notna(L['eps']) else "-")
            c4.metric("ROE", f"{L['roe']:.1f}%" if pd.notna(L['roe']) else "-")
            c5.metric("负债率", f"{L['debt_ratio']:.1f}%" if pd.notna(L['debt_ratio']) else "-")
        else: st.info("暂无财务数据")

    # ── Tab 5: 宏观研报 ──
    with tabs[4]:
        st.subheader("📰 宏观研报")
        
        # 同步按钮
        c1, c2 = st.columns([3,1])
        with c2:
            if st.button("📥 拉取研报", type="primary", use_container_width=True):
                from src.analyst.research import run_daily_research
                with st.spinner("⏳ 拉取中... 约需60秒"):
                    r = run_daily_research(str(Path(__file__).parent.parent / "data" / "stock.db"))
                st.success(f"✅ 完成: {sum(r.values())} 篇")
                st.cache_data.clear(); st.rerun()
        with c1:
            st.caption(f"共 {db.execute('SELECT COUNT(*) FROM research_article').fetchone()[0]} 篇研报")
        
        # 标签库浏览
        tags = db.execute("SELECT tag, category, description FROM tag_library WHERE is_active=1 ORDER BY category, tag").fetchall()
        tag_cats = {}
        for t in tags: tag_cats.setdefault(t["category"], []).append(t["tag"])
        
        col1, col2 = st.columns([1, 3])
        with col1:
            st.markdown("**🏷️ 标签筛选**")
            sel_tag_cat = st.selectbox("分类", sorted(tag_cats.keys()), label_visibility="collapsed")
            if sel_tag_cat:
                sel_tag = st.radio("标签", tag_cats[sel_tag_cat], label_visibility="collapsed")
            else:
                sel_tag = None
        
        with col2:
            if sel_tag:
                articles = db.execute("SELECT title, content, fetched_at, category FROM research_article WHERE category=? ORDER BY fetched_at DESC LIMIT 20", (sel_tag,)).fetchall()
            else:
                articles = db.execute("SELECT title, content, fetched_at, category FROM research_article ORDER BY fetched_at DESC LIMIT 20").fetchall()
            
            if articles:
                for a in articles:
                    tag_display = a["category"].replace("·", " · ")
                    with st.expander(f"[{tag_display}] {a['title'][:60]}  ({a['fetched_at'][:10]})"):
                        # 检测是否为选股推荐JSON
                        if a["category"].startswith("选股"):
                            try:
                                content = json.loads(a["content"])
                                if isinstance(content, dict) and "codes" in content:
                                    st.markdown("**推荐股票**")
                                    for code, name in zip(content.get("codes",[]), content.get("names",[])):
                                        code_clean = code.replace(".SZ","").replace(".SH","")
                                        in_db = db.execute("SELECT 1 FROM stock_basic WHERE stock_code=?", (code_clean,)).fetchone()
                                        tag_icon = "✅" if in_db else "⬜"
                                        st.caption(f"{tag_icon} {name} ({code})")
                            except: st.markdown(a["content"])
                        else:
                            st.markdown(a["content"])
            else:
                st.info("暂无研报，运行 python3 src/analyst/research.py --daily 拉取")

        # 标签统计
        st.divider()
        with st.expander("📊 标签统计"):
            for row in _tag_summary(db):
                st.caption(f"{row['category']}: {row['cnt']} 篇 (最新{row['last'][:10]})")

    # ── Tab 6: 操作 ──
    with tabs[5]:
        st.markdown(f"**{sel['name']}** ({sel_code})")
        st.markdown(f"当前: {'🔴 持仓' if is_h else '⚪ 自选'}")
        if st.button("📌 切换持仓", use_container_width=True):
            toggle_holding(db, sel_code); st.rerun()
        st.divider()
        st.markdown("**📌 自选股管理**")
        new_code = st.text_input("添加股票代码（如 600519 / 000001）", key="add_stock_input")
        if st.button("➕ 添加自选", use_container_width=True):
            if new_code:
                msg = add_stock(db, new_code)
                st.toast(msg)
                if "已添加" in msg:
                    st.rerun()
        watch_codes = [r[0] for r in db.execute("SELECT stock_code FROM portfolio_stock ORDER BY stock_code").fetchall()]
        if watch_codes:
            del_code = st.selectbox("从自选移除", watch_codes, key="del_stock_sel")
            if st.button("🗑 移除自选", use_container_width=True):
                remove_stock(db, del_code)
                st.toast(f"已移除 {del_code}"); st.rerun()
        st.divider()
        st.markdown("**数据状态**")
        st.caption(f"K线: {len(kdf)} 天")
        st.caption(f"财务: {len(fdf)} 期")
        ls = db.execute("SELECT MAX(fetched_at) FROM real_time_quote").fetchone()[0]
        if ls: st.caption(f"更新于: {ls[11:19]}")
        st.divider()
        with st.expander("📊 数据覆盖率"):
            from src.service.coverage import compute_coverage
            cov = compute_coverage(db, persist=False)  # UI 只读展示，不落库
            if cov:
                st.dataframe(pd.DataFrame(cov), use_container_width=True, hide_index=True)
            else:
                st.caption("暂无自选股")
        st.divider()
        st.markdown("**📤 数据导出**")
        if st.button("导出行情CSV", use_container_width=True):
            q = db.execute("SELECT * FROM real_time_quote WHERE fetched_at=(SELECT MAX(fetched_at) FROM real_time_quote)").fetchall()
            if q:
                out = io.StringIO(); w = csv.writer(out)
                w.writerow(q[0].keys())
                for row in q: w.writerow(row)
                st.download_button("📥 下载", out.getvalue(), "quotes.csv", "text/csv")
        if st.button("导出K线CSV", use_container_width=True):
            q = db.execute("SELECT * FROM kline_day WHERE stock_code=? ORDER BY trade_date DESC LIMIT 500", (sel_code,)).fetchall()
            if q:
                out = io.StringIO(); w = csv.writer(out)
                w.writerow(q[0].keys())
                for row in q: w.writerow(row)
                st.download_button("📥 下载", out.getvalue(), f"kline_{sel_code}.csv", "text/csv")

    # ── 侧边栏 ──
    with st.sidebar:
        st.subheader("📊 QuantLab")
        st.caption("量化交易分析工具")
        st.divider()
        ps = PortfolioAnalyzer.summary(qdf)
        if ps:
            st.metric("组合股票", ps["total"])
            st.metric("上涨占比", f"{ps['up_ratio']}%")
            st.metric("持仓数", ps["hold"])
        st.divider()
        st.caption(f"行情: {db.execute('SELECT COUNT(*) FROM real_time_quote').fetchone()[0]} 条")
        st.caption(f"K线: {db.execute('SELECT COUNT(*) FROM kline_day').fetchone()[0]} 条")
        st.caption(f"财务: {db.execute('SELECT COUNT(*) FROM financial_statement').fetchone()[0]} 条")
        st.caption(f"研报: {db.execute('SELECT COUNT(*) FROM research_article').fetchone()[0]} 篇")
        st.caption(f"模式: {db.execute('SELECT COUNT(*) FROM pattern_library').fetchone()[0]} 条")
        st.divider()
        st.caption("QuantLab © 2026 鹿溪联合创新实验室")
        st.caption("数据仅供参考，不构成投资建议")

if __name__ == "__main__":
    main()
