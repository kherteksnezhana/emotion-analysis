"""
Pydantic-схемы для валидации данных запросов и ответов API.
"""
from pydantic import BaseModel, Field, field_validator
import re


# ─────────────────────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=5)
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=4)
    role: str
    department: str

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Логин может содержать только латинские буквы, цифры и подчёркивание")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# ОТЧЁТЫ
# ─────────────────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=20)


class AnalyzeResponse(BaseModel):
    success: bool
    emotion: str
    confidence: float
    burnout_index: float
    burnout_risk: str
    burnout_trend: str


# ─────────────────────────────────────────────────────────────────────────────
# ЭКСПОРТ
# ─────────────────────────────────────────────────────────────────────────────

class ExportSummaryRequest(BaseModel):
    period: str = "all"


class ExportDetailedRequest(BaseModel):
    department: str | None = None
    start_date: str | None = None
    end_date: str | None = None