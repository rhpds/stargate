"""Resilience utilities — retry with backoff and circuit breaker."""

import logging
import time
import urllib.error
from typing import Callable, TypeVar

logger = logging.getLogger("stargate.resilience")

T = TypeVar("T")

RETRYABLE_EXCEPTIONS = (
    urllib.error.URLError,
    TimeoutError,
    ConnectionError,
    OSError,
)


def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    operation: str = "operation",
) -> T:
    for attempt in range(max_retries):
        try:
            return func()
        except RETRYABLE_EXCEPTIONS as e:
            if attempt == max_retries - 1:
                logger.warning(f"{operation} failed after {max_retries} attempts: {e}")
                raise
            delay = base_delay * (2 ** attempt)
            logger.info(f"{operation} attempt {attempt + 1} failed, retrying in {delay}s: {e}")
            time.sleep(delay)
    raise RuntimeError(f"{operation} failed")


class CircuitBreaker:
    """Simple circuit breaker — opens after N failures, closes after cooldown."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 60.0, name: str = "circuit"):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.name = name
        self._failures = 0
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        if time.time() >= self._open_until:
            return False
        return True

    def record_success(self):
        self._failures = 0

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open_until = time.time() + self.cooldown_seconds
            logger.warning(f"Circuit breaker '{self.name}' OPEN — {self._failures} failures, cooling down {self.cooldown_seconds}s")

    def check(self) -> bool:
        if self.is_open:
            logger.debug(f"Circuit breaker '{self.name}' is open — fast-failing")
            return False
        return True
