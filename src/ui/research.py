"""宏观研报面板（顶栏与 Tab 共用）。"""
from __future__ import annotations

import json


def render_research(st, db, *, standalone: bool = False) -> None:
    st.subheader("📰 宏观研报")
    c1, c2 = st.columns([3, 1])
    with c2:
        if st.button("📥 拉取研报", type="primary", use_container_width=True,
                     key="pull_research"):
            from pathlib import Path
            from src.analyst.research import run_daily_research
            db_path = str(Path(__file__).resolve().parent.parent.parent / "data" / "stock.db")
            with st.spinner("⏳ 拉取中... 约需60秒"):
                r = run_daily_research(db_path)
            st.success(f"✅ 完成: {sum(r.values())} 篇")
            st.cache_data.clear()
            st.rerun()
    with c1:
        cnt = db.execute("SELECT COUNT(*) FROM research_article").fetchone()[0]
        st.caption(f"共 {cnt} 篇 · 点击下方展开阅读")

    tags = db.execute(
        "SELECT tag, category FROM tag_library WHERE is_active=1 ORDER BY category,tag"
    ).fetchall()
    tag_cats: dict[str, list] = {}
    for t in tags:
        tag_cats.setdefault(t["category"], []).append(t["tag"])

    sel_cat = st.selectbox("分类", ["全部"] + sorted(tag_cats.keys()),
                           key="research_cat")
    if sel_cat != "全部":
        articles = db.execute(
            "SELECT title,content,fetched_at,category FROM research_article "
            "WHERE category=? OR category LIKE ? ORDER BY fetched_at DESC LIMIT 30",
            (sel_cat, f"{sel_cat}·%")).fetchall()
    else:
        articles = db.execute(
            "SELECT title,content,fetched_at,category FROM research_article "
            "ORDER BY fetched_at DESC LIMIT 30").fetchall()

    if articles:
        for a in articles:
            with st.expander(f"[{a['category']}] {a['title'][:80]} ({str(a['fetched_at'])[:10]})"):
                if str(a["category"]).startswith("选股"):
                    try:
                        content = json.loads(a["content"])
                        if isinstance(content, dict) and "codes" in content:
                            st.markdown("**推荐股票**")
                            for code, name in zip(content.get("codes", []),
                                                  content.get("names", [])):
                                code_clean = str(code).replace(".SZ", "").replace(".SH", "")
                                in_db = db.execute(
                                    "SELECT 1 FROM stock_basic WHERE stock_code=?",
                                    (code_clean,)).fetchone()
                                st.caption(f"{'✅' if in_db else '⬜'} {name} ({code})")
                        else:
                            st.markdown(a["content"])
                    except (json.JSONDecodeError, TypeError, ValueError):
                        st.markdown(a["content"])
                else:
                    st.markdown(a["content"])
    else:
        st.info("暂无研报，点击「📥 拉取研报」获取")

    with st.expander("📊 标签统计"):
        rows = db.execute(
            "SELECT category, COUNT(*) as cnt, MAX(fetched_at) as last "
            "FROM research_article GROUP BY category ORDER BY cnt DESC"
        ).fetchall()
        for row in rows:
            st.caption(f"{row[0]}: {row[1]} 篇")
