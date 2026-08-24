"""
衡流 · HengLiu（QuantFlow）— 量化分析与模式发现
数据源: 国投证券(行情) + 国信证券(财务)
"""
import sys, csv, io
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from src.db.connection import open_db
from src.service.portfolio import (
    seed_if_empty, add_stock, remove_stock, toggle_holding,
)
from src.quant.engine import RegimeClassifier, MarkovTransition, MomentumAnalyzer, PortfolioAnalyzer
from src.quant.pattern_discovery import PatternDiscoveryEngine
from src.quant.prediction_loop import oos_stats
from src.ui.theme import TEXT, MUTED, ACCENT, UP, DOWN, FLAT, apply_theme
from src.ui.charts import plot_quant_kline, plot_fin_trend, calc_rsi, fmt
from src.ui.research import render_research

st.set_page_config(
    page_title="衡流 · HengLiu - 量化分析与模式发现",
    page_icon=str(Path(__file__).parent / "assets" / "brand" / "favicon.svg"),
    layout="wide",
    initial_sidebar_state="expanded")
apply_theme(st)


@st.cache_resource
def get_db():
    c = open_db(app=True)
    seed_if_empty(c)
    return c


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
    return pd.read_sql("SELECT * FROM kline_day WHERE stock_code=? ORDER BY trade_date",
                       _db, params=(code,))


@st.cache_data(ttl=300)
def load_fin_df(_db, code):
    return pd.read_sql(
        "SELECT report_year||report_type AS period,revenue,net_profit,eps,"
        "gross_margin,roe,debt_ratio FROM financial_statement "
        "WHERE stock_code=? ORDER BY report_year,report_type",
        _db, params=(code,))


@st.cache_data(ttl=600)
def cached_backtest(code: str, last_date: str, cols: tuple, rows: tuple) -> dict:
    kdf = pd.DataFrame(list(rows), columns=list(cols))
    pde = PatternDiscoveryEngine(code)
    pde.fit(kdf)
    return pde.backtest(window=50, step=2)


def _ui_sync(db):
    from src.service.lock import try_single_instance
    from src.service.pipeline import sync_quotes, sync_kline, sync_trend
    codes = [r[0] for r in db.execute("SELECT stock_code FROM portfolio_stock")]
    with try_single_instance("数据同步") as ok:
        if not ok:
            return {"ok": False, "msg": "同步已在运行（定时任务或另一窗口），请稍后"}
        with st.status("⏳ 同步中...", expanded=True) as status:
            status.update(label="📊 同步行情...")
            q = sync_quotes(db, codes)
            if q.ok:
                st.toast(f"✅ 行情 {q.inserted} 条")
            else:
                st.error(q.message)
            status.update(label="📈 同步K线...")
            sync_kline(db, codes)
            status.update(label="⏱ 同步分时...")
            a_share = [c for c in codes if not str(c).upper().startswith("H")]
            if a_share:
                t = sync_trend(db, a_share)
                if t.errors:
                    st.toast(f"⚠️ 分时部分失败: {t.errors[0]}")
            status.update(label="✅ 同步完成", state="complete")
        st.cache_data.clear()
        return {"ok": True}


def main():
    db = get_db()

    r1, r2, r3, r4 = st.columns([2, 0.5, 1.5, 0.5])
    with r1:
        st.markdown(f"<h1 style='color:{TEXT}'>衡流 · HengLiu</h1>", unsafe_allow_html=True)
        st.caption("审度称衡，守正观流")
    with r2:
        if st.button("🔄", help="同步全部自选行情/K线/分时"):
            r = _ui_sync(db)
            if r.get("ok"):
                st.rerun()
            elif r.get("msg"):
                st.error(r["msg"])
    with r3:
        search = st.text_input("🔍", placeholder="过滤名称/代码", label_visibility="collapsed")
    with r4:
        view = st.segmented_control(
            "", ["📋全部", "⭐自选", "🔴持仓", "📰研报"],
            default="📋全部", key="v", label_visibility="collapsed")

    if "研报" in view:
        render_research(st, db, standalone=True)
        st.stop()

    qdf = load_quotes(db)
    if qdf.empty:
        st.info("点击 🔄 同步数据")
        return

    if "自选" in view:
        qdf = qdf[qdf["is_holding"] == 0]
    elif "持仓" in view:
        qdf = qdf[qdf["is_holding"] == 1]
    if search:
        qdf = qdf[qdf["name"].str.contains(search, na=False)
                  | qdf["stock_code"].str.contains(search, na=False)]
    if qdf.empty:
        st.info("无匹配股票")
        return

    if "sel_stock" in st.session_state:
        if st.session_state.sel_stock not in qdf["stock_code"].tolist():
            st.session_state.sel_stock = qdf["stock_code"].iloc[0]
    sel_code = st.selectbox(
        "当前分析标的",
        qdf["stock_code"].tolist(),
        format_func=lambda c: f"{qdf[qdf['stock_code']==c]['name'].values[0]} ({c})",
        key="sel_stock")

    cols = {"stock_code": "代码", "name": "名称", "price": "最新", "change_pct": "涨跌幅",
            "pe_ttm": "PE", "market_value": "市值", "change_20d": "20日", "turnover": "换手"}
    display = qdf[list(cols.keys())].copy()
    display.columns = list(cols.values())

    def highlight(s):
        try:
            is_sel = display.loc[s.name, "代码"] == sel_code
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
    st.caption(f"共 {len(qdf)} 只 · 选中: {sel_code}")

    sel = qdf[qdf["stock_code"] == sel_code].iloc[0]
    is_h = bool(sel["is_holding"])
    kdf = load_kline_df(db, sel_code)
    fdf = load_fin_df(db, sel_code)

    tabs = st.tabs(["📊 因子 & 信号", "📈 技术图表", "📋 量化分析",
                    "💹 财务趋势", "📰 宏观研报", "🏷️ 操作"])

    with tabs[0]:
        mom = MomentumAnalyzer.compute(kdf) if not kdf.empty else {}
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("价格", fmt(sel["price"]), sel["change_pct"])
            st.markdown(
                f"<div style='color:{MUTED};font-size:0.8rem'>{sel['name']} · {sel_code}</div>",
                unsafe_allow_html=True)
        with c2:
            st.metric("PE_TTM", fmt(sel["pe_ttm"], 1))
            st.metric("量比", fmt(sel["volume_ratio"], 2))
        with c3:
            if mom:
                st.metric("5日动量", f"{mom['ret_5d']}%", delta_color="off")
                st.markdown(f"<div style='color:{ACCENT}'>{mom['trend']}</div>",
                            unsafe_allow_html=True)
        with c4:
            if mom:
                st.metric("趋势信号", mom["signal"])
                st.metric("动量强度", mom["strength"])

        st.divider()
        st.subheader("组合概览")
        ps = PortfolioAnalyzer.summary(qdf)
        if ps:
            a, b, c, d, e = st.columns(5)
            a.metric("总股票", ps["total"])
            b.metric("上涨", f"{ps['up']}/{ps['total']} ({ps['up_ratio']}%)")
            c.metric("下跌", ps["down"])
            d.metric("持仓", ps["hold"])
            e.metric("持仓涨跌", f"{ps['hold_pnl']}%")

        st.divider()
        st.subheader("样本外结算（prediction_log）")
        stats = oos_stats(db)
        if stats["n"] == 0:
            st.caption("尚无已结算预测。同步后次日才会回填实际涨跌。")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("已结算", f"{stats['hits']}/{stats['n']}")
            c2.metric("命中率", f"{stats['accuracy']*100:.1f}%")
            c3.metric("多数类基线",
                      f"{stats['majority_baseline']*100:.1f}% ({stats['majority_class']})")
            vs = stats["vs_baseline"]
            c4.metric("相对基线", f"{vs*100:+.1f}pt")
            st.caption("三分类均匀 33% 不是诚实零假设；多数类（常为盘整）才是。")

        st.divider()
        st.subheader("下一交易日预测")
        if not kdf.empty and len(kdf) >= 50:
            pde = PatternDiscoveryEngine(sel_code)
            pde.fit(kdf)
            pde.discover_patterns()
            pred = pde.predict()
            summ = pde.summary()
            if pred:
                c1, c2, c3, c4 = st.columns(4)
                dir_icon = {"up": "📈 上涨", "down": "📉 下跌", "flat": "➡️ 盘整"}
                dir_col = {"up": UP, "down": DOWN, "flat": FLAT}
                c1.markdown(
                    f"<div style='color:{dir_col[pred.direction]};font-size:1.5rem;"
                    f"font-weight:700'>{dir_icon[pred.direction]}</div>",
                    unsafe_allow_html=True)
                c2.metric("置信度", f"{pred.confidence*100:.0f}%")
                c3.metric("预测价格", f"{pred.predicted_price:.2f}")
                c4.markdown(
                    f"<small style='color:{MUTED}'>基于 {len(pred.patterns_used)} 种模式</small>"
                    f"<br/>{', '.join(pred.patterns_used[:4])}",
                    unsafe_allow_html=True)
            if summ:
                bt = cached_backtest(
                    sel_code, str(kdf.iloc[-1]["trade_date"]),
                    tuple(kdf.columns),
                    tuple(kdf.itertuples(index=False, name=None)))
                if "accuracy" in bt:
                    st.caption(
                        f"滑动窗口回测准确率: {bt['accuracy']*100:.1f}% "
                        f"({bt['correct']}/{bt['total']}) · 模式: {summ['patterns_found']}条"
                        " · 回测≠实盘")
                    with st.expander("📈 回测绩效（含交易成本，仅做多/空仓）"):
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

    with tabs[1]:
        fig = plot_quant_kline(kdf, sel["name"])
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("K线数据不足")
        if not kdf.empty and len(kdf) >= 15:
            rsi_arr = calc_rsi(kdf)
            if rsi_arr is not None:
                cur = rsi_arr[-1]
                tag = "超买 🔴" if cur > 70 else "超卖 🟢" if cur < 30 else "正常 ⚪"
                c1, c2, c3 = st.columns(3)
                c1.metric("RSI(14)", f"{cur:.1f}", tag)
                close = kdf["close"].values
                ema12 = pd.Series(close).ewm(span=12).mean().values
                ema26 = pd.Series(close).ewm(span=26).mean().values
                dif = ema12 - ema26
                dea = pd.Series(dif).ewm(span=9).mean().values
                bar = 2 * (dif - dea)
                c2.metric("MACD DIF", f"{dif[-1]:.2f}")
                sig = ("金叉 🟢" if bar[-1] > 0 and bar[-2] <= 0
                       else "死叉 🔴" if bar[-1] < 0 and bar[-2] >= 0 else "-")
                c3.metric("MACD信号", sig)

    with tabs[2]:
        if kdf.empty or len(kdf) < 30:
            st.info("需要至少30个交易日K线数据")
        else:
            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("市场状态 (GMM)")
                st.caption("全样本描述性聚类，不是可交易的实时状态。")
                rc = RegimeClassifier(4)
                rc.fit(kdf)
                if rc._fitted:
                    regimes = rc.get_regime_series(kdf)
                    if regimes:
                        st.metric("样本末状态", regimes[-1][1])
                        from collections import Counter
                        cnt = Counter(r[1] for r in regimes)
                        tot = sum(cnt.values())
                        st.markdown("**历史状态分布**")
                        for name, count in cnt.most_common():
                            st.markdown(f"{name}: {count}/{tot} ({count/tot*100:.0f}%)")
                else:
                    st.info("数据不足以分类")
            with c2:
                st.subheader("马尔可夫转移")
                mt = MarkovTransition()
                if len(kdf) > 50:
                    returns = kdf.sort_values("trade_date")["close"].pct_change().dropna().values * 100
                    mt.fit(returns)
                    if mt.transition_matrix is not None:
                        st.metric("市场持续性", f"{mt.get_persistence():.2f}")
                        st.markdown("**下一日状态概率**")
                        probs = mt.next_state_prob(returns[-1] if len(returns) else 0)
                        for state, prob in probs.items():
                            st.markdown(f"{state}: {prob*100:.1f}%")
            st.divider()
            st.subheader("多周期动量矩阵")
            show_hold = st.checkbox("仅显示持仓", value=False, key="mom_hold_only")
            codes = (qdf[qdf["is_holding"] == 1]["stock_code"].tolist()
                     if show_hold else qdf["stock_code"].tolist())
            name_map = dict(zip(qdf["stock_code"], qdf["name"]))
            mom_data = []
            for code in codes:
                k = load_kline_df(db, code)
                if k.empty:
                    continue
                m = MomentumAnalyzer.compute(k)
                if m:
                    mom_data.append({"名称": name_map.get(code, code),
                                     "5日": f"{m['ret_5d']}%", "20日": f"{m['ret_20d']}%",
                                     "60日": f"{m['ret_60d']}%",
                                     "趋势": m["trend"], "信号": m["signal"]})
            if mom_data:
                st.dataframe(pd.DataFrame(mom_data), use_container_width=True, hide_index=True)

    with tabs[3]:
        if not fdf.empty:
            fig = plot_fin_trend(fdf)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
            L = fdf.iloc[-1]
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("营收", f"{L['revenue']/1e8:.1f}亿" if pd.notna(L["revenue"]) else "-")
            c2.metric("净利润", f"{L['net_profit']/1e8:.1f}亿" if pd.notna(L["net_profit"]) else "-")
            c3.metric("EPS", f"{L['eps']:.2f}" if pd.notna(L["eps"]) else "-")
            c4.metric("ROE", f"{L['roe']:.1f}%" if pd.notna(L["roe"]) else "-")
            c5.metric("负债率", f"{L['debt_ratio']:.1f}%" if pd.notna(L["debt_ratio"]) else "-")
        else:
            st.info("暂无财务数据")

    with tabs[4]:
        render_research(st, db)

    with tabs[5]:
        st.markdown(f"**{sel['name']}** ({sel_code})")
        st.markdown(f"当前: {'🔴 持仓' if is_h else '⚪ 自选'}")
        if st.button("📌 切换持仓", use_container_width=True):
            toggle_holding(db, sel_code)
            st.cache_data.clear()
            st.rerun()
        st.divider()
        st.markdown("**📌 自选股管理**")
        new_code = st.text_input("添加股票代码（如 600519 / 000001）", key="add_stock_input")
        if st.button("➕ 添加自选", use_container_width=True):
            if new_code:
                msg = add_stock(db, new_code)
                st.toast(msg)
                if "已添加" in msg:
                    st.cache_data.clear()
                    st.rerun()
        watch_codes = [r[0] for r in db.execute(
            "SELECT stock_code FROM portfolio_stock ORDER BY stock_code")]
        if watch_codes:
            del_code = st.selectbox("从自选移除", watch_codes, key="del_stock_sel")
            if st.button("🗑 移除自选", use_container_width=True):
                remove_stock(db, del_code)
                st.cache_data.clear()
                st.toast(f"已移除 {del_code}")
                st.rerun()
        st.divider()
        st.markdown("**数据状态**")
        st.caption(f"K线: {len(kdf)} 天")
        st.caption(f"财务: {len(fdf)} 期")
        ls = db.execute("SELECT MAX(fetched_at) FROM real_time_quote").fetchone()[0]
        if ls:
            st.caption(f"更新于: {ls[11:19] if len(str(ls)) > 11 else ls}")
        with st.expander("📊 数据覆盖率"):
            from src.service.coverage import compute_coverage
            cov = compute_coverage(db, persist=False)
            if cov:
                st.dataframe(pd.DataFrame(cov), use_container_width=True, hide_index=True)
        st.divider()
        st.markdown("**📤 数据导出**")
        if st.button("导出行情CSV", use_container_width=True):
            q = db.execute(
                "SELECT * FROM real_time_quote WHERE fetched_at="
                "(SELECT MAX(fetched_at) FROM real_time_quote)").fetchall()
            if q:
                out = io.StringIO()
                w = csv.writer(out)
                w.writerow(q[0].keys())
                for row in q:
                    w.writerow(row)
                st.download_button("📥 下载", out.getvalue(), "quotes.csv", "text/csv")
        if st.button("导出K线CSV", use_container_width=True):
            q = db.execute(
                "SELECT * FROM kline_day WHERE stock_code=? ORDER BY trade_date DESC LIMIT 500",
                (sel_code,)).fetchall()
            if q:
                out = io.StringIO()
                w = csv.writer(out)
                w.writerow(q[0].keys())
                for row in q:
                    w.writerow(row)
                st.download_button("📥 下载", out.getvalue(), f"kline_{sel_code}.csv", "text/csv")

    with st.sidebar:
        st.image(str(Path(__file__).parent / "assets" / "brand" / "logo.svg"), use_container_width=True)
        st.caption("审度称衡，守正观流")
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
        st.caption("衡流 · HengLiu © 2026 鹿溪联合创新实验室")
        st.caption("本工具仅供量化模式研究，不构成投资建议")


if __name__ == "__main__":
    main()
