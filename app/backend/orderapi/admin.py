"""Operator endpoints: fault injection and restocking.

No fault injection here (so chaos can always be turned off) and no auth:
acceptable only because the API port is bound to the private host-only IP 192.168.56.20. In a real system
these would sit behind admin authentication or on a separate internal port.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import chaos, db, metrics
from .logs import log

logger = logging.getLogger("orderapi")
router = APIRouter(prefix="/api/admin")


class ChaosIn(BaseModel):
    extra_latency_ms: int = Field(default=0, ge=0, le=5000)
    error_rate: float = Field(default=0.0, ge=0, le=1)
    payment_failure_rate: float = Field(default=0.03, ge=0, le=1)


class RestockIn(BaseModel):
    amount: int = Field(default=100, gt=0, le=10000)


def refresh_stock_gauges(timeout: float | None = None) -> None:
    with db.connection(timeout=timeout) as conn, db.timed("select_stock"):
        rows = conn.execute("SELECT sku, stock FROM products").fetchall()
    for row in rows:
        metrics.PRODUCT_STOCK.labels(sku=row["sku"]).set(row["stock"])


@router.get("/chaos")
def get_chaos():
    return chaos.get()


@router.put("/chaos")
def set_chaos(cfg: ChaosIn):
    # Only the fields sent in the request change; the others keep their current value.
    changes = cfg.model_dump(exclude_unset=True)
    new = chaos.update(**changes)
    log(logger, logging.WARNING, "chaos settings changed", **changes)
    return new


@router.post("/chaos/reset")
def reset_chaos():
    log(logger, logging.WARNING, "chaos settings reset")
    return chaos.reset()


@router.post("/restock")
def restock(body: RestockIn):
    with db.connection() as conn, db.timed("restock"):
        conn.execute("UPDATE products SET stock = stock + %s", (body.amount,))
    refresh_stock_gauges()
    log(logger, logging.INFO, "restocked all products", amount=body.amount)
    return {"restocked_by": body.amount}
