"""
FastAPI dependency: аутентификация через cookie-сессию.
"""
from fastapi import Request, HTTPException
import backend.database.database as db
from backend.config import SESSION_COOKIE_NAME


def get_current_user(request: Request) -> dict:
    """
    Dependency — возвращает данные текущего пользователя.
    Если сессия отсутствует или истекла — редирект на страницу входа.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/"})
    session = db.get_session_by_token(token)
    if not session:
        raise HTTPException(status_code=302, headers={"Location": "/"})
    return {
        "user_id": session["user_id"],
        "name": session["name"],
        "role": session["role"],
        "department": session["department"],
    }