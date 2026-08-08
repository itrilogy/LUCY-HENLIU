"""量化引擎测试"""
import numpy as np
import pandas as pd
import pytest

from src.quant.engine import MomentumAnalyzer, RegimeClassifier, MarkovTransition


def _make_kline(n=80, seed=1, base=10.0):
    rng = np.random.default_rng(seed)
    close = base + np.cumsum(rng.normal(0, 0.3, n))
    close = np.maximum(close, base * 0.5)
    dates = pd.bdate_range("2026-01-01", periods=n)
    return pd.DataFrame({
        "trade_date": dates.strftime("%Y-%m-%d"),
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": np.full(n, 100000),
        "amount": np.full(n, 1e6),
    })


def test_momentum_compute_returns_all_keys():
    kdf = _make_kline(80)
    m = MomentumAnalyzer.compute(kdf)
    assert m is not None
    for k in ("ret_5d", "ret_20d", "ret_60d", "ma5", "ma20", "ma60",
              "trend", "strength", "signal"):
        assert k in m, f"缺少动量指标 {k}"


def test_momentum_short_data_returns_empty():
    # 数据不足时返回空 dict（不崩溃）
    assert not MomentumAnalyzer.compute(_make_kline(3))


def test_momentum_uptrend_detected():
    # 单调上涨 → 多头排列
    n = 80
    close = np.linspace(10, 20, n)
    kdf = pd.DataFrame({
        "trade_date": pd.bdate_range("2026-01-01", periods=n).strftime("%Y-%m-%d"),
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.full(n, 100000), "amount": np.full(n, 1e6),
    })
    m = MomentumAnalyzer.compute(kdf)
    assert "多头" in m["trend"]
    assert m["signal"] == "买入 🟢"


def test_regime_classifier_fit_and_predict():
    kdf = _make_kline(80)
    rc = RegimeClassifier(n_regimes=3)
    rc.fit(kdf)
    # predict 需要三个特征值
    state = rc.predict(return_val=0.5, volatility=1.0, volume_ratio=1.2)
    assert state in rc.regime_names.values()
    # get_regime_series 返回 [(日期, 状态)] 序列（前 5 行因 rolling NaN 被丢弃）
    series = rc.get_regime_series(kdf)
    assert 0 < len(series) <= len(kdf)
    assert all(len(item) == 2 for item in series)


def test_markov_transition_matrix():
    rng = np.random.default_rng(3)
    returns = rng.normal(0, 1, 200)
    mt = MarkovTransition(n_states=3)
    mt.fit(returns)
    tm = mt.transition_matrix
    assert tm.shape == (3, 3)
    assert np.allclose(tm.sum(axis=1), 1.0)
    # 持续性 = 对角线和 / 3
    assert 0.0 <= mt.get_persistence() <= 1.0
