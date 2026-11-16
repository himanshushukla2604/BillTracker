"""Accounts and cookie sessions. Every /api route except these and /api/health needs a login.

Passwords are hashed with PBKDF2-SHA256 (stdlib, no extra dependency). Sessions are random
tokens kept in an HttpOnly cookie; only their SHA-256 is stored, so a leaked database does
not hand out live sessions.

Failed password checks are throttled three ways (see `_blocked`), so guessing is slow but a
stranger cannot lock you out of your own account just by knowing your email.

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
# Wrong passwords allowed within FAILURE_WINDOW seconds before further tries get a 429.
MAX_FAILURES = 10  # from one address against one email
MAX_FAILURES_PER_IP = 30  # from one address against any emails (password spraying)
MAX_FAILURES_PER_EMAIL = 100  # against one email from anywhere (many addresses, one target)
FAILURE_WINDOW = 15 * 60
MAX_SIGNUPS_PER_IP = 5  # new accounts from one address within SIGNUP_WINDOW seconds
SIGNUP_WINDOW = 60 * 60
MAX_TRACKED = 10_000  # throttle entries kept in memory before stale ones are dropped
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(prefix="/api/auth", tags=["auth"])
_failures: dict[str, list[float]] = {}  # "pair:<ip>|<email>", "ip:<ip>", "email:<email>" -> failure times
_signups: dict[str, list[float]] = {}  # ip -> sign-up times


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


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AccountDeletion(BaseModel):
    password: str = Field(max_length=128)


# ---------------------------------------------------------------- throttling

def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _recent(store: dict[str, list[float]], key: str, window: float) -> int:
    """How many events `key` has within `window`; forgets older ones."""
    cutoff = time.monotonic() - window
    recent = [t for t in store.get(key, ()) if t > cutoff]
    if recent:
        store[key] = recent
    else:
        store.pop(key, None)
    return len(recent)


def _record(store: dict[str, list[float]], key: str, window: float) -> None:
    if len(store) >= MAX_TRACKED:  # bounded memory: drop whatever has gone quiet
        for k in list(store):
            _recent(store, k, window)
        if len(store) >= MAX_TRACKED:
            store.clear()
    store.setdefault(key, []).append(time.monotonic())


def _failure_keys(ip: str, email: str) -> list[tuple[str, int]]:
    return [(f"pair:{ip}|{email}", MAX_FAILURES), (f"ip:{ip}", MAX_FAILURES_PER_IP),
            (f"email:{email}", MAX_FAILURES_PER_EMAIL)]


def _blocked(ip: str, email: str) -> bool:
    return any(_recent(_failures, key, FAILURE_WINDOW) >= cap for key, cap in _failure_keys(ip, email))


def _failed(ip: str, email: str) -> None:
    for key, _ in _failure_keys(ip, email):
        _record(_failures, key, FAILURE_WINDOW)


def _check_password(conn: sqlite3.Connection, uid: int, password: str, request: Request) -> sqlite3.Row:
    """The logged-in user's row, once they have re-entered their password (401 if wrong, 429 if guessing)."""
    row = conn.execute("SELECT id, email, password_hash FROM users WHERE id=?", (uid,)).fetchone()
    ip = _client_ip(request)
    if _blocked(ip, row["email"]):
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")
    if not verify_password(password, row["password_hash"]):
        _failed(ip, row["email"])
        raise HTTPException(401, "That is not your current password")
    return row


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: NewAccount, request: Request, response: Response,
             conn: sqlite3.Connection = Depends(db.get_conn)):
    first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    if not first and os.environ.get("FT_REGISTRATION", "1") == "0":
        raise HTTPException(403, "Sign-ups are closed on this server")
    ip = _client_ip(request)
    if _recent(_signups, ip, SIGNUP_WINDOW) >= MAX_SIGNUPS_PER_IP:
        raise HTTPException(429, "Too many new accounts from here. Try again in an hour.")
    if conn.execute("SELECT 1 FROM users WHERE email=?", (body.email,)).fetchone():
        raise HTTPException(409, "An account with this email already exists")
    uid = conn.execute("INSERT INTO users (email, password_hash) VALUES (?,?)",
                       (body.email, hash_password(body.password))).lastrowid
    # Every account starts empty: nobody inherits data that existed before them.
    if os.environ.get("FT_SEED", "0") == "1":
        from .seed import seed_demo
        seed_demo(conn, uid)
    conn.commit()
    _record(_signups, ip, SIGNUP_WINDOW)
    _start_session(conn, uid, request, response)
    return UserOut(id=uid, email=body.email)


@router.post("/login", response_model=UserOut)
def login(body: Credentials, request: Request, response: Response,
          conn: sqlite3.Connection = Depends(db.get_conn)):
    ip = _client_ip(request)
    if _blocked(ip, body.email):
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")
    row = conn.execute("SELECT id, password_hash FROM users WHERE email=?", (body.email,)).fetchone()
    if not verify_password(body.password, row["password_hash"] if row else _DUMMY_HASH) or not row:
        _failed(ip, body.email)
        raise HTTPException(401, "Wrong email or password")
    _failures.pop(f"pair:{ip}|{body.email}", None)
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


@router.post("/password", status_code=204)
def change_password(body: PasswordChange, request: Request, uid: int = Depends(current_user),
                    conn: sqlite3.Connection = Depends(db.get_conn)):
    """Sets a new password and logs out every other device; this one stays logged in."""
    _check_password(conn, uid, body.current_password, request)
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(body.new_password), uid))
    conn.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?",
                 (uid, _token_hash(request.cookies.get(COOKIE, ""))))
    conn.commit()
    return Response(status_code=204)


@router.post("/delete-account", status_code=204)
def delete_account(body: AccountDeletion, request: Request, uid: int = Depends(current_user),
                   conn: sqlite3.Connection = Depends(db.get_conn)):
    """Erases the account and everything in it (expenses, cards, loans, goals, budgets, sessions).

    Daily server backups made before today still hold the data until they rotate out.
    """
    _check_password(conn, uid, body.password, request)
    conn.execute("DELETE FROM users WHERE id=?", (uid,))  # every table cascades from users
    conn.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response
