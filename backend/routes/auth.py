"""
Маршруты аутентификации: вход, выход, регистрация.
"""
import re
import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import backend.database.database as db
from backend.config import TEMPLATES_DIR, SESSION_COOKIE_NAME, SESSION_DAYS

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ── СТРАНИЦЫ ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None, registered: str = None):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error, "registered": registered},
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"form_data": {}},
    )


# ── API ──────────────────────────────────────────────────────────────────────

@router.post("/api/login")
async def api_login(username: str = Form(...), password: str = Form(...)):
    user = db.verify_user(username, password)
    if not user:
        return RedirectResponse(url="/?error=auth", status_code=303)
    token = secrets.token_urlsafe(32)
    db.save_session(user[0], token, days=SESSION_DAYS)
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * SESSION_DAYS,
        samesite="lax",
    )
    return response


@router.post("/api/logout")
async def api_logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        db.delete_session(token)
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@router.post("/api/register")
async def api_register(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    department: str = Form(...),
):
    form_data = {
        "full_name": full_name,
        "username": username,
        "role": role,
        "department": department,
    }

    def _err(code: str):
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": code, "form_data": form_data},
        )

    if len(full_name.strip()) < 5:
        return _err("invalid_name")
    if len(password) < 4:
        return _err("short_password")
    if not re.match(r"^[a-zA-Z0-9_]+$", username):
        return _err("invalid_username")

    user_id = db.add_user(full_name, username, password, role, department)
    if user_id:
        return RedirectResponse(url="/?registered=success", status_code=303)
    return _err("exists")