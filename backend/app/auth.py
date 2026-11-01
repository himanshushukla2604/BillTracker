"""Accounts and cookie sessions. Every /api route except these and /api/health needs a login.

Passwords are hashed with PBKDF2-SHA256 (stdlib, no extra dependency). Sessions are random
tokens kept in an HttpOnly cookie; only their SHA-256 is stored, so a leaked database does
not hand out live sessions.

Env: FT_REGISTRATION=0 closes sign-ups (the very first account can always be created).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from . import db

COOKIE = "ft_session"
SESSION_DAYS = 30
PBKDF2_ITERATIONS = 600_000
MAX_FAILURES = 10  # per email, within FAILURE_WINDOW seconds
FAILURE_WINDOW = 15 * 60
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(prefix="/api/auth", tags=["auth"])
_failures: dict[str, list[float]] = {}


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
    return hmac.compare_digest(actual, base64.b64decode(digest))


# Checked against when the email is unknown, so both cases take the same time.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


# ----------------------------------------------------------------- sessions

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _start_session(conn: sqlite3.Connection, user_id: int, request: Request, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    expires = _now() + timedelta(days=SESSION_DAYS)
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now().isoformat(),))
    conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
                 (_token_hash(token), user_id, expires.isoformat()))
    conn.commit()
    response.set_cookie(
        COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
        secure=request.url.scheme == "https", path="/",
    )


def current_user(request: Request, conn: sqlite3.Connection = Depends(db.get_conn)) -> int:
    """FastAPI dependency: the logged-in user's id, or 401."""
    token = request.cookies.get(COOKIE)
    if token:
        row = conn.execute(
            "SELECT user_id FROM sessions WHERE token_hash=? AND expires_at > ?",
            (_token_hash(token), _now().isoformat()),
        ).fetchone()
        if row:
            return row["user_id"]
    raise HTTPException(401, "Please log in")


# ------------------------------------------------------------------- routes

class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("enter a valid email address")
        return v


class NewAccount(Credentials):
    @field_validator("password")
    @classmethod
    def _strong_enough(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("use at least 8 characters")
        return v


class UserOut(BaseModel):
    id: int
    email: str


def _throttled(email: str) -> bool:
    cutoff = time.monotonic() - FAILURE_WINDOW
    recent = [t for t in _failures.get(email, []) if t > cutoff]
    _failures[email] = recent
    return len(recent) >= MAX_FAILURES


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: NewAccount, request: Request, response: Response,
             conn: sqlite3.Connection = Depends(db.get_conn)):
    first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    if not first and os.environ.get("FT_REGISTRATION", "1") == "0":
        raise HTTPException(403, "Sign-ups are closed on this server")
    if conn.execute("SELECT 1 FROM users WHERE email=?", (body.email,)).fetchone():
        raise HTTPException(409, "An account with this email already exists")
    uid = conn.execute("INSERT INTO users (email, password_hash) VALUES (?,?)",
                       (body.email, hash_password(body.password))).lastrowid
    if first:
        # Data from before accounts existed belongs to whoever sets the server up.
        for table in ("expenses", "budgets", "settings"):
            conn.execute(f"UPDATE {table} SET user_id=? WHERE user_id IS NULL", (uid,))
    elif os.environ.get("FT_SEED", "0") == "1":
        from .seed import seed_demo
        seed_demo(conn, uid)
    conn.commit()
    _start_session(conn, uid, request, response)
    return UserOut(id=uid, email=body.email)


@router.post("/login", response_model=UserOut)
def login(body: Credentials, request: Request, response: Response,
          conn: sqlite3.Connection = Depends(db.get_conn)):
    if _throttled(body.email):
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")
    row = conn.execute("SELECT id, password_hash FROM users WHERE email=?", (body.email,)).fetchone()
    if not verify_password(body.password, row["password_hash"] if row else _DUMMY_HASH) or not row:
        _failures.setdefault(body.email, []).append(time.monotonic())
        raise HTTPException(401, "Wrong email or password")
    _failures.pop(body.email, None)
    _start_session(conn, row["id"], request, response)
    return UserOut(id=row["id"], email=body.email)


@router.post("/logout", status_code=204)
def logout(request: Request, conn: sqlite3.Connection = Depends(db.get_conn)):
    token = request.cookies.get(COOKIE)
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
        conn.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response


@router.get("/me", response_model=UserOut)
def me(uid: int = Depends(current_user), conn: sqlite3.Connection = Depends(db.get_conn)):
    row = conn.execute("SELECT id, email FROM users WHERE id=?", (uid,)).fetchone()
    return UserOut(id=row["id"], email=row["email"])
