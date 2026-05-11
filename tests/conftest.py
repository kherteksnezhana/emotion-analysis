"""
conftest.py — общие pytest-фикстуры для всего тест-сьюта.
"""
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Мок базы данных — подменяем psycopg3 ДО импорта приложения
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def mock_db_pool():
    """Подменяет psycopg_pool.ConnectionPool на уровне модуля database.py."""
    with patch("psycopg_pool.ConnectionPool") as mock_pool_cls:
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        
        mock_connection_context = MagicMock()
        mock_connection_context.__enter__.return_value = mock_conn
        mock_pool.connection.return_value = mock_connection_context

        yield mock_pool


# ---------------------------------------------------------------------------
# Мок сессии — ДЛЯ АВТОРИЗАЦИИ В ТЕСТАХ
# ---------------------------------------------------------------------------

# Сохраняем сессии для разных ролей
MOCK_SESSIONS = {
    "employee-session-token": {
        "user_id": 1,
        "name": "Тест Сотрудник",
        "role": "Сотрудник",
        "department": "IT",
    },
    "manager-session-token": {
        "user_id": 2,
        "name": "Тест Руководитель",
        "role": "Руководитель",
        "department": "IT",
    },
    "hr-session-token": {
        "user_id": 3,
        "name": "Тест HR",
        "role": "HR-администратор",
        "department": "HR",
    },
}


# ---------------------------------------------------------------------------
# Фикстуры клиентов с авторизацией
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    """Создаёт FastAPI-приложение с замоканной БД и ML-моделью."""
    with patch("psycopg_pool.ConnectionPool"), \
         patch("transformers.pipeline") as mock_pipeline:
        
        mock_clf = MagicMock()
        mock_clf.return_value = [[
            {"label": "positive", "score": 0.80},
            {"label": "neutral", "score": 0.15},
            {"label": "negative", "score": 0.05},
        ]]
        mock_pipeline.return_value = mock_clf
        
        from backend.main import app as fastapi_app
        yield fastapi_app


@pytest_asyncio.fixture
async def client(app):
    """Обычный клиент без авторизации."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client_employee(app):
    """Клиент с активной сессией Сотрудника."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.cookies.set("session_token", "employee-session-token")
        
        # Мокаем получение сессии из БД
        with patch("backend.database.database.get_session_by_token") as mock_get_session:
            mock_get_session.return_value = MOCK_SESSIONS["employee-session-token"]
            
            # Также мокаем verify_user для логина, если нужно
            with patch("backend.database.database.verify_user") as mock_verify:
                mock_verify.return_value = (1, "Тест Сотрудник", "Сотрудник", "IT")
                
                yield ac


@pytest_asyncio.fixture
async def auth_client_manager(app):
    """Клиент с активной сессией Руководителя."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.cookies.set("session_token", "manager-session-token")
        
        with patch("backend.database.database.get_session_by_token") as mock_get_session:
            mock_get_session.return_value = MOCK_SESSIONS["manager-session-token"]
            yield ac


@pytest_asyncio.fixture
async def auth_client_hr(app):
    """Клиент с активной сессией HR-администратора."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.cookies.set("session_token", "hr-session-token")
        
        with patch("backend.database.database.get_session_by_token") as mock_get_session:
            mock_get_session.return_value = MOCK_SESSIONS["hr-session-token"]
            yield ac


# ---------------------------------------------------------------------------
# Тестовый пользователь-данные
# ---------------------------------------------------------------------------

EMPLOYEE_USER = {
    "user_id": 1,
    "name": "Тест Сотрудник",
    "role": "Сотрудник",
    "department": "IT",
}

MANAGER_USER = {
    "user_id": 2,
    "name": "Тест Руководитель",
    "role": "Руководитель",
    "department": "IT",
}

HR_USER = {
    "user_id": 3,
    "name": "Тест HR",
    "role": "HR-администратор",
    "department": "HR",
}


@pytest.fixture
def employee_session():
    return EMPLOYEE_USER.copy()


@pytest.fixture
def manager_session():
    return MANAGER_USER.copy()


@pytest.fixture
def hr_session():
    return HR_USER.copy()