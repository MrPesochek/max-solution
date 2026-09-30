from __future__ import annotations

import secrets
import time
from collections import deque

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from emulator.settings import Settings
from emulator.state import EmulatorState
from emulator.web import security
from emulator.web.templating import templates

router = APIRouter()

SESSION_COOKIE = "onec_emulator_session"
LOGIN_NONCE_COOKIE = "onec_emulator_login_nonce"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class NotAuthenticated(Exception):
    pass


def _settings(request: Request) -> Settings:
    state: EmulatorState = request.app.state.emulator
    return state.settings


def is_authenticated(request: Request) -> bool:
    cookie = request.cookies.get(SESSION_COOKIE)
    return security.verify_session_cookie(_settings(request).session_secret, cookie)


def session_csrf_token(secret: str, session_cookie: str) -> str:
    return security.csrf_token(secret, f"session.{session_cookie}")


def login_csrf_token(secret: str, nonce: str) -> str:
    return security.csrf_token(secret, f"login.{nonce}")


def csrf_token_for(request: Request) -> str:
    secret = _settings(request).session_secret
    session_cookie = request.cookies.get(SESSION_COOKIE)
    if session_cookie and security.verify_session_cookie(secret, session_cookie):
        return session_csrf_token(secret, session_cookie)
    nonce = getattr(request.state, "login_nonce", None) or request.cookies.get(LOGIN_NONCE_COOKIE)
    return login_csrf_token(secret, nonce) if nonce else ""


templates.env.globals["csrf_token"] = csrf_token_for


async def _provided_token(request: Request) -> str:
    header = request.headers.get(CSRF_HEADER)
    if header:
        return header
    content_type = request.headers.get("content-type", "")
    if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
        value = (await request.form()).get(CSRF_FIELD)
        return value if isinstance(value, str) else ""
    return ""


async def _check_csrf(request: Request, expected: str) -> None:
    provided = await _provided_token(request)
    if not expected or not provided or not security.check_password(expected, provided):
        raise HTTPException(status_code=403, detail="CSRF-токен формы недействителен")


async def require_session(request: Request) -> None:
    if not is_authenticated(request):
        raise NotAuthenticated()
    if request.method not in _SAFE_METHODS:
        secret = _settings(request).session_secret
        await _check_csrf(
            request, session_csrf_token(secret, request.cookies.get(SESSION_COOKIE, ""))
        )


def _client_key(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _recent_failures(request: Request) -> deque[float]:
    settings = _settings(request)
    now = time.monotonic()
    failures: dict[str, deque[float]] | None = getattr(request.app.state, "login_failures", None)
    if failures is None:
        failures = request.app.state.login_failures = {}
    hits = failures.setdefault(_client_key(request), deque())
    while hits and hits[0] <= now - settings.login_failure_window_seconds:
        hits.popleft()
    return hits


def _login_page(request: Request, error: str | None, status_code: int = 200) -> Response:
    nonce = secrets.token_urlsafe(24)
    request.state.login_nonce = nonce
    response = templates.TemplateResponse(
        request, "login.html", {"error": error}, status_code=status_code
    )
    response.set_cookie(LOGIN_NONCE_COOKIE, nonce, httponly=True, samesite="strict")
    return response


@router.get("/login")
async def login_form(request: Request) -> Response:
    return _login_page(request, None)


@router.post("/login")
async def login_submit(request: Request, password: str = Form(...)) -> Response:
    settings = _settings(request)
    nonce = request.cookies.get(LOGIN_NONCE_COOKIE, "")
    await _check_csrf(request, login_csrf_token(settings.session_secret, nonce) if nonce else "")

    failures = _recent_failures(request)
    if len(failures) >= settings.login_max_failures:
        return _login_page(request, "Слишком много попыток, попробуйте позже", status_code=429)
    if not security.check_password(settings.ui_password, password):
        failures.append(time.monotonic())
        return _login_page(request, "Неверный пароль", status_code=401)
    failures.clear()

    response = RedirectResponse("/ui/orders", status_code=303)
    cookie_value = security.issue_session_cookie(
        settings.session_secret, settings.session_ttl_seconds
    )
    response.set_cookie(
        SESSION_COOKIE,
        cookie_value,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(LOGIN_NONCE_COOKIE)
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    if is_authenticated(request):
        await require_session(request)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
