"""Registration, login, logout, current user."""
import logging

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from . import db, metrics
from .deps import apply_chaos, current_user
from .logs import log
from .security import burn_dummy_hash, hash_password, new_token, token_hash, verify_password

logger = logging.getLogger("orderapi")
router = APIRouter(prefix="/api/auth", dependencies=[Depends(apply_chaos)])

SESSION_DAYS = 7
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=120)
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: str = Field(max_length=120)
    password: str = Field(max_length=128)


def _start_session(conn, user_id: int) -> str:
    token, hashed = new_token()
    with db.timed("insert_session"):
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) "
            "VALUES (%s, %s, now() + make_interval(days => %s))",
            (hashed, user_id, SESSION_DAYS),
        )
    return token


@router.post("/register", status_code=201)
def register(body: RegisterIn):
    email = body.email.strip().lower()
    with db.connection() as conn, db.timed("select_user"):
        exists = conn.execute("SELECT 1 FROM users WHERE email = %s", (email,)).fetchone()
    if exists:
        metrics.AUTH_EVENTS.labels(event="register", result="failure").inc()
        log(logger, logging.WARNING, "registration failed: email already registered")
        raise HTTPException(409, detail={"reason": "email_taken", "message": "An account with this email already exists."})
    password_hash = hash_password(body.password)  # CPU-heavy on purpose (see security.py)
    try:
        with db.connection() as conn:
            with db.timed("insert_user"):
                user = conn.execute(
                    "INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s) RETURNING id, email, name",
                    (email, body.name.strip(), password_hash),
                ).fetchone()
            token = _start_session(conn, user["id"])
    except psycopg.errors.UniqueViolation:
        metrics.AUTH_EVENTS.labels(event="register", result="failure").inc()
        log(logger, logging.WARNING, "registration failed: email already registered")
        raise HTTPException(409, detail={"reason": "email_taken", "message": "An account with this email already exists."})
    metrics.AUTH_EVENTS.labels(event="register", result="success").inc()
    log(logger, logging.INFO, "user registered", user_id=user["id"])
    return {"token": token, "user": user}


@router.post("/login")
def login(body: LoginIn):
    email = body.email.strip().lower()
    with db.connection() as conn:
        with db.timed("select_user"):
            user = conn.execute(
                "SELECT id, email, name, password_hash FROM users WHERE email = %s", (email,)
            ).fetchone()
        if user is None:
            burn_dummy_hash(body.password)
            ok = False
        else:
            ok = verify_password(body.password, user["password_hash"])
        if not ok:
            metrics.AUTH_EVENTS.labels(event="login", result="failure").inc()
            # Never log the email or password: logs are widely readable.
            log(logger, logging.WARNING, "login failed: bad credentials")
            raise HTTPException(401, detail={"reason": "bad_credentials", "message": "Incorrect email or password."})
        token = _start_session(conn, user["id"])
    metrics.AUTH_EVENTS.labels(event="login", result="success").inc()
    log(logger, logging.INFO, "user logged in", user_id=user["id"])
    return {"token": token, "user": {"id": user["id"], "email": user["email"], "name": user["name"]}}


@router.post("/logout", status_code=204)
def logout(authorization: str | None = Header(default=None), user: dict = Depends(current_user)):
    with db.connection() as conn, db.timed("delete_session"):
        conn.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash(authorization[7:]),))
    metrics.AUTH_EVENTS.labels(event="logout", result="success").inc()
    log(logger, logging.INFO, "user logged out", user_id=user["id"])


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return user
