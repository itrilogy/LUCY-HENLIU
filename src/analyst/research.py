"""
AI 研报生成引擎 — 基于股票特征 + LLM 的宏观经济问答流水线

流程:
  股票特征 → Query生成器(规则/LLM) → 宏观API → 格式化(规则/LLM) → 标签存储
"""

import sys, os, json, time, sqlite3, re
from pathlib import Path
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.datasource.gs_client import _get


# ── 行业分类与查询模板 ─────────────────────────
SECTOR_QUERIES = {
    "银行": [
        "中国LPR利率 最新调整 对银行业影响",
        "中国存款准备金率 变化趋势",
        "中国社会融资规模 最新数据",
        "中国银行业净息差 变化趋势",
        "央行货币政策 最新动向",
    ],
    "证券": [
        "中国资本市场改革 最新政策",
        "A股市场日均成交额 变化趋势",
        "中国券商行业监管政策 最新",
        "资本市场开放政策 最新进展",
    ],
    "半导体": [
        "中国半导体产业政策 最新支持措施",
        "中美科技竞争 对半导体行业影响",
        "中国芯片国产化率 进展",
        "国家集成电路产业基金 投资动态",
    ],
    "电力": [
        "中国电力市场化改革 最新进展",
        "新能源发电占比 变化趋势",
        "中国碳排放权交易 市场动态",
        "电力行业十四五规划 执行情况",
    ],
    "医药": [
        "中国医药集采政策 最新动态",
        "医保目录调整 最新进展",
        "中国创新药审批 趋势分析",
        "医疗健康产业政策 2026年重点",
    ],
    "军工": [
        "中国国防预算 增长趋势",
        "军工行业十四五规划 执行情况",
        "军民融合政策 最新进展",
    ],
    "化工": [
        "中国化工行业环保政策 最新",
        "大宗商品价格走势 对化工影响",
        "化工行业产能周期 分析",
    ],
    "机械": [
        "中国制造业PMI 最新数据",
        "工业机器人产量 增长趋势",
        "智能制造政策 最新支持措施",
    ],
    "白酒": [
        "中国消费市场 复苏趋势",
        "白酒行业监管政策 最新",
        "居民可支配收入 增长趋势",
    ],
    "包装": [
        "中国造纸行业 景气度分析",
        "环保限塑政策 对包装行业影响",
        "快递包装绿色转型 政策要求",
    ],
    "ETF基金": [
        "中国ETF市场 规模增长趋势",
        "指数基金发展 最新数据",
        "中国资本市场 投资者结构变化",
    ],
}

# 每日通用查询（适用于所有股票）
DAILY_QUERIES = [
    ("中国GDP同比增速 最新数据", "宏观·GDP"),
    ("中国CPI同比 最新月度数据", "宏观·CPI"),
    ("中国PPI同比 最新月度数据", "宏观·PPI"),
    ("中国制造业PMI 最新数据", "宏观·PMI"),
    ("中国M2货币供应量 同比增速 最新", "宏观·货币"),
    ("中国社会融资规模 增量 最新数据", "宏观·货币"),
    ("中国LPR利率 最新报价", "宏观·利率"),
    ("人民币汇率 最新走势", "宏观·汇率"),
    ("中国外汇储备 最新数据", "宏观·外汇"),
    ("中国城镇调查失业率 最新数据", "宏观·就业"),
    ("全国规模以上工业增加值 同比增速", "宏观·产业"),
    ("中国社会消费品零售总额 同比增速", "宏观·消费"),
    ("中国固定资产投资 累计同比增速", "宏观·投资"),
    ("中国对外贸易进出口总额 最新数据", "宏观·外贸"),
    ("中国房地产开发投资 累计同比增速", "宏观·地产"),
    ("美国CPI同比 最新数据", "全球·美国"),
    ("美国联邦基金利率 最新", "全球·美国"),
    ("欧元区CPI同比 最新", "全球·欧洲"),
    ("日本CPI同比 最新", "全球·日本"),
    ("国际原油价格 最新走势", "全球·商品"),
    ("COMEX黄金价格 最新走势", "全球·商品"),
    ("LME铜价 最新走势", "全球·商品"),
    ("中国央行公开市场操作 最新", "宏观·流动性"),
    ("北向资金 沪股通深股通 流向 最新", "市场·资金"),
]

# 历史快照查询（带年份标签，用于对比趋势）
HISTORICAL_QUERIES = []
for year in range(datetime.now().year - 2, datetime.now().year + 1):
    HISTORICAL_QUERIES.extend([
        (f"中国GDP同比增速 {year}年", f"宏观·GDP·{year}"),
        (f"中国CPI同比 {year}年变化趋势", f"宏观·CPI·{year}"),
        (f"中国PPI同比 {year}年变化趋势", f"宏观·PPI·{year}"),
        (f"中国M2货币供应量 {year}年趋势", f"宏观·货币·{year}"),
        (f"中国制造业PMI {year}年走势", f"宏观·PMI·{year}"),
    ])

# ── LLM 查询生成器 ────────────────────────────

def _call_llm(prompt: str, system: str = "") -> Optional[str]:
    """调用 Deepseek 或备用模型"""
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    
    import urllib.request, ssl
    ctx = ssl.create_default_context()
    try:
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    except AttributeError:
        pass
    
    url = "https://api.deepseek.com/v1/chat/completions"
    if not api_key.startswith("sk-"):
        # 尝试其他端点
        url = "https://api.deepseek.com/chat/completions"
    
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system or "你是一个金融分析师，擅长宏观经济分析。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 2000
    }).encode()
    
    try:
        req = urllib.request.Request(url, data=body,
            headers={"Content-Type":"application/json","Authorization":f"Bearer {api_key}"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return None


def generate_queries(stock_name: str, industry: str, pe: float, 
                     market_value: str, daily: bool = False) -> list:
    """
    根据股票特征生成宏观经济查询
    
    Args:
        stock_name: 股票名称
        industry: 所属行业
        pe: 市盈率
        market_value: 市值
        daily: 是否每日更新模式
    
    Returns: [(query_text, tag), ...]
    """
    queries = []
    
    # 1. 每日通用宏观指标
    if daily:
        for q, tag in DAILY_QUERIES[:10]:  # 每日只取前10条最核心的
            queries.append((q, tag))
        return queries
    
    # 2. 行业专属查询
    for sec_name, sec_queries in SECTOR_QUERIES.items():
        if sec_name in industry:
            for q in sec_queries:
                queries.append((q, f"行业·{sec_name}"))
            break
    
    # 3. 基于估值的查询
    if pe and pe > 0:
        if pe < 15:
            queries.append(("A股市场整体估值水平 分析 低估值板块", "策略·估值"))
        elif pe > 50:
            queries.append(("高估值成长板块 市场风险 分析", "策略·估值"))
    
    # 4. 基于市值的查询
    if market_value:
        try:
            mv = float(str(market_value).replace("亿","").replace("万",""))
            if mv > 1000:
                queries.append(("大盘蓝筹股 市场表现 分析", "策略·风格"))
            elif mv < 100:
                queries.append(("中小盘股 市场表现 流动性 分析", "策略·风格"))
        except (ValueError, TypeError):  # 市值字符串解析失败则跳过，非致命
            pass
    
    # 5. LLM 增强（如有API；失败不影响规则查询）
    try:
        llm_result = _call_llm(
            f"""股票{stock_name}(行业:{industry},PE:{pe})的持有者需要关注哪些宏观经济指标？
            请返回3-5条中文查询语句，每行一条，不要序号。""")
        if llm_result:
            for line in llm_result.strip().split("\n"):
                q = line.strip().strip("0123456789.、 \t")
                if q and len(q) > 5:
                    queries.append((q, "LLM·推荐"))
        time.sleep(0.5)
    except Exception:  # LLM 输出格式异常时忽略该增强项
        pass
    
    return queries


# ── 格式转换器 ────────────────────────────────

def _guess_industry(stock_name: str) -> str:
    """从股票名称启发式推断行业（stock_basic.industry_name 未填充时的兜底）"""
    for sec_name in SECTOR_QUERIES:
        if sec_name in stock_name:
            return sec_name
    return "综合"


def assign_tags(llm_content: str, query: str, default_tag: str, db: sqlite3.Connection) -> str:
    """
    使用LLM从标签库中选择匹配标签，可新增标签
    返回最终选中的标签
    """
    # 获取现有标签
    existing = [r[0] for r in db.execute("SELECT tag FROM tag_library WHERE is_active=1").fetchall()]
    tag_list = "\n".join(f"- {t}" for t in existing)
    
    # 先尝试LLM
    llm_result = _call_llm(
        f"""根据以下研报内容，从标签库中选择1-3个最相关的标签。
如果无完全匹配，可创建1个新标签（格式：'分类·子类'）。

标签库：
{tag_list}

研报标题：{query}
研报内容（摘要）：{llm_content[:500]}

返回格式：仅返回标签列表，每行一个，不要序号和额外文字。""",
        system="你是一个标签分类专家。精确选择，不要泛泛而配。")
    
    if llm_result:
        selected = []
        for line in llm_result.strip().split("\n"):
            t = line.strip().strip("* -")
            if t and not t.startswith("标签"):
                if t in existing:
                    selected.append(t)
                elif "·" in t:
                    # 新标签，加入库
                    cat = t.split("·")[0]
                    try:
                        db.execute("INSERT OR IGNORE INTO tag_library(tag,category,description) VALUES(?,?,?)",
                                   (t, cat[:20], f"LLM自动创建 {datetime.now().strftime('%Y-%m-%d')}"))
                        db.commit()
                        selected.append(t)
                    except Exception:  # 标签写入失败仅丢弃该新标签，不影响主流程
                        pass
        if selected:
            return "|".join(selected[:3])
    
    return default_tag


def format_response(raw_response: str, query: str, db: Optional[sqlite3.Connection] = None) -> str:
    """格式化宏观API响应为可读文章"""
    if not raw_response or len(raw_response) < 20:
        return "数据获取失败"
    
    # 提取内容
    content = ""
    if isinstance(raw_response, dict):
        data = raw_response
    else:
        try: data = json.loads(raw_response)
        except: data = {}
    if not isinstance(data, dict): data = {}
    for item in (data.get("data") or []):
        if isinstance(item, dict) and item.get("type") == "STREAM_MESSAGE":
            content += item.get("content", "")
    
    if not content or len(content) < 20:
        return "暂无有效数据"
    
    # 清理Markdown格式
    content = re.sub(r'```visual\n.*?\n```', '', content, flags=re.DOTALL)
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = content.strip()
    
    # 短内容不需要LLM格式化（避免LLM幻觉生成"未配置"类内容）
    if len(content) < 100:
        return content
    
    # 尝试LLM增强格式化（仅当内容足够丰富时）
    if len(content) > 200:
        llm_formatted = _call_llm(
            f"""将以下宏观经济查询结果重新组织为清晰的结构化研报格式，包含：
    1. 核心结论（1-2句）
    2. 关键数据（列表形式）
    3. 趋势分析
    
    原始内容：
    {content[:1500]}""",
            system="你是一个宏观经济分析师，请用中文输出结构化的Markdown格式。\n注意：如果原始内容已经是完整的回答，直接优化格式即可，不要编造数据。")
        
        if llm_formatted:
            return llm_formatted.strip()
    
    return content


# ── 执行引擎 ─────────────────────────────────

def execute_query(query: str) -> str:
    """执行单条宏观查询"""
    try:
        r = _get("https://dgzt.guosen.com.cn/skills/agent/adapter/query",
                 {"text": query, "softName": "agent_skills"})
        return json.dumps(r, ensure_ascii=False)
    except Exception as e:
        return f"查询失败: {e}"


def run_pipeline(db: sqlite3.Connection, stock_codes: list = None, daily_mode: bool = False) -> dict:
    """
    运行研报生成流水线
    
    Args:
        db: 数据库连接
        stock_codes: 股票代码列表，None=全部
        daily_mode: 每日模式(仅通用指标)
    
    Returns: {category: count}
    """
    if stock_codes is None:
        stock_codes = [r[0] for r in db.execute("SELECT stock_code FROM portfolio_stock").fetchall()]
    
    results = {}
    generated = 0
    
    # 每日通用查询
    queries = [(q, tag) for q, tag in DAILY_QUERIES]
    
    # 非每日模式：追加历史快照（带年份标签）
    if not daily_mode:
        for q, tag in HISTORICAL_QUERIES:
            if (q, tag) not in queries:
                queries.append((q, tag))
    if not daily_mode:
        for code in stock_codes[:5]:  # 限5只以防过多
            stock = db.execute("SELECT name FROM stock_basic WHERE stock_code=?", (code,)).fetchone()
            if not stock: continue
            # 行业优先取 stock_basic.industry_name，未填充时按股票名称启发式推断
            fin = db.execute("SELECT industry_name FROM stock_basic WHERE stock_code=?", (code,)).fetchone()
            industry = fin[0] if fin and fin[0] else _guess_industry(stock[0])
            pe = db.execute("SELECT pe_ttm FROM real_time_quote WHERE stock_code=? ORDER BY fetched_at DESC LIMIT 1", (code,)).fetchone()
            pe_val = pe[0] if pe and pe[0] else 0
            mv = db.execute("SELECT market_value FROM real_time_quote WHERE stock_code=? ORDER BY fetched_at DESC LIMIT 1", (code,)).fetchone()
            mv_val = mv[0] if mv else "0"
            stock_queries = generate_queries(stock[0], industry, pe_val, mv_val, daily=False)
            queries.extend(stock_queries)
    
    # 去重
    seen = set()
    unique_queries = []
    for q, tag in queries:
        if q not in seen:
            seen.add(q); unique_queries.append((q, tag))
    
    print(f"📋 共 {len(unique_queries)} 条查询待执行" if daily_mode else f"📋 共 {len(unique_queries)} 条(含行业定制)待执行")
    
    for query, tag in unique_queries:
        try:
            # 执行
            raw = execute_query(query)
            # 格式化
            article = format_response(raw, query)
            if article and len(article) > 30:
                # 存储
                db.execute(
                    "INSERT OR REPLACE INTO research_article(category,title,content,source) VALUES(?,?,?,?)",
                    (tag, query.strip()[:200], article[:8000], "AI研报引擎"))
                db.commit()
                results[tag] = results.get(tag, 0) + 1
                generated += 1
                print(f"  ✅ {tag}: {query[:40]}...", flush=True)
            else:
                print(f"  ⚠️ {tag}: 内容过短", flush=True)
            time.sleep(1.2)  # 频率限制
        except Exception as e:
            print(f"  ❌ {tag}: {e}", flush=True)
    
    return results


def tag_summary(db: sqlite3.Connection) -> list:
    """获取标签统计"""
    rows = db.execute(
        "SELECT category, COUNT(*) as cnt, MAX(fetched_at) as last FROM research_article GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    return [{"category": r[0], "cnt": r[1], "last": r[2]} for r in rows]


def run_daily_research(db_path: str = "") -> dict:
    """可直接调用的每日研报生成接口（替代 subprocess）"""
    if not db_path:
        db_path = str(Path(__file__).parent.parent.parent / "data" / "stock.db")
    db = sqlite3.connect(db_path)
    try:
        results = run_pipeline(db, daily_mode=True)
        return results
    finally:
        db.commit()
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", action="store_true", help="每日模式(仅通用指标)")
    parser.add_argument("--db", type=str, default="", help="数据库路径")
    args = parser.parse_args()
    
    db_path = args.db or str(Path(__file__).parent.parent.parent / "data" / "stock.db")
    db = sqlite3.connect(db_path)
    print("🚀 AI研报引擎启动\n")
    
    if args.daily:
        results = run_pipeline(db, daily_mode=True)
    else:
        codes = [r[0] for r in db.execute("SELECT stock_code FROM portfolio_stock").fetchall()]
        results = run_pipeline(db, codes, daily_mode=False)
    
    print(f"\n✅ 生成 {sum(results.values())} 篇研报")
    for tag, cnt in results.items():
        print(f"  {tag}: {cnt} 篇")
    print("\n📊 标签分布:")
    for row in tag_summary(db):
        print(f"  {row['category']}: {row['cnt']} 篇 (最新{row['last'][:10]})")
    
    db.close()
