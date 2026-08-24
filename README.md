# 衡流 (HengLiu / QuantFlow) — 本地量化分析工具

> **审度称衡，守正观流**  
> 基于国投证券(行情) + 国信证券(财务)双数据源的本地量化分析平台。  
> 每只股票独立的模式发现引擎，通过预测→反馈→迭代收敛实现自适应学习。  
> 出品：**鹿溪联合创新实验室**（LUXI Joint Innovation Lab）

## 数据全景

| 数据类型 | 覆盖范围 | 数据源 |
|:---------|:---------|:-------|
| 📊 实时行情 | 26只股票，15+字段 | 国投证券 |
| 📈 日K线 | 26只×120天 | 国投证券 |
| ⏱ 分时走势 | 25只×266分时点 | 国投证券 |
| 📋 财务报表 | 23只×20期(5年) | 国信证券 |
| 🧠 模式库 | 277条可重复模式 | 自发现 |

## 快速启动

> 运行环境：直接使用系统 Python 3（本机已验证 Python 3.14 + sklearn 1.9 / pandas 3.0），**不创建 venv**。

```bash
# 1. 安装依赖到系统 Python（含量化引擎所需 scikit-learn）
pip install -r requirements.txt

# 2. 配置 API Key（首次运行任一步骤都会自动建表，无需手动初始化）
cp config/.env.example config/.env   # 在网页获取 API Key

# 3. 数据同步（首次先全量，之后每日用 sync_daily.py）
python3 src/sync_now.py               # 全量同步 (行情+K线)
python3 src/sync_trend.py             # 分时同步
python3 src/sync_financial.py         # 财务同步
python3 src/sync_daily.py             # 一键全量（含研报/选股/预测闭环）

# 4. 启动 UI
streamlit run src/main.py
```

> 所有 sync 脚本和 UI 入口都会自动执行 `src/db/schema.py` 的 `init_db()`，
> 数据库表结构统一由 `src/db/schema.py` 管理。

## 功能模块

| 标签 | 功能 | 算法 |
|:-----|:-----|:-----|
| 📊 因子&信号 | 6大因子评分 + 组合概览 + 下一日预测 | PatternDiscovery v2.0 |
| 📈 技术图表 | K线 + MA + RSI + MACD + 布林带 | Plotly |
| 📋 量化分析 | GMM状态分类 + 马尔可夫链 + 动量矩阵 | sklearn |
| 💹 财务趋势 | 营收/净利润/ROE趋势 | 国信API |
| 🏷️ 操作 | 持仓切换 + 数据状态 | — |

## 架构

```
src/
├── main.py                    # Streamlit 布局（主题/研报/组合拆到 src/ui、service）
├── scheduler.py               # 交易日 15:30 定时调度 + 结果告警（常驻）
├── sync_daily.py              # 一键全量（锁内 pipeline + 备份；部分失败退出码 2）
├── sync_now.py / sync_trend.py / sync_financial.py / sync_extra.py
├── datasource/                # 国投 + 国信 + 限流熔断（国信熔到次日 0 点）
├── quant/                     # GMM / 模式发现 / 预测闭环（OOS vs 多数类）
├── db/connection.py           # WAL + FK + busy_timeout
├── db/migrations.py           # user_version 迁移（日历/指标字典）
├── service/pipeline.py        # 同步门面（CLI 与 UI 共用）
├── service/calendar.py        # 交易日历
├── service/codes.py           # 市场推断 / API 代码映射
└── ui/                        # theme / charts / research

tests/                         # pytest（connection/日历/同步门面/泄漏/OOS）
```

## 工程能力

| 能力 | 说明 |
|---|---|
| 单元测试 | `python3 -m pytest tests/ -q`（pytest 已写入 requirements.txt） |
| API 限流/熔断 | 国投 429 自动指数退避重试；国信日限额（197006）当日熔断不再发请求 |
| 单实例锁 | 同步脚本并发执行时自动跳过，防止写坏 SQLite |
| 自动备份 | 每次同步后 `VACUUM INTO` 快照到 `data/backups/`（保留 14 天） |
| 定时任务 | `python3 src/scheduler.py` 常驻：工作日 15:30 自动全量同步 |
| 告警 | 同步完成/异常推送微信（WEIXIN_BOT_TOKEN）并写 `data/logs/` |
| 自选股管理 | UI 操作 Tab 增删自选股（数据库驱动，不再硬编码） |
| 数据覆盖率 | UI 展示每只股票 K线/分时/财务覆盖，落库 `data_coverage` |
| 回测绩效 | 成本模型（默认双边 0.1%）、最大回撤、夏普、分模式胜率 |
| 模式显著性 | 二项检验（α=0.05，样本≥10），不显著模式投票权重减半 |

## 收敛预测闭环

每只股票独立的 PatternDiscoveryEngine 通过历史K线发现可重复模式。
`src/sync_daily.py` 每次同步后自动执行 `src/quant/prediction_loop.py`：

```
生成预测 → 存入 prediction_log → 次日K线到达 → 结算(对比实际) → 收敛提升
```

- **结算**：按预测目标日相对前一交易日收盘的涨跌回填 `actual_*`（节假日顺延到下一开市日）
- **新预测**：基于最新状态生成下一交易日预测入库；模式方向为先验规则，不再用次日标签冒充命中率
- **口径**：不要把三分类均匀 33% 当成能力。诚实零假设是多数类（A 股常为盘整）。UI「因子&信号」展示 `prediction_log` 命中率相对多数类基线。首轮实盘结算约 5/24（弱于随机），需积累后再评估

## 说明

- SSL：所有 HTTPS 请求保持证书验证；国信服务器仅支持 legacy renegotiation，
  已通过 `OP_LEGACY_SERVER_CONNECT` 显式兼容（而非关闭验证）。
- 敏感配置 `config/.env` 已被 `.gitignore` 排除，请勿提交真实 Key。

---

## 📜 版权与数据声明

**版权**：本仓库（衡流 · HengLiu / QuantFlow）由 **鹿溪联合创新实验室（LUXI Joint Innovation Lab）** 原创开发，
采用 [MIT](./LICENSE) 许可证开源。引用、修改、分发时请保留版权与许可证声明。

**数据来源**：
- 行情数据：国投证券开放接口（自选股行情 / K线 / 分时）
- 财务与宏观数据：国信证券开放接口（财务报表 / 宏观指标 / 资金流向）
- 数据仅用于**个人学习与量化研究**，接口访问受供应商配额与条款约束

**免责声明**：
- 本项目输出的任何预测、信号、回测指标**均不构成投资建议**；
  量化模型存在过拟合与失效风险，历史回测不代表未来表现
- **市场有风险，投资需谨慎**。因使用本项目产生的任何投资损失，作者不承担责任

**依赖致谢**（均为各自开源许可）：
Streamlit · Plotly · pandas · numpy · scikit-learn · scipy · httpx · python-dotenv · schedule

**API Key 使用规范**：
- `config/.env` 中的 Key 属个人凭证，请勿提交到公共仓库
- 国信接口有每日调用限额（超出后当日熔断，次日重置），请合理规划同步频率
