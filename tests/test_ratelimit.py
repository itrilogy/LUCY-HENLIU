"""限流/重试/熔断封装测试"""
import pytest

from src.datasource.ratelimit import (
    api_call, RetryableError, QuotaExceededError, CircuitBreaker, BREAKERS,
)


def test_retry_success_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RetryableError("429")
        return "ok"

    result = api_call(flaky, retries=5, base_delay=0.01)
    assert result == "ok"
    assert calls["n"] == 3


def test_retry_exhausted_raises():
    def always_fail():
        raise RetryableError("503")

    with pytest.raises(RetryableError):
        api_call(always_fail, retries=2, base_delay=0.01)


def test_quota_error_not_retried():
    calls = {"n": 0}

    def quota():
        calls["n"] += 1
        raise QuotaExceededError("日限额")

    with pytest.raises(QuotaExceededError):
        api_call(quota, retries=5, base_delay=0.01)
    assert calls["n"] == 1  # 配额错误不重试


def test_breaker_blocks_requests_until_closed():
    BREAKERS["gs"].close()
    BREAKERS["gs"].open("测试熔断")
    with pytest.raises(QuotaExceededError):
        api_call(lambda: (_ for _ in ()).throw(AssertionError("不应被调用")),
                 breaker_key="gs")
    BREAKERS["gs"].close()
    assert api_call(lambda: "ok", breaker_key="gs") == "ok"


def test_breaker_auto_opens_on_quota_error():
    BREAKERS["gs"].close()  # 确保干净状态

    def quota():
        raise QuotaExceededError("日限额")

    with pytest.raises(QuotaExceededError):
        api_call(quota, breaker_key="gs")
    assert BREAKERS["gs"].is_open  # 自动熔断
    BREAKERS["gs"].close()


def test_gs_breaker_opens_until_midnight():
    import time
    from datetime import datetime, timedelta
    BREAKERS["gs"].close()
    BREAKERS["gs"].open("日限额")
    assert BREAKERS["gs"].is_open
    tomorrow = (datetime.now() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    # 打开后的截止应在次日 0 点附近（允许 2 秒误差）
    assert abs(BREAKERS["gs"]._opened_until - tomorrow.timestamp()) < 2
    assert BREAKERS["gs"]._opened_until > time.time() + 60
    BREAKERS["gs"].close()


def test_global_breakers_isolated():
    # gs 熔断不影响 sdicsc
    BREAKERS["gs"].open("测试")
    assert BREAKERS["gs"].is_open
    assert not BREAKERS["sdicsc"].is_open
    BREAKERS["gs"].close()


def test_normal_exception_passthrough():
    with pytest.raises(ValueError):
        api_call(lambda: (_ for _ in ()).throw(ValueError("boom")),
                 retries=2, base_delay=0.01)
