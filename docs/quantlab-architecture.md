# QuantLab — 量化交易分析工具 技术文档

> 最后更新: 2026-08-13 | 版本: v2.2（四周工程：同步门面 / 日历 / 预测口径）

---

## 一、项目结构

```
stock-analyzer/
├── README.md                          # 项目说明
├── requirements.txt                   # Python 依赖
├── config/
│   └── .env                           # API Key 配置 (GS_API_KEY + GT_ZNXG_KEY)
├── data/
│   └── stock.db                       # SQLite 数据库 (21+张表)
├── docs/
│   ├── data-architecture.md           # 数据架构设计
│   └── quantlab-architecture.md       # 量化架构设计
├── src/
│   ├── main.py                        # Streamlit UI 主入口 (520行)
│   ├── sync_now.py                    # 全量数据同步（行情+K线）
│   ├── sync_daily.py                  # 一键全量同步（含智能选股+研报）
│   ├── sync_trend.py                  # 分时数据同步
│   ├── sync_financial.py              # 财务数据同步
│   ├── sync_extra.py                  # 辅助数据同步（拥挤度/宏观/资金流向）
│   ├── sync_research_history.py       # 历史研报回填
│   ├── sync_macro_public.py           # 公开宏观数据嵌入
│   ├── datasource/
│   │   ├── sdicsc_client.py           # 国投证券行情 API
│   │   └── gs_client.py               # 国信证券财务 API
│   ├── quant/
│   │   ├── engine.py                  # 量化分析引擎 (GMM/马尔可夫/动量)
│   │   └── pattern_discovery.py       # 模式发现引擎 (v2.0 自适应阈值)
│   ├── analyst/
│   │   └── research.py                # AI研报引擎 (LLM驱动+规则模板)
│   ├── db/
│   │   └── schema.py                  # 数据库 DDL
│   └── service/
│       └── sync.py                    # 同步调度服务
```

## 二、数据库完整数据状态

| 表名 | 记录数 | 说明 | 数据源 |
|:-----|:------:|:-----|:------|
| `real_time_quote` | 130 行 | 实时行情快照 | 国投证券 |
| `kline_day` | 2,908 行 | 26只×~120天日K线 | 国投证券 |
| `trend_data` | 7,448 行 | 25只×266分时点 | 国投证券 |
| `financial_statement` | 441 行 | 三表5年(含现金流) | 国信证券 |
| `research_article` | **103 篇** | 宏观研报+历史数据 | 国信API+公开数据 |
| `pattern_library` | **277 条** | 模式发现结果 | 本地计算 |
| `tag_library` | **45 个** | 研报标签体系 | 预置+LLM扩充 |
| `macro_indicator` | 36 行 | 结构化宏观指标 | 国信API |
| `portfolio_stock` | 26 行 | 含6只持仓标记 | 本地 |

### 研报覆盖

| 类别 | 条数 | 覆盖范围 |
|:-----|:----:|:---------|
| 宏观·GDP | 26 篇 | 2010~2025 (含最新) |
| 宏观·CPI | 18 篇 | 2010~2024 |
| 宏观·PPI | 19 篇 | 2010~2024 |
| 宏观·PMI | 18 篇 | 2012~2024 |
| 宏观·货币(M2) | 21 篇 | 2010~2024 |
| 全球·美国/欧洲/日本 | 8 篇 | 最新数据 |
| 全球·商品 | 6 篇 | 最新数据 |
| 市场·资金 | 2 篇 | 最新数据 |

## 三、数据源架构

```
┌─ 国投证券 ───────────────────┐
│  POST /api/quote/batch      │ → real_time_quote (26只)
│  GET /api/kline/:code       │ → kline_day (120天)
│  GET /api/trend/:code       │ → trend_data (266点/只)
│  GET /api/v1/calc/query     │ → 行业拥挤度
├─ 国信证券 ───────────────────┤
│  incomeStatement/1.0        │ → financial_statement (5年)
│  balanceSheet/1.0           │ → financial_statement
│  cashFlowStatement/1.0      │ → financial_statement (修复后)
│  agent/adapter/query        │ → research_article (每日宏观)
├─ 公开数据 ───────────────────┤
│  国家统计局年度公报           │ → research_article (2010年起)
├─ 本地计算 ───────────────────┤
│  PatternDiscoveryEngine     │ → pattern_library (277条)
│  GMM RegimeClassifier       │ → 市场状态分类
│  MarkovTransition           │ → 转移矩阵+稳态分布
│  MomentumAnalyzer           │ → 动量信号
└──────────────────────────────┘
```

## 四、量化分析引擎

### PatternDiscoveryEngine (v2.0)

| 模式类型 | 发现数 | 平均命中率 |
|:---------|:------:|:---------:|
| K线形态(锤子/吞没/十字星) | 72条 | **65.8%** |
| 动量延续/反转 | 72条 | 统计中 |
| MACD金叉/死叉 | 48条 | 32.2% |
| 布林带超买/超卖 | 45条 | 41.8% |
| 成交量异常 | 40条 | 35.6% |

**回测准确率**: 仅作滑动窗口参考，不是实盘。实盘口径见 `prediction_log` 相对多数类基线（首轮 5/24）。K 线形态命中率在修复标签泄漏后需重算，旧表 65.8% 不可用。

### RegimeClassifier (GMM)

- 4种市场状态: 牛市/熊市/震荡/低迷
- 特征: 日收益率 + 波动率 + 量比

### MarkovTransition

- 3态离散: 下跌<-1% / 盘整±1% / 上涨>1%
- 输出: 3×3转移矩阵 + 持续性指标

## 五、AI研报引擎

```
股票特征 → generate_queries() → 国信API → format_response() → research_article
                                           ↕
                                    LLM格式化 (Deepseek)
                                           ↕
                                    assign_tags() → 标签库
```

| 组件 | 功能 |
|:-----|:------|
| `DAILY_QUERIES` | 24条核心宏观每日更新 |
| `HISTORICAL_QUERIES` | 15条年曆史快照(积累) |
| `SECTOR_QUERIES` | 11个行业×5条定制 |
| `_call_llm()` | Deepseek LLM格式化+标签 |
| `assign_tags()` | 40标签库选择/新增 |

## 六、启动指南

```bash
# 首次部署
pip install -r requirements.txt
cp config/.env.example config/.env
python3 src/sync_now.py              # 行情+K线
python3 src/sync_trend.py            # 分时
python3 src/sync_financial.py        # 财务
python3 src/sync_macro_public.py     # 宏观历史

# 每日运行
streamlit run src/main.py            # 启动UI
# 界面点击 🔄 同步行情 → 📥 拉取研报

# 命令行全量
python3 src/sync_daily.py --full
```

## 七、更新日志

| 日期 | 版本 | 变更 |
|:-----|:----|:------|
| 2026-07-31 | v2.1 | 103篇研报+历史数据回填+AI研报引擎+标签体系 |
| 2026-07-30 | v2.0 | 模式发现引擎+现金流量表+量化分析引擎 |
| 2026-07-30 | v1.0 | 初始版本：双数据源+K线+分时+财务 |
