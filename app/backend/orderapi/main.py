"""ShopLite API: application setup, instrumentation, health and metrics.

Business endpoints live in their own modules:
  auth.py     /api/auth/register, /login, /logout, /me
  catalog.py  /api/categories, /api/products, /api/products/{id}
  cart.py     /api/cart, /api/cart/items[/{product_id}]
  orders.py   POST /api/orders (checkout), GET /api/orders[/{order_id}]
  admin.py    /api/admin/chaos, /api/admin/restock   (operator tools)
"""
import logging
import os
import platform
import re
import time
import uuid
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import admin, auth, cart, catalog, db, flaws, metrics, orders
from .logs import log, request_id_var, setup_logging

APP_VERSION = os.getenv("APP_VERSION", "dev")
setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("orderapi")

KNOWN_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


# =============================================================================
# Instrumentation middleware: one place that measures EVERY request
# =============================================================================
class ObservabilityMiddleware:
    """Pure ASGI middleware: request ID, RED metrics and one access log line.

    Why the route *template* is the label: /api/orders/17 and /api/orders/18
    must count as the same series, route="/api/orders/{order_id}". Using the
    raw path would create one time series per order ID (unbounded cardinality).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/metrics":
            # Don't measure the scrapes themselves; they would add noise.
            return await self.app(scope, receive, send)

        method = scope["method"] if scope["method"] in KNOWN_METHODS else "OTHER"
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        # Only accept a well-formed incoming ID (from nginx); otherwise make one.
        # Never trust client input blindly: it ends up in logs.
        request_id = incoming if SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)

        status = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        metrics.HTTP_IN_PROGRESS.labels(method=method).inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status["code"] = 500
            logger.exception("unhandled exception", extra={"fields": {"path": scope["path"]}})
            raise
        finally:
            duration = time.perf_counter() - start
            metrics.HTTP_IN_PROGRESS.labels(method=method).dec()
            # FastAPI stores the matched route in the scope during routing.
            route_obj = scope.get("route")
            route = getattr(route_obj, "path", None) or "unmatched"
            code = status["code"]
            metrics.HTTP_REQUESTS.labels(method=method, route=route, status=str(code)).inc()
            metrics.HTTP_DURATION.labels(method=method, route=route).observe(duration)

            level = logging.ERROR if code >= 500 else logging.WARNING if code >= 400 else logging.INFO
            if route not in ("/health", "/ready") or code >= 400:
                log(
                    logger, level, "request completed",
                    method=scope["method"], route=route, path=scope["path"],
                    status=code, duration_ms=round(duration * 1000, 1),
                )
            request_id_var.reset(token)


# =============================================================================
# App lifecycle
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    metrics.BUILD_INFO.info({"version": APP_VERSION, "python": platform.python_version()})
    db.init_pool()
    log(logger, logging.INFO, "starting", version=APP_VERSION, flaws=flaws.enabled())
    try:
        admin.refresh_stock_gauges(timeout=10)
        log(logger, logging.INFO, "startup complete", database="connected")
    except psycopg.Error as exc:
        log(logger, logging.ERROR, "startup: database not reachable yet", error=str(exc))
    yield
    db.close_pool()
    log(logger, logging.INFO, "shutdown complete")


app = FastAPI(title="ShopLite API", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(ObservabilityMiddleware)


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    if request.method == "POST" and request.url.path == "/api/orders":
        metrics.ORDERS_FAILED.labels(reason="validation").inc()
    errors = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
    # Never echo submitted values (could be passwords) into logs: messages only.
    log(logger, logging.WARNING, "validation failed", path=request.url.path,
        errors=[f"{'.'.join(map(str, e.get('loc', [])))}: {e.get('msg')}" for e in errors])
    for e in errors:
        e.pop("input", None)
    return JSONResponse(status_code=422, content={"detail": {"reason": "validation", "errors": errors,
                                                             "message": "Please check the highlighted fields."}})


@app.exception_handler(psycopg.Error)
async def on_database_error(request: Request, exc: psycopg.Error):
    """Any database failure (incl. pool timeout) becomes a clean 503."""
    if request.method == "POST" and request.url.path == "/api/orders":
        metrics.ORDERS_FAILED.labels(reason="db_error").inc()
    log(logger, logging.ERROR, "database error", path=request.url.path,
        error_type=type(exc).__name__, error=str(exc))
    return JSONResponse(status_code=503, content={"detail": {"reason": "db_error",
                                                             "message": "We're having trouble right now. Please try again shortly."}})


# =============================================================================
# Health, readiness, metrics
# =============================================================================
@app.get("/health")
def health():
    """Liveness: answers as long as the process works. Docker's healthcheck uses it."""
    return {"status": "ok", "version": APP_VERSION}


@app.get("/ready")
def ready():
    """Readiness: can we actually serve traffic? Checks the database."""
    try:
        with db.connection(timeout=2) as conn, db.timed("health_check"):
            conn.execute("SELECT 1")
        return {"status": "ready", "database": "ok"}
    except psycopg.Error as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": str(exc)})


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


for module in (auth, catalog, cart, orders, admin):
    app.include_router(module.router)
