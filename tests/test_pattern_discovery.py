"""模式发现引擎测试"""
import numpy as np
import pandas as pd
import pytest

from src.quant.pattern_discovery import PatternDiscoveryEngine

# _compute_features 生成的特征列（与实现一致）
FEATURE_COLS = [
    "return", "tr", "atr", "rsi", "macd_dif", "macd_dea", "macd_bar",
    "boll_mid", "boll_std", "boll_up", "boll_dn", "boll_pos",
    "vol_ma5", "vol_ratio", "volatility",
    "next_return", "next_direction", "next_close",
]


def _make_kline(n=120, seed=42):
    rng = np.random.default_rng(seed)
    close = np.maximum(10 + np.cumsum(rng.normal(0, 0.4, n)), 5)
    dates = pd.bdate_range("2026-01-01", periods=n).strftime("%Y-%m-%d")
    return pd.DataFrame({
        "trade_date": dates,
        "open": close, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": np.full(n, 100000),
        "amount": np.full(n, 1e6),
    })


def test_fit_adds_features():
    pde = PatternDiscoveryEngine("000037")
    assert pde.fit(_make_kline(120))
    for col in FEATURE_COLS:
        assert col in pde.df.columns, f"缺少特征列 {col}"
    # 末行 next_direction 应为 NaN（无次日数据，不产生假标签）
    assert pd.isna(pde.df["next_direction"].iloc[-1])


def test_discover_and_predict():
    pde = PatternDiscoveryEngine("000037")
    pde.fit(_make_kline(120))
    n = pde.discover_patterns()
    assert n >= 0
    pred = pde.predict()
    assert pred is None or pred.direction in ("up", "down", "flat")


def test_backtest_returns_metrics():
    pde = PatternDiscoveryEngine("000037")
    pde.fit(_make_kline(120))
    bt = pde.backtest(window=50, step=5)
    assert "total" in bt and "accuracy" in bt
    assert bt["total"] > 0
    assert 0.0 <= bt["accuracy"] <= 1.0
    # 增强指标：成本模型/回撤/夏普/分模式胜率
    for k in ("total_return", "max_drawdown", "sharpe", "trades", "per_pattern"):
        assert k in bt, f"缺少回测绩效指标 {k}"
    assert -1.0 <= bt["max_drawdown"] <= 0.0


def test_backtest_cost_reduces_return():
    pde = PatternDiscoveryEngine("000037")
    pde.fit(_make_kline(120))
    bt0 = pde.backtest(window=50, step=5, cost_pct=0.0)
    bt1 = pde.backtest(window=50, step=5, cost_pct=0.5)
    # 含成本（多换仓）的累计收益不高于无成本版本
    assert bt1["total_return"] <= bt0["total_return"] + 1e-9


def test_backtest_with_too_short_data():
    pde = PatternDiscoveryEngine("000037")
    pde.fit(_make_kline(30))
    bt = pde.backtest(window=50, step=5)
    assert "error" in bt or bt.get("total", 0) == 0  # 数据不足时不崩溃


def test_pattern_significance():
    pde = PatternDiscoveryEngine("000037")
    # 样本不足 → 不显著
    assert not pde._is_significant(4, 4)
    # 8/10 胜率 0.8，p=0.0547 > 0.05 → 不显著（临界）
    assert not pde._is_significant(8, 10)
    # 9/10 胜率 0.9，p=0.0107 < 0.05 → 显著
    assert pde._is_significant(9, 10)
    # 15/20 胜率 0.75，p≈0.021 → 显著
    assert pde._is_significant(15, 20)


def test_pattern_significance_flat_baseline():
    """flat 模式使用 1/3 随机基准（三分类），不应按 0.5 判定"""
    pde = PatternDiscoveryEngine("000037")
    # 16/30 @ p0=0.5：P(X>=16|0.5)≈0.43 不显著；@ p0=1/3：P(X>=16|1/3)≈0.01 显著
    # 关键断言：p0 参数确实改变判定
    r50 = pde._is_significant(16, 30, p0=0.5)
    r33 = pde._is_significant(16, 30, p0=1 / 3)
    assert r33 and not r50
