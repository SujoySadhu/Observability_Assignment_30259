"""Shared FastAPI dependencies: fault injection and authentication."""
import logging

from fastapi import Header, HTTPException, Request

from . import chaos, db, metrics
from .logs import log
from .security import token_hash

logger = logging.getLogger("orderapi")


async def apply_chaos(request: Request) -> None:
    if await chaos.maybe_inject():
        if request.method == "POST" and request.url.path == "/api/orders":
            metrics.ORDERS_FAILED.labels(reason="injected").inc()
        log(logger, logging.ERROR, "injected failure (chaos)", path=request.url.path)
        raise HTTPException(500, detail={"reason": "injected", "message": "chaos: injected failure"})


def current_user(authorization: str | None = Header(default=None)) -> dict:
    """Resolve 'Authorization: Bearer <token>' to a user, or answer 401."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, detail={"reason": "unauthenticated", "message": "Please log in."})
    with db.connection() as conn, db.timed("select_session"):
        user = conn.execute(
            "SELECT u.id, u.email, u.name FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = %s AND s.expires_at > now()",
            (token_hash(authorization[7:]),),
        ).fetchone()
    if user is None:
        raise HTTPException(401, detail={"reason": "session_expired", "message": "Your session has expired. Please log in again."})
    return user
