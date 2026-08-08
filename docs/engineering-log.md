# QuantLab 工程记录（Engineering Log）

> 记录日期：2026-08-08
> 记录范围：代码评估 → 缺陷修复 → 数据同步 → 工程化 1~5 的全部决策与事实

---

## 一、项目概述

QuantLab 是个人量化分析平台：双数据源（国投证券行情 / 国信证券财务）→ SQLite → 模式发现引擎（预测-反馈-收敛闭环）→ Streamlit UI。
初始形态为功能原型：数据管道可跑通，但存在 Schema 漂移、静默失败、无版本管理、无测试等问题。

---

## 二、评估发现（2026-08-08 首轮）

### 严重问题（P0）
| 问题 | 影响 |
|---|---|
| **Schema 漂移**：`main.py` 内联 DDL（6 表精简版）与 `src/db/schema.py`（24 表完整版）互不兼容 | 全新安装必崩（实测：`no such table: trend_data` / `portfolio_stock has 8 columns but 5 values were supplied`） |
| **依赖缺失**：requirements.txt 无 scikit-learn；`.venv` 为 72K 空壳（无 pip） | `pip install -r requirements.txt` 后量化分析 Tab 直接 ImportError |
| **四处禁用 SSL 证书验证**（gs_client/sync_daily/sync_extra/sync_macro_public/research） | HTTPS 请求可被中间人篡改 |

### 功能失效（P1）
- `sync_extra.py` 的 `urllib_request` NameError → 资金流向同步永远静默失败
- `service/sync.py` 调用不存在的 `query_a_income` 等方法；`FundFlowSyncService.daily_sync` 是空实现
- `total_changes` 累计计数 bug（9 处）：首次执行后恒 >0，插入统计严重虚高
- `sync_daily.py` K线裸 `VALUES`（9 值 vs 10 列）→ 完整版库上全部静默失败
- 预测-反馈闭环从未运行（`prediction_log` 0 条）
- 行业推断查 `stock_basic.industry_name`（26/26 全 NULL）→ 永远"综合"
- `sync_extra.sync_crowding` 把拥挤度误写 `data_coverage` 表

### 方法学（P2）
- 回测预测目标日与实际对比日**错位一天**
- `next_direction` 末行假标签（无次日数据被标成 `flat`，污染模式库）
- `pattern_library` 的 `INSERT OR REPLACE` 每次重置 `first_seen`

---

## 三、第一轮修复（同日）

统一 DDL / 依赖与 .gitignore / SSL 恢复（实测国信需 `OP_LEGACY_SERVER_CONNECT`，保持验证）/ sync_extra 重写（urllib、crowding 写 `sector_crowding`、宏观提取数值）/ rowcount 计数 / 命名列 INSERT / 预测闭环新模块 `prediction_loop.py`（防重+按日结算）/ 回测错位与假标签修复（000037 回测 0.34 → 0.54）/ 行业推断启发式 / 裸 except 清零。
运行环境确定：**使用系统 Python 3，删除空 `.venv`，不建 venv**。

---

## 四、数据同步（2026-08-08 周六）

- 行情 26/26、K线 26/26 至 **08-07**（首次 429 限流 8 只，间隔 2s 补拉）、分时 25/26（H02380 港股接口不支持，预期）
- 预测闭环首次生成 24 条预测（目标 08-10 周一）
- **国信 API 日限额耗尽**（code 197006）：财务增量/宏观/资金流向当日无法执行，次日 0 点重置
- **拥挤度 API 真实格式**：`data={行业代码:{code, calcTime, d5, d20}}` + 驼峰指标键（与 skill 文档的组装格式不同），修正解析后 13/30 行业入库

---

## 五、工程化 1~5（同日）

### 第 1 步 — 工程地基
- `git init` + 13 次语义化提交（`.gitignore` 覆盖 `.env`/`data/`/`.reasonix/`/日志/备份/锁）
- `src/datasource/ratelimit.py`：`api_call` 指数退避重试（429/503/超时）+ `CircuitBreaker` 熔断（国信 197006 当日熔断）；gs_client/sdicsc_client 重构接入，对外返回结构兼容
- `tests/`：9 文件 39 用例（schema/engine/pattern_discovery/prediction_loop/datasource/ratelimit/service/coverage/notify）

### 第 2 步 — 日志/锁/备份
- `service/logging_setup.py`：`data/logs/` 按天轮转（保留 14 天）
- `service/lock.py`：fcntl 单实例锁（占用时非零退出码供调度识别）
- `service/backup.py`：`VACUUM INTO` 每日快照（保留 14 份，路径单引号转义）
- `sync_daily.py` 编排：`main(日志→锁→同步→备份)` → `_run(实际同步)`

### 第 3 步 — 定时调度 + 告警
- `scheduler.py`：schedule 库常驻，工作日 15:30 子进程执行 `sync_daily --full`；"跳过"（锁占用）不误报告警
- `service/notify.py`：log + weixin 双通道（复用 `WEIXIN_BOT_TOKEN` → ilinkai 网关，best-effort，未公开 API 格式）

### 第 4 步 — 自选股配置化 + 覆盖率
- main.py 操作 Tab 增删自选股（调行情 API 验证、`guess_market` 自动推断、可转债代码段白名单细分）；`STOCKS` 降级为首次种子
- `service/coverage.py`：K线/分时/财务覆盖计算，`persist` 开关隔离 UI 只读展示与同步落库

### 第 5 步 — 回测增强 + 模式显著性
- backtest 增加：成本模型（默认双边 0.1%）、**完整日序列净值**（修复 step>1 漏计中间日收益的 Blocking）、最大回撤、夏普、分模式胜率
- `_is_significant`：二项检验（α=0.05，方向基准 0.5 / flat 基准 1/3），不显著模式投票权重减半

### review 复核（两轮）
1 Blocking（回测净值 step>1 漏计）+ 5 Should-fix（锁退出码 / UI 覆盖率污染 last_synced_at / flat 显著性基准 / guess_market 可转债细分 / sdicsc 熔断死代码注释）——全部修复并验证，结论 ship as-is。

---

## 六、当前数据状态（2026-08-08 收盘口径）

| 数据 | 状态 |
|---|---|
| 行情 | 26 只快照（fetched_at 08-08 15:03） |
| K线 | 26 只至 08-07（07-31~08-07 已补齐） |
| 分时 | 25 只至 08-07（H02380 无分时） |
| 财务 | 441 期有效 + 5 骨架行（301707，待国信限额重置后填值），最新完整期 2026Q1 |
| 模式库 | 277 条 |
| 预测 | 24 条待结算（目标 08-10 周一） |
| 拥挤度 | 13 个行业 |

---

## 七、已知限制与后续方向

### 已知限制
1. **国信日限额**：GS_API_KEY 每日限额（197006）耗尽后所有端点静默返回 0 条，次日 0 点重置——同步脚本已熔断不再空转，但财务增量需限额窗口内分日完成
2. **交易日历**：`scheduler.is_trading_day` 仅判断周一~周五，未覆盖 A 股法定节假日（`trade_calendar` 表 0 行，可用其扩展精确日历）
3. **节假日预测**：`_next_trade_date` 只跳周末；预测目标日落在节假日时由结算顺延逻辑兜底（已实现）
4. **微信通知格式**：ilinkai 网关 API 未公开文档，`notify._weixin` 为 best-effort（POST JSON `{token, title, content}`），失败仅记日志
5. **`sync_daily --quick` 财务骨架行**：只建行不填值，数值由 `sync_financial.py`（UPSERT）覆盖
6. **回测夏普未减无风险利率**（当前 rf=0，可配置）

### 后续方向（未实施，按优先级）
1. **交易日精确日历**：`trade_calendar` 填充 + `_next_trade_date` 接入
2. **回测交易成本可配置**：滑点/印花税/资金管理等
3. **组合层风控**：相关性热图（`correlation_matrix` 已实现未展示）、组合波动率
4. **数据源扩展**：数据源抽象为协议层，接入 Tushare 等备用源（缓解单一数据源限额/断供）
5. **报告导出**：周报/月报 PDF
6. **launchd 开机自启**：scheduler 常驻化（用户当前暂不需要）

---

## 八、运行手册（速查）

```bash
python3 -m pytest tests/ -q              # 测试（39 用例）
python3 src/sync_daily.py --full         # 手动全量同步（锁→同步→备份）
python3 src/scheduler.py                 # 常驻：工作日 15:30 自动同步 + 微信告警
streamlit run src/main.py                # UI
```

依赖（系统 Python 3，不建 venv）：`pip install --break-system-packages -r requirements.txt pytest`

---

## 九、Git 提交历史（13 次）

```
8779cee init: QuantLab 量化分析平台（修复后基线）
75d1c59 chore: 忽略 .reasonix 内部元数据
32249f9 feat: 第1步工程地基 — git 基线 + API 限流/重试/熔断封装 + 25 个 pytest 单元测试
727ffb8 feat: 第2步 日志统一(data/logs) + 单实例锁 + VACUUM INTO 自动备份，接入 sync_daily 编排
f3daeb0 feat: 第3步 交易日15:30定时调度(scheduler.py) + 微信/日志双通道告警(notify.py)
0c838f3 test: 修复通知测试（JSON 中文断言）
42706c4 feat: 第4步 自选股 UI 增删管理(数据库驱动) + 数据覆盖率计算与展示(data_coverage)
9423d3a feat: 第5步 回测增强(成本模型/回撤/夏普/分模式胜率) + 模式显著性二项检验筛选
0809fb4 docs: README 更新工程能力说明
0c0c0d7 fix: review 意见落实 — 回测净值按完整日序列累乘…（Blocking+5 Should-fix）
34f561d fix: guess_market 可转债按代码段细分 + 补 persist只读/市场推断测试
fc5369d test: 补 flat 模式显著性基准(1/3)用例
449a831 test: 修正 flat 显著性用例数据(16/30)
30e16a6 chore: requirements 显式声明 scipy（显著性检验依赖）
```
