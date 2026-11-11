"""PostgreSQL access: a connection pool plus a timing helper for every query."""
import os
import time
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import metrics

pool: ConnectionPool | None = None


def init_pool() -> ConnectionPool:
    """Create the pool without blocking startup.

    An empty conninfo makes libpq read PGHOST, PGUSER, PGPASSWORD and PGDATABASE
    from the environment, so the password never sits in a URL or in the code.
    open(wait=False) means the API starts even if Postgres is down: /health
    still answers, /ready reports the database problem, and the metrics show it.
    """
    global pool
    pool = ConnectionPool(
        conninfo=os.getenv("DATABASE_URL", ""),
        min_size=2,
        max_size=int(os.getenv("DB_POOL_MAX", "10")),
        timeout=5,  # seconds to wait for a free connection before raising PoolTimeout
        kwargs={"row_factory": dict_row},
        open=False,
    )
    pool.open(wait=False)

    # These gauges are computed at scrape time: Prometheus calls /metrics,
    # the client library calls these functions and reports the current value.
    metrics.DB_POOL_CONNECTIONS.labels(state="managed").set_function(
        lambda: pool.get_stats().get("pool_size", 0)
    )
    metrics.DB_POOL_CONNECTIONS.labels(state="idle").set_function(
        lambda: pool.get_stats().get("pool_available", 0)
    )
    metrics.DB_POOL_WAITING.set_function(
        lambda: pool.get_stats().get("requests_waiting", 0)
    )
    return pool


@contextmanager
def connection(timeout: float | None = None):
    """Borrow a pooled connection; count a failure to get one as db_errors_total{operation="connect"}.

    The block commits on success and rolls back if an exception escapes it.
    """
    try:
        ctx = pool.connection(timeout=timeout)
        conn = ctx.__enter__()
    except Exception:
        metrics.DB_ERRORS.labels(operation="connect").inc()
        raise
    try:
        yield conn
    except BaseException as exc:
        if not ctx.__exit__(type(exc), exc, exc.__traceback__):
            raise
    else:
        ctx.__exit__(None, None, None)


def close_pool() -> None:
    if pool is not None:
        pool.close()


@contextmanager
def timed(operation: str):
    """Measure one database operation and count it as an error if it raises.

    with db.timed("insert_order"):
        conn.execute(...)
    """
    start = time.perf_counter()
    try:
        yield
    except Exception:
        metrics.DB_ERRORS.labels(operation=operation).inc()
        raise
    finally:
        metrics.DB_QUERY_DURATION.labels(operation=operation).observe(
            time.perf_counter() - start
        )
