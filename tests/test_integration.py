"""
test_integration.py — интеграционные тесты
"""

import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

def _make_session(role: str, department: str = "IT", user_id: int = 1):
    return {
        "user_id": user_id,
        "name": "Тест Пользователь",
        "role": role,
        "department": department,
    }


# ---------------------------------------------------------------------------
# Фикстура приложения
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    """Создаёт FastAPI-приложение с замоканной БД и ML-моделью."""
    with patch("psycopg_pool.ConnectionPool"), \
         patch("transformers.pipeline") as mock_pipeline:
        
        mock_clf = MagicMock()
        mock_clf.return_value = [[
            {"label": "positive", "score": 0.85},
            {"label": "neutral", "score": 0.10},
            {"label": "negative", "score": 0.05},
        ]]
        mock_pipeline.return_value = mock_clf
        
        from backend.main import app as fastapi_app
        yield fastapi_app


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ===========================================================================
# POST /api/login
# ===========================================================================

class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success_redirects(self, client):
        with patch("backend.database.database.verify_user", return_value=(1, "Тест", "Сотрудник", "IT")), \
             patch("backend.database.database.save_session", return_value=True):
            response = await client.post(
                "/api/login",
                data={"username": "test_user", "password": "test_pass"},
                follow_redirects=False,
            )
        assert response.status_code in (302, 303)
    
    @pytest.mark.asyncio
    async def test_login_wrong_credentials(self, client):
        with patch("backend.database.database.verify_user", return_value=None):
            response = await client.post(
                "/api/login",
                data={"username": "wrong", "password": "wrong"},
                follow_redirects=False,
            )
        assert response.status_code in (302, 303)
    
    @pytest.mark.asyncio
    async def test_login_empty_fields(self, client):
        response = await client.post(
            "/api/login",
            data={"username": "", "password": ""},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303, 422)


# ===========================================================================
# POST /api/analyze
# ===========================================================================

class TestAnalyze:
    @pytest.mark.asyncio
    async def test_analyze_short_text_returns_400(self, client):
        """Текст короче 20 символов → 400"""
        client.cookies.set("session_token", "test-token")
        with patch("backend.database.database.get_session_by_token", return_value={
            "user_id": 1, "name": "Тест", "role": "Сотрудник", "department": "IT"
        }):
            
            response = await client.post("/api/analyze", data={"text": "Коротко"})
        
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_analyze_valid_text_returns_200(self, client):
        """Валидный текст → 200"""
        client.cookies.set("session_token", "test-token")
        with patch("backend.database.database.get_session_by_token", return_value={
            "user_id": 1, "name": "Тест", "role": "Сотрудник", "department": "IT"
        }), \
             patch("backend.services.emotion_service.EmotionService.analyze_and_save") as mock_analyze:
            
            mock_analyze.return_value = {
                "success": True,
                "emotion": "Положительное состояние",
                "confidence": 0.85,
                "burnout_index": 0.15,
            }
            
            response = await client.post(
                "/api/analyze",
                data={"text": "Сегодня был очень продуктивный рабочий день, всё получилось отлично!"}
            )
        
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
    
    @pytest.mark.asyncio
    async def test_analyze_requires_auth(self, client):
        """Без сессии → редирект"""
        with patch("backend.routes.deps.get_current_user", side_effect=Exception("Не авторизован")):
            response = await client.post(
                "/api/analyze",
                data={"text": "Тестовый текст для анализа"},
                follow_redirects=False,
            )
        assert response.status_code in (302, 303)


# ===========================================================================
# GET /api/team_analytics
# ===========================================================================

class TestTeamAnalytics:
    @pytest.mark.asyncio
    async def test_manager_can_access(self, client):
        """Руководитель → 200"""
        client.cookies.set("session_token", "test-token")
        with patch("backend.database.database.get_session_by_token", return_value={
            "user_id": 2, "name": "Руководитель", "role": "Руководитель", "department": "IT"
        }), \
             patch("backend.database.database.get_all_team_reports", return_value=[]):
            
            response = await client.get("/api/team_analytics?period=month")
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_employee_cannot_access(self, client):
        """Сотрудник → 403"""
        client.cookies.set("session_token", "test-token")
        with patch("backend.database.database.get_session_by_token", return_value={
            "user_id": 1, "name": "Сотрудник", "role": "Сотрудник", "department": "IT"
        }):
            
            response = await client.get("/api/team_analytics?period=month")
        
        assert response.status_code == 403
    
    @pytest.mark.asyncio
    async def test_hr_cannot_access(self, client):
        """HR → 403"""
        client.cookies.set("session_token", "test-token")
        with patch("backend.database.database.get_session_by_token", return_value={
            "user_id": 3, "name": "HR", "role": "HR-администратор", "department": "HR"
        }):
            
            response = await client.get("/api/team_analytics?period=all")
        
        assert response.status_code == 403