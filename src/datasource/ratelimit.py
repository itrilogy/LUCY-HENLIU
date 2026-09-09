"""
数据源 API 统一调用封装：超时、指数退避重试、限额熔断。

能力：
- 对 429 / 503 / 超时 自动指数退避重试（国投证券的瞬时限流）
- 识别国信证券日限额错误码 197006，命中后当日熔断（停止无效请求，避免浪费配额）
- 统一超时与错误日志

用法（以 gs_client 为例）：
    data = api_call(get_json, url, breaker_key="gs")
    # get_json 内部对响应抛 RetryableError / QuotaExceededError
"""

import logging
import random
import time
from datetime import datetime, timedelta
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 国信证券日限额错误码（当日无法恢复，触发熔断）
GS_QUOTA_CODE = 197006


class APIError(Exception):
    """API 调用失败的基类"""


class RetryableError(APIError):
    """可重试错误：429 / 503 / 网络超时等瞬时故障"""


class QuotaExceededError(APIError):
    """配额耗尽：当日无法恢复，不应重试"""


class CircuitBreaker:
    """按供应商维度的熔断器：配额耗尽后冷却期内不再发请求。"""

    def __init__(self, cooldown: float = 3600.0, until_midnight: bool = False):
        self.cooldown = cooldown
        self.until_midnight = until_midnight
        self._opened_until = 0.0
        self._reason = ""

    def open(self, reason: str) -> None:
        if self.until_midnight:
            now = datetime.now()
            nxt = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            self._opened_until = nxt.timestamp()
            wait = max(1, int(self._opened_until - time.time()))
        else:
            self._opened_until = time.time() + self.cooldown
            wait = int(self.cooldown)
        self._reason = reason
        logger.warning("🔌 熔断器打开（%s），%d 秒内不再请求该数据源", reason, wait)

    def close(self) -> None:
        self._opened_until = 0.0
        self._reason = ""

    @property
    def is_open(self) -> bool:
        return time.time() < self._opened_until

    @property
    def reason(self) -> str:
        return self._reason


# 全局熔断器：gs（国信）/ sdicsc（国投）各自独立，互不影响
BREAKERS: dict[str, CircuitBreaker] = {
    "gs": CircuitBreaker(until_midnight=True),  # 国信日限额：熔到次日 0 点
    "sdicsc": CircuitBreaker(),
}


def api_call(fn: Callable[[], T], *, retries: int = 3,
             base_delay: float = 1.0, max_delay: float = 15.0,
             breaker_key: str = "") -> T:
    """
    带指数退避重试的调用封装。

    - fn() 抛 RetryableError → 退避重试（最多 retries 次）
    - fn() 抛 QuotaExceededError → 打开熔断器后立即失败
    - 熔断器已打开 → 直接抛 QuotaExceededError，不发请求
    - 其他异常 → 立即上抛

    :param breaker_key: 'gs' / 'sdicsc' / ''（'' 表示不参与熔断）
    """
    breaker = BREAKERS.get(breaker_key) if breaker_key else None
    if breaker is not None and breaker.is_open:
        raise QuotaExceededError(f"熔断中: {breaker.reason}")

    delay = base_delay
    for attempt in range(retries + 1):
        try:
            return fn()
        except QuotaExceededError as e:
            if breaker is not None:
                breaker.open(str(e))
            raise
        except RetryableError as e:
            if attempt >= retries:
                raise
            jitter = random.uniform(0.5, 1.5) * delay
            logger.warning("⏳ 第 %d 次重试（%.1fs 后）: %s", attempt + 1, jitter, e)
            time.sleep(jitter)
            delay = min(delay * 2, max_delay)
    raise RetryableError("重试次数耗尽")  # 理论不可达
