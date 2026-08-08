"""
历史研报全量回填 — 按年份逐个拉取宏观数据
用法:  nohup python3 src/sync_research_history.py > data/sync_history.log 2>&1 &
       tail -f data/sync_history.log
"""

import sys, os, time, json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
from src.analyst.research import execute_query, format_response

LOG = Path(__file__).parent.parent / "data" / "sync_history.log"
DB = Path(__file__).parent.parent / "data" / "stock.db"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# 年份范围：2015 ~ 2026（12年）
YEARS = list(range(2015, 2027))

# 按年份的查询模板
YEARLY_QUERIES = [
    (lambda y: f"中国GDP同比增速 {y}年", lambda y: f"宏观·GDP·{y}"),
    (lambda y: f"中国CPI同比 {y}年变化趋势", lambda y: f"宏观·CPI·{y}"),
    (lambda y: f"中国PPI同比 {y}年变化趋势", lambda y: f"宏观·PPI·{y}"),
    (lambda y: f"中国M2货币供应量 {y}年趋势", lambda y: f"宏观·货币·{y}"),
    (lambda y: f"中国制造业PMI {y}年走势", lambda y: f"宏观·PMI·{y}"),
]

# 季度查询（精细化）
QUARTERLY_QUERIES = [
    (lambda y, q: f"中国GDP同比增速 {y}年第{q}季度", lambda y, q: f"宏观·GDP·{y}Q{q}"),
]

# 五年计划/特殊时期
SPECIAL_QUERIES = [
    ("中国GDP增速 2010年至2015年趋势", "宏观·GDP·2010-2015"),
    ("中国GDP增速 2016年至2020年趋势", "宏观·GDP·2016-2020"),
    ("中国GDP增速 2021年至2025年趋势", "宏观·GDP·2021-2025"),
]

# 一次性主题（不依赖年份）
THEMATIC_QUERIES = [
    ("中国人口结构变化 对经济影响", "宏观·人口"),
    ("中国城镇化率 变化趋势", "宏观·城镇化"),
    ("中国居民人均可支配收入 增长趋势", "宏观·收入"),
    ("中国研发投入占GDP比重 变化趋势", "宏观·创新"),
    ("中国进出口贸易结构 变化趋势", "宏观·贸易结构"),
    ("中国外汇储备 历史变化趋势", "宏观·外汇"),
    ("中国地方政府债务 变化趋势", "宏观·财政"),
    ("中国房地产市场 历史周期回顾", "宏观·地产"),
    ("中国制造业转型升级 历程", "宏观·产业"),
    ("中国数字经济规模 增长趋势", "宏观·数字经济"),
    ("中国新能源产业 发展历程", "宏观·新能源"),
    ("全球主要经济体GDP 对比 2010年至2025年", "全球·对比"),
    ("人民币汇率 历史走势 2015年至2025年", "宏观·汇率"),
    ("中国央行基准利率 历史调整 2015年至2025年", "宏观·利率"),
    ("中国A股市场 历史牛熊周期 回顾", "市场·历史"),
]


def main():
    log("=" * 60)
    log("📚 历史研报全量回填开始")
    
    from src.db.schema import init_db
    init_db(str(DB))
    db = sqlite3.connect(str(DB))
    total_ok = 0
    
    # ── 1. 按年查询（5个指标 × 12年 = 60条） ──
    log(f"\n--- 阶段1: 年度数据 ({len(YEARS)}年 × {len(YEARLY_QUERIES)}指标) ---")
    for year in YEARS:
        for q_fn, t_fn in YEARLY_QUERIES:
            query = q_fn(year)
            tag = t_fn(year)
            try:
                raw = execute_query(query)
                article = format_response(raw, query)
                if article and len(article) > 20:
                    db.execute(
                        "INSERT OR REPLACE INTO research_article(category,title,content,source) VALUES(?,?,?,?)",
                        (tag, query, article[:5000], "宏观API"))
                    db.commit()
                    total_ok += 1
                    log(f"  ✅ {tag}: {len(article)}字")
                else:
                    log(f"  ⚠️ {tag}: 内容过短({len(article) if article else 0})")
                time.sleep(3.0)
            except Exception as e:
                log(f"  ❌ {tag}: {e}")
                time.sleep(5.0)
    
    # ── 2. 专题查询 ──
    log(f"\n--- 阶段2: 专题数据 ({len(THEMATIC_QUERIES)}条) ---")
    for query, tag in THEMATIC_QUERIES:
        try:
            raw = execute_query(query)
            article = format_response(raw, query)
            if article and len(article) > 20:
                db.execute(
                    "INSERT OR REPLACE INTO research_article(category,title,content,source) VALUES(?,?,?,?)",
                    (tag, query, article[:5000], "宏观API"))
                db.commit()
                total_ok += 1
                log(f"  ✅ {tag}: {len(article)}字")
            else:
                log(f"  ⚠️ {tag}: 内容过短")
            time.sleep(3.0)
        except Exception as e:
            log(f"  ❌ {tag}: {e}")
            time.sleep(5.0)
    
    # ── 3. 特殊时期 ──
    log(f"\n--- 阶段3: 特殊时期 ({len(SPECIAL_QUERIES)}条) ---")
    for query, tag in SPECIAL_QUERIES:
        try:
            raw = execute_query(query)
            article = format_response(raw, query)
            if article and len(article) > 20:
                db.execute(
                    "INSERT OR REPLACE INTO research_article(category,title,content,source) VALUES(?,?,?,?)",
                    (tag, query, article[:5000], "宏观API"))
                db.commit()
                total_ok += 1
                log(f"  ✅ {tag}: {len(article)}字")
            time.sleep(3.0)
        except Exception as e:
            log(f"  ❌ {tag}: {e}")
            time.sleep(5.0)
    
    # ── 统计 ──
    tags = db.execute("SELECT category, COUNT(*) FROM research_article WHERE category LIKE '%·20%' OR category LIKE '%·历史%' OR category LIKE '%宏观·%' GROUP BY category ORDER BY category").fetchall()
    db.commit()
    db.close()
    log(f"\n{'='*60}")
    log(f"✅ 完成: 共 {total_ok} 条历史研报")
    log(f"📊 标签分布:")
    for t in tags:
        log(f"  {t[0]}: {t[1]} 篇")
    log(f"{'='*60}")


if __name__ == "__main__":
    main()
