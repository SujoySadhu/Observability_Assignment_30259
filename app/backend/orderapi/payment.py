"""A simulated external payment gateway.

Real services spend much of their time waiting on dependencies. This gives the
API a realistic dependency with:
  * a log-normal latency distribution (most calls fast, a long slow tail)
  * a rare very slow call (1%) that hits the timeout -> pushes p95/p99 up
  * a configurable decline rate (see chaos.py)
"""
import math
import random
import time

from . import chaos, metrics

TIMEOUT_SECONDS = 1.0
# Typical latency per payment method, in seconds.
BASE_LATENCY = {"card": 0.12, "wallet": 0.08, "cash": 0.005}


def charge(amount_cents: int, method: str) -> str:
    """Return 'approved', 'declined' or 'timeout'."""
    start = time.perf_counter()
    delay = random.lognormvariate(math.log(BASE_LATENCY[method]), 0.5)
    if method != "cash" and random.random() < 0.01:
        delay *= 12  # rare slow gateway response

    if delay > TIMEOUT_SECONDS:
        time.sleep(TIMEOUT_SECONDS)  # we give up waiting
        result = "timeout"
    else:
        time.sleep(delay)
        declined = method != "cash" and random.random() < chaos.get().payment_failure_rate
        result = "declined" if declined else "approved"

    metrics.PAYMENT_DURATION.labels(method=method).observe(time.perf_counter() - start)
    metrics.PAYMENT_REQUESTS.labels(method=method, result=result).inc()
    return result
