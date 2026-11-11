"""Fault injection ("chaos") for controlled failure demos.

Changed at runtime through PUT /api/admin/chaos. Because the settings are also
exported as the chaos_injection gauge, a dashboard can show *why* errors or
latency went up during a demo.
"""
import asyncio
import random
import threading
from dataclasses import asdict, dataclass

from . import metrics


@dataclass
class ChaosConfig:
    extra_latency_ms: int = 0          # added to every business request
    error_rate: float = 0.0            # fraction of business requests that fail with HTTP 500
    payment_failure_rate: float = 0.03  # fraction of card/wallet payments declined (3% is "normal")


_lock = threading.Lock()
_config = ChaosConfig()


def _publish(cfg: ChaosConfig) -> None:
    for key, value in asdict(cfg).items():
        metrics.CHAOS.labels(type=key).set(value)


def get() -> ChaosConfig:
    with _lock:
        return ChaosConfig(**asdict(_config))


def update(**changes) -> ChaosConfig:
    global _config
    with _lock:
        _config = ChaosConfig(**{**asdict(_config), **changes})
        _publish(_config)
        return ChaosConfig(**asdict(_config))


def reset() -> ChaosConfig:
    global _config
    with _lock:
        _config = ChaosConfig()
        _publish(_config)
        return ChaosConfig(**asdict(_config))


async def maybe_inject() -> bool:
    """Apply the configured latency; return True if this request should fail."""
    cfg = get()
    if cfg.extra_latency_ms > 0:
        # +/-20% jitter so the latency histogram looks like real traffic.
        jitter = random.uniform(0.8, 1.2)
        await asyncio.sleep(cfg.extra_latency_ms * jitter / 1000)
    return random.random() < cfg.error_rate


_publish(_config)
