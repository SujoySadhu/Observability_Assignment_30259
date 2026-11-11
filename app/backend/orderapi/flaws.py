"""Switches for the deliberate flaws (for learning observability).

FLAWS is a comma-separated list in the environment (see compose.yaml):
  slow_queries  N+1 queries in cart and order history (+ missing indexes in the schema)
  memory_leak   unbounded search cache that is never evicted
  coupon_bug    fixed-amount coupons crash checkout with an unhandled TypeError (HTTP 500)
  slow_login    password hashing 5x more expensive than needed (CPU-heavy logins)

Set FLAWS="" to run the "fixed" version and compare the dashboards.
"""
import os

ALL = ("slow_queries", "memory_leak", "coupon_bug", "slow_login")
_enabled = {f.strip() for f in os.getenv("FLAWS", ",".join(ALL)).split(",") if f.strip()}


def on(name: str) -> bool:
    return name in _enabled


def enabled() -> list[str]:
    return sorted(_enabled)
