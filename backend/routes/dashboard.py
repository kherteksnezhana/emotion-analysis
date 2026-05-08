"""
Маршрут /dashboard — роутинг по роли пользователя.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from backend.config import TEMPLATES_DIR
from backend.routes.deps import get_current_user
from backend.services.context_builders import (
    EmployeeContextBuilder,
    ManagerContextBuilder,
    HRContextBuilder,
)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

_ROLE_TEMPLATE = {
    "Сотрудник": "employee.html",
    "Руководитель": "manager.html",
    "HR-администратор": "hr.html",
}


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    user = {
        "id": current_user["user_id"],
        "full_name": current_user["name"],
        "role": current_user["role"],
        "department": current_user["department"],
    }

    role = user["role"]
    template_name = _ROLE_TEMPLATE.get(role, "employee.html")

    if role == "Сотрудник":
        extra = EmployeeContextBuilder.build(user["id"])
    elif role == "Руководитель":
        extra = ManagerContextBuilder.build(user)
    elif role == "HR-администратор":
        extra = HRContextBuilder.build()
    else:
        extra = EmployeeContextBuilder.build(user["id"])

    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={"user": user, **extra},
    )