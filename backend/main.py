"""
Точка входа FastAPI-приложения.
Здесь только инициализация — никакой бизнес-логики.

Структура проекта:
    backend/
    ├── config.py              ← константы и переменные окружения
    ├── main.py                ← этот файл: точка входа
    ├── database/
    │   └── database.py        ← слой доступа к данным (DAL)
    ├── model/
    │   ├── emotion_model.py   ← ML-модель RuBERT
    │   └── text_preprocessor.py
    ├── routes/
    │   ├── auth.py            ← login / logout / register
    │   ├── dashboard.py       ← /dashboard с роутингом по ролям
    │   ├── api.py             ← /api/analyze, /api/team_analytics
    │   ├── export.py          ← /api/export_*
    │   └── deps.py            ← FastAPI dependency: get_current_user
    ├── services/
    │   ├── emotion_service.py    ← бизнес-логика анализа эмоций
    │   ├── export_service.py     ← формирование CSV
    │   └── context_builders.py  ← построение контекста для шаблонов
    ├── schemas/
    │   └── __init__.py        ← Pydantic-модели для валидации
    └── utils/
        ├── formatting.py      ← форматирование дат, timestamp
        └── keywords.py        ← извлечение ключевых слов
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.config import STATIC_DIR
import backend.database.database as db
from backend.routes import auth_router, dashboard_router, api_router, export_router

app = FastAPI(title="Emotion Analysis System")

# Статика
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Инициализация БД при старте
db.init_db()

# Подключение роутеров
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(api_router)
app.include_router(export_router)