"""
自选股分析工具 - 数据库建表 DDL
SQLite 3, Python sqlite3 标准库
"""

SCHEMA_SQL = """
-- =============================================
-- 一、用户数据层
-- =============================================

-- 1. 自选股分组
CREATE TABLE IF NOT EXISTS portfolio (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL DEFAULT '默认分组',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 2. 自选股明细
CREATE TABLE IF NOT EXISTS portfolio_stock (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES portfolio(id) ON DELETE CASCADE,
    stock_code   TEXT    NOT NULL,
    market       TEXT    NOT NULL,          -- 'SH' / 'SZ' / 'BJ' / 'HK'
    note         TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    added_at     TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    is_holding   INTEGER NOT NULL DEFAULT 0, -- 1=持仓 0=自选
    UNIQUE(portfolio_id, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_ps_code ON portfolio_stock(stock_code);

-- 3. 股票基本信息
CREATE TABLE IF NOT EXISTS stock_basic (
    stock_code      TEXT PRIMARY KEY,
    name            TEXT    NOT NULL,
    market          TEXT    NOT NULL,
    industry_code   TEXT,
    industry_name   TEXT,
    listing_date    TEXT,
    total_shares    REAL,
    float_shares    REAL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    fetched_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(stock_code)
);
CREATE INDEX IF NOT EXISTS idx_sb_industry ON stock_basic(industry_code);

-- =============================================
-- 二、行情数据层（国投证券 sdicsc 源）
-- =============================================

-- 4. 实时行情快照
CREATE TABLE IF NOT EXISTS real_time_quote (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code          TEXT    NOT NULL REFERENCES stock_basic(stock_code),
    price               REAL    NOT NULL,
    change_amt          REAL    NOT NULL,
    change_pct          TEXT    NOT NULL,
    prev_close          REAL    NOT NULL,
    open                REAL,
    high                REAL,
    low                 REAL,
    avg_price           REAL,
    volume              TEXT,
    amount              TEXT,
    turnover            TEXT,
    amplitude           TEXT,
    volume_ratio        REAL,
    outside             TEXT,
    inside              TEXT,
    pe                  REAL,
    pe_dynamic          REAL,
    pe_ttm              REAL,
    market_value        TEXT,
    circ_market_val     TEXT,
    change_5d           TEXT,
    change_20d          TEXT,
    change_60d          TEXT,
    change_120d         TEXT,
    change_250d         TEXT,
    change_ytd          TEXT,
    change_month        TEXT,
    change_week         TEXT,
    iopv                TEXT,
    discount_rate       TEXT,
    fund_scale          TEXT,
    susp_flag           TEXT,
    trade_date          TEXT    NOT NULL,
    trade_time          TEXT    NOT NULL,
    fetched_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_qt_code_time ON real_time_quote(stock_code, fetched_at DESC);

-- 5. 日K线
CREATE TABLE IF NOT EXISTS kline_day (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code  TEXT    NOT NULL REFERENCES stock_basic(stock_code),
    trade_date  TEXT    NOT NULL,
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      INTEGER NOT NULL,
    amount      REAL,
    -- 复权因子（用于前复权计算）
    adjust_factor REAL DEFAULT 1.0,
    UNIQUE(stock_code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_kd_code_date ON kline_day(stock_code, trade_date DESC);

-- 6. 分钟K线
CREATE TABLE IF NOT EXISTS kline_minute (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code  TEXT    NOT NULL REFERENCES stock_basic(stock_code),
    freq        TEXT    NOT NULL,       -- '1min' / '5min' / '15min' / '30min' / '60min'
    time_key    TEXT    NOT NULL,       -- '2026-07-30 09:35'
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      INTEGER NOT NULL,
    amount      REAL,
    UNIQUE(stock_code, freq, time_key)
);
CREATE INDEX IF NOT EXISTS idx_km_lookup ON kline_minute(stock_code, freq, time_key DESC);

-- 7. 分时数据
CREATE TABLE IF NOT EXISTS trend_data (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code  TEXT    NOT NULL REFERENCES stock_basic(stock_code),
    trade_date  TEXT    NOT NULL,
    time_seq    INTEGER NOT NULL,       -- 1-241
    price       REAL    NOT NULL,
    avg_price   REAL,
    volume      INTEGER NOT NULL,
    change_amt  REAL,
    change_pct  TEXT,
    UNIQUE(stock_code, trade_date, time_seq)
);
CREATE INDEX IF NOT EXISTS idx_tr_lookup ON trend_data(stock_code, trade_date, time_seq);

-- 8. 行业拥挤度
CREATE TABLE IF NOT EXISTS sector_crowding (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_code     TEXT    NOT NULL,
    sector_name     TEXT    NOT NULL,
    calc_date       TEXT    NOT NULL,
    d5_amount_now       REAL,
    d5_amount_quantile  REAL,
    d5_market_val_now       REAL,
    d5_market_val_quantile  REAL,
    d5_turnover_now         REAL,
    d5_turnover_quantile    REAL,
    d20_amount_now      REAL,
    d20_amount_quantile REAL,
    d20_market_val_now      REAL,
    d20_market_val_quantile REAL,
    d20_turnover_now        REAL,
    d20_turnover_quantile   REAL,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(sector_code, calc_date)
);

-- =============================================
-- 三、财务数据层（国信证券 gs 源）
-- =============================================

-- 9. 财务报表（利润表 + 资产负债表 + 现金流量表 合并）
CREATE TABLE IF NOT EXISTS financial_statement (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code      TEXT    NOT NULL REFERENCES stock_basic(stock_code),
    market          TEXT    NOT NULL,
    report_type     TEXT    NOT NULL,       -- 'Q1' / 'Q2' / 'Q3' / 'Q4'
    report_year     TEXT    NOT NULL,       -- '2024'
    report_date     TEXT,
    -- 利润表
    revenue         REAL,
    cost            REAL,
    gross_profit    REAL,
    net_profit      REAL,
    non_gaap_net    REAL,
    eps             REAL,
    gross_margin    REAL,
    net_margin      REAL,
    -- 资产负债表
    total_assets    REAL,
    current_assets  REAL,
    total_liab      REAL,
    current_liab    REAL,
    equity          REAL,
    -- 现金流量表
    oper_cf         REAL,
    invest_cf       REAL,
    finance_cf      REAL,
    free_cf         REAL,
    -- 衍生指标
    roe             REAL,
    roa             REAL,
    debt_ratio      REAL,
    revenue_growth  REAL,
    profit_growth   REAL,
    -- 研发与分红
    rd_expense      REAL,
    rd_ratio        REAL,
    dividend        REAL,
    dividend_rate   REAL,
    -- 元信息
    currency    TEXT NOT NULL DEFAULT 'CNY',
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(stock_code, report_type, report_year)
);
CREATE INDEX IF NOT EXISTS idx_fs_lookup ON financial_statement(stock_code, report_year DESC, report_type);

-- 10. 资金流向
CREATE TABLE IF NOT EXISTS fund_flow (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code      TEXT    NOT NULL REFERENCES stock_basic(stock_code),
    trade_date      TEXT    NOT NULL,
    main_force_net  REAL,
    super_large_buy REAL,
    super_large_sell REAL,
    large_buy       REAL,
    large_sell      REAL,
    medium_buy      REAL,
    medium_sell     REAL,
    small_buy       REAL,
    small_sell      REAL,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(stock_code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_ff_date ON fund_flow(stock_code, trade_date DESC);

-- =============================================
-- 四、宏观数据层（国信证券 gs 源）
-- =============================================

-- 11. 宏观指标字典
CREATE TABLE IF NOT EXISTS indicator_def (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    region      TEXT NOT NULL,
    category    TEXT NOT NULL,
    freq        TEXT NOT NULL,
    unit        TEXT,
    description TEXT,
    source      TEXT NOT NULL DEFAULT '国信证券'
);

-- 12. 宏观指标值
CREATE TABLE IF NOT EXISTS macro_indicator (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator_code TEXT NOT NULL REFERENCES indicator_def(code),
    period      TEXT NOT NULL,          -- '2024Q4' / '2025-06' / '2025'
    value       REAL,
    yoy_change  REAL,
    mom_change  REAL,
    unit        TEXT,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(indicator_code, period)
);
CREATE INDEX IF NOT EXISTS idx_mi_code ON macro_indicator(indicator_code, period DESC);

-- =============================================
-- 五、辅助层
-- =============================================

-- 13. 行业板块字典
CREATE TABLE IF NOT EXISTS sector (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,          -- 'industry' / 'concept' / 'region'
    level       INTEGER DEFAULT 1
);

-- 14. 股票行业归属
CREATE TABLE IF NOT EXISTS stock_sector_map (
    stock_code  TEXT NOT NULL REFERENCES stock_basic(stock_code),
    sector_code TEXT NOT NULL REFERENCES sector(code),
    PRIMARY KEY (stock_code, sector_code)
);

-- 15. 交易日历
CREATE TABLE IF NOT EXISTS trade_calendar (
    trade_date  TEXT PRIMARY KEY,
    market      TEXT NOT NULL DEFAULT 'SH',
    is_open     INTEGER NOT NULL DEFAULT 1,
    day_type    TEXT
);
CREATE INDEX IF NOT EXISTS idx_tc_date ON trade_calendar(trade_date);

-- =============================================
-- 六、数据补全与同步追踪
-- =============================================

-- 16. 数据同步日志（追踪每次补全操作）
CREATE TABLE IF NOT EXISTS sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    data_type       TEXT    NOT NULL,   -- 'kline_day' / 'kline_minute' / 'fund_flow' / 
                                        -- 'financial' / 'macro' / 'quote' / 'trend'
    source          TEXT    NOT NULL,   -- 'sdicsc' / 'gs'
    stock_code      TEXT,              -- NULL for macro/sector-wide syncs
    sync_mode       TEXT    NOT NULL,  -- 'full' / 'incremental' / 'gap_fill'
    -- 时间范围
    period_start    TEXT,
    period_end      TEXT,
    -- 执行结果
    rows_fetched    INTEGER DEFAULT 0,
    rows_inserted   INTEGER DEFAULT 0,
    rows_updated    INTEGER DEFAULT 0,
    errors          TEXT,              -- JSON 错误详情
    status          TEXT    NOT NULL DEFAULT 'success',  -- 'success' / 'partial' / 'failed'
    duration_ms     INTEGER,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_sl_type_time ON sync_log(data_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sl_code     ON sync_log(stock_code, data_type);

-- 17. 数据覆盖率追踪（每只股票每种数据的已覆盖区间）
CREATE TABLE IF NOT EXISTS data_coverage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code      TEXT    NOT NULL REFERENCES stock_basic(stock_code),
    data_type       TEXT    NOT NULL,   -- 'kline_day' / 'kline_minute' / 'fund_flow' / 'financial'
    -- 已覆盖区间
    coverage_start  TEXT,              -- 最早有数据的日期
    coverage_end    TEXT,              -- 最新有数据的日期
    total_days      INTEGER,           -- 应有交易日数
    filled_days     INTEGER,           -- 已有数据天数
    gap_days        INTEGER DEFAULT 0, -- 缺失天数
    last_synced_at  TEXT,
    UNIQUE(stock_code, data_type)
);
CREATE INDEX IF NOT EXISTS idx_dc_coverage ON data_coverage(data_type, stock_code);

-- 18. 复权因子表（用于K线前复权计算）
CREATE TABLE IF NOT EXISTS adjust_factor (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code  TEXT    NOT NULL REFERENCES stock_basic(stock_code),
    trade_date  TEXT    NOT NULL,
    factor      REAL    NOT NULL,       -- 复权因子
    UNIQUE(stock_code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_af_code_date ON adjust_factor(stock_code, trade_date DESC);

-- 19. 数据源健康检查
CREATE TABLE IF NOT EXISTS data_source_health (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT    NOT NULL,       -- 'sdicsc_quote' / 'sdicsc_kline' / 'gs_finance'
    endpoint    TEXT    NOT NULL,
    status      TEXT    NOT NULL,       -- 'up' / 'down' / 'degraded'
    latency_ms  INTEGER,
    checked_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_dsh_source ON data_source_health(source_name, checked_at DESC);

-- =============================================
-- 七、模式发现与研报层
-- =============================================

-- 20. 模式库（PatternDiscoveryEngine 持久化）
CREATE TABLE IF NOT EXISTS pattern_library (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code   TEXT    NOT NULL,
    pattern_type TEXT    NOT NULL,
    pattern_sig  TEXT    NOT NULL,
    direction    TEXT    NOT NULL,
    hit_rate     REAL    DEFAULT 0,
    sample_count INTEGER DEFAULT 0,
    params       TEXT,
    first_seen   TEXT,
    last_seen    TEXT,
    is_active    INTEGER DEFAULT 1,
    UNIQUE(stock_code, pattern_type, pattern_sig)
);
CREATE INDEX IF NOT EXISTS idx_pl_stock ON pattern_library(stock_code, is_active);

-- 21. 预测日志（预测→反馈闭环）
CREATE TABLE IF NOT EXISTS prediction_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code      TEXT    NOT NULL,
    trade_date      TEXT    NOT NULL,
    direction       TEXT    NOT NULL,
    confidence      REAL,
    predicted_price REAL,
    actual_direction TEXT,
    actual_price    REAL,
    correct         INTEGER DEFAULT 0,
    error_pct       REAL,
    engine_version  TEXT,
    pattern_type    TEXT,
    created_at      TEXT    DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_plog_lookup ON prediction_log(stock_code, trade_date);

-- 22. 预测模型记录
CREATE TABLE IF NOT EXISTS prediction_models (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code     TEXT    NOT NULL,
    engine_version TEXT    NOT NULL,
    pattern_type   TEXT    NOT NULL,
    params         TEXT,
    accuracy       REAL    DEFAULT 0,
    precision      REAL    DEFAULT 0,
    recall         REAL    DEFAULT 0,
    f1_score       REAL    DEFAULT 0,
    sample_count   INTEGER DEFAULT 0,
    is_active      INTEGER DEFAULT 1,
    created_at     TEXT    DEFAULT CURRENT_TIMESTAMP,
    updated_at     TEXT    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(stock_code, pattern_type, engine_version)
);

-- 23. 研报文章
CREATE TABLE IF NOT EXISTS research_article (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT    NOT NULL,
    title      TEXT    NOT NULL,
    content    TEXT    NOT NULL,
    source     TEXT    NOT NULL DEFAULT '宏观API',
    fetched_at TEXT    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, title)
);
CREATE INDEX IF NOT EXISTS idx_ra_category ON research_article(category, fetched_at DESC);

-- 24. 研报标签库
CREATE TABLE IF NOT EXISTS tag_library (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tag         TEXT    NOT NULL UNIQUE,
    category    TEXT    NOT NULL,
    description TEXT,
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db(db_path: str):
    """初始化数据库，执行建表 DDL"""
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    init_db("../../data/stock.db")
    print("数据库初始化完成: data/stock.db")
