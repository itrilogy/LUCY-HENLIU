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


def test_backtest_with_too_short_data():
    pde = PatternDiscoveryEngine("000037")
    pde.fit(_make_kline(30))
    bt = pde.backtest(window=50, step=5)
    assert "error" in bt or bt.get("total", 0) == 0  # 数据不足时不崩溃
