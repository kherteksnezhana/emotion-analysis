"""
test_functional.py — функциональные (API) тесты

Проверяемые эндпоинты:
  • POST /api/register
  • POST /api/logout
  • GET  /dashboard
  • GET  /api/export_reports
  • GET  /api/export_detailed_reports
"""

import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Фикстура приложения (с заглушками тяжёлых зависимостей)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    # Патчим psycopg_pool вместо psycopg2
    with patch("psycopg_pool.ConnectionPool"), \
         patch("transformers.pipeline") as mock_pipeline:
        mock_clf = MagicMock()
        mock_clf.return_value = [[
            {"label": "positive", "score": 0.80},
            {"label": "neutral",  "score": 0.15},
            {"label": "negative", "score": 0.05},
        ]]
        mock_pipeline.return_value = mock_clf
        from backend.main import app as fastapi_app
        yield fastapi_app


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client_employee(app):
    """Клиент с активной сессией Сотрудника."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.cookies.set("session_token", "employee-session-token")
        yield ac


@pytest_asyncio.fixture
async def auth_client_hr(app):
    """Клиент с активной сессией HR-администратора."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.cookies.set("session_token", "hr-session-token")
        yield ac


# ===========================================================================
# POST /api/register
# ===========================================================================

class TestRegister:

    VALID_DATA = {
        "full_name": "Иванов Иван Иванович",
        "username": "ivanov_test",
        "password": "pass123",
        "role": "Сотрудник",
        "department": "IT",
    }

    @pytest.mark.asyncio
    async def test_register_success_redirects(self, client):
        """Успешная регистрация → редирект на /?registered=success."""
        with patch("backend.database.database.add_user", return_value=42):
            response = await client.post(
                "/api/register",
                data=self.VALID_DATA,
                follow_redirects=False,
            )
        assert response.status_code in (302, 303)
        location = response.headers.get("location", "")
        assert "registered=success" in location, \
            f"Ожидался registered=success в редиректе, получено: {location}"

    @pytest.mark.asyncio
    async def test_register_duplicate_user(self, client):
        """Дублирующийся логин → возврат страницы с error=exists."""
        with patch("backend.database.database.add_user", return_value=None):
            response = await client.post(
                "/api/register",
                data=self.VALID_DATA,
                follow_redirects=True,
            )
        assert response.status_code == 200
        text = response.text
        assert "exists" in text or "уже существует" in text or "error" in text.lower()

    @pytest.mark.asyncio
    async def test_register_short_password(self, client):
        """Пароль < 4 символов → ошибка валидации."""
        data = {**self.VALID_DATA, "password": "ab", "username": "user_short_pw"}
        response = await client.post(
            "/api/register",
            data=data,
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "short_password" in response.text or "4" in response.text

    @pytest.mark.asyncio
    async def test_register_invalid_username_chars(self, client):
        """Логин с кириллицей → ошибка валидации."""
        data = {**self.VALID_DATA, "username": "пользователь"}
        response = await client.post(
            "/api/register",
            data=data,
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "invalid_username" in response.text or "латин" in response.text

    @pytest.mark.asyncio
    async def test_register_short_fullname(self, client):
        """ФИО < 5 символов → ошибка invalid_name."""
        data = {**self.VALID_DATA, "full_name": "Ив", "username": "iv_short"}
        response = await client.post(
            "/api/register",
            data=data,
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "invalid_name" in response.text or "корректное" in response.text

    @pytest.mark.asyncio
    async def test_register_page_get(self, client):
        """GET /register должен возвращать страницу регистрации."""
        response = await client.get("/register")
        assert response.status_code == 200
        assert "Регистрация" in response.text or "register" in response.text.lower()

    @pytest.mark.asyncio
    async def test_register_all_roles(self, client):
        """Регистрация с разными ролями не должна ломаться."""
        roles = ["Сотрудник", "Руководитель", "HR-администратор"]
        for i, role in enumerate(roles):
            data = {
                "full_name": f"Тест Тестов Тестович",
                "username": f"test_role_{i}",
                "password": "testpass",
                "role": role,
                "department": "IT",
            }
            with patch("backend.database.database.add_user", return_value=100 + i):
                response = await client.post(
                    "/api/register",
                    data=data,
                    follow_redirects=False,
                )
            assert response.status_code in (302, 303), \
                f"Роль '{role}' вернула {response.status_code}"


# ===========================================================================
# POST /api/logout
# ===========================================================================

class TestLogout:

    @pytest.mark.asyncio
    async def test_logout_redirects_to_login(self, auth_client_employee):
        """Выход должен редиректить на страницу входа и удалять cookie."""
        with patch("backend.database.database.get_session_by_token", return_value={
            "user_id": 1, "name": "Test", "role": "Сотрудник", "department": "IT"
        }), patch("backend.database.database.delete_session", return_value=True):
            response = await auth_client_employee.post(
                "/api/logout",
                follow_redirects=False,
            )

        assert response.status_code in (302, 303)
        location = response.headers.get("location", "")
        assert location == "/" or "/login" in location or location.endswith("/"), \
            f"Ожидался редирект на /, получено: {location}"

    @pytest.mark.asyncio
    async def test_logout_clears_cookie(self, auth_client_employee):
        """После logout cookie session_token должен быть удалён."""
        with patch("backend.database.database.get_session_by_token", return_value=None), \
             patch("backend.database.database.delete_session", return_value=True):
            response = await auth_client_employee.post(
                "/api/logout",
                follow_redirects=False,
            )

        # Проверяем Set-Cookie заголовок на удаление куки
        set_cookie = response.headers.get("set-cookie", "")
        # Либо куки нет в ответе клиента, либо он выставлен пустым/истёкшим
        assert (
            "session_token" not in auth_client_employee.cookies
            or "session_token=" in set_cookie
        )

    @pytest.mark.asyncio
    async def test_logout_without_session(self, client):
        """Выход без активной сессии не должен ломать сервер (нет 500)."""
        with patch("backend.database.database.delete_session", return_value=True):
            response = await client.post(
                "/api/logout",
                follow_redirects=False,
            )
        assert response.status_code not in (500,)


# ===========================================================================
# GET /dashboard
# ===========================================================================

class TestDashboard:

    def _employee_context(self):
        return {
            "reports": [],
            "avg_score": 75,
            "score_trend": None,
            "current_emotion": "Положительное состояние",
            "burnout_current": 0.15,
            "burnout_trend": 0.0,
            "burnout_trend_percent": 0,
        }

    def _manager_context(self):
        return {
            "team": [],
            "all_reports": [],
            "avg_score": 70,
            "chart_labels": [],
            "chart_data": [],
            "dist_data": [0, 0, 0],
            "stats_excellent": 0,
            "stats_good": 0,
            "stats_warning": 0,
            "stats_excellent_percent": 0,
            "stats_good_percent": 0,
            "stats_warning_percent": 0,
            "team_attention_count": 0,
            "top_keywords": [],
            "total_employees": 0,
            "reported_today": 0,
            "not_reported_today": 0,
            "reports_percentage": 0,
            "team_burnout": [],
            "team_high_burnout": [],
        }

    def _hr_context(self):
        return {
            "total_employees": 10,
            "total_reports": 50,
            "current_month_ru": "Январь",
            "need_attention_count": 2,
            "high_morale_count": 5,
            "employees_data": [],
            "departments": ["IT", "Маркетинг"],
            "emotion_stats": [],
            "dept_avg_scores": [],
            "avg_company_score": 72,
            "dept_reports_stats": [],
            "company_burnout_history": [],
            "departments_burnout_history": {},
            "company_burnout_avg": 0.25,
            "high_burnout_employees": [],
            "period_comparison": None,
            "team_attention_count": 2,
        }

    @pytest.mark.asyncio
    async def test_dashboard_employee(self, client):
        """Сотрудник видит свою страницу дашборда."""
        session_data = {
            "user_id": 1, "name": "Тест Сотрудник",
            "role": "Сотрудник", "department": "IT"
        }
        client.cookies.set("session_token", "emp-dash-token")

        with patch("backend.database.database.get_session_by_token", return_value=session_data), \
             patch("backend.services.context_builders.EmployeeContextBuilder.build",
                   return_value=self._employee_context()):
            response = await client.get("/dashboard")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dashboard_manager(self, client):
        """Руководитель видит дашборд команды."""
        session_data = {
            "user_id": 2, "name": "Тест Руководитель",
            "role": "Руководитель", "department": "IT"
        }
        client.cookies.set("session_token", "manager-session-token")

        with patch("backend.database.database.get_session_by_token", return_value=session_data), \
             patch("backend.services.context_builders.ManagerContextBuilder.build",
                   return_value=self._manager_context()):
            response = await client.get("/dashboard")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dashboard_hr(self, client):
        """HR-администратор видит дашборд компании."""
        session_data = {
            "user_id": 3, "name": "Тест HR",
            "role": "HR-администратор", "department": "HR"
        }
        client.cookies.set("session_token", "hr-session-token")

        with patch("backend.database.database.get_session_by_token", return_value=session_data), \
             patch("backend.services.context_builders.HRContextBuilder.build",
                   return_value=self._hr_context()):
            response = await client.get("/dashboard")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dashboard_no_auth_redirect(self, client):
        """Без авторизации → редирект на страницу входа."""
        client.cookies.clear()
        with patch("backend.database.database.get_session_by_token", return_value=None):
            response = await client.get("/dashboard", follow_redirects=False)

        assert response.status_code in (302, 303, 401), \
            f"Ожидался редирект/401, получен {response.status_code}"


# ===========================================================================
# GET /api/export_reports
# ===========================================================================

class TestExportReports:

    @pytest.mark.asyncio
    async def test_export_reports_hr_success(self, auth_client_hr):
        """HR получает CSV-файл со сводкой."""
        hr_session = {
            "user_id": 3, "name": "HR Admin",
            "role": "HR-администратор", "department": "HR"
        }

        mock_streaming = MagicMock()
        mock_streaming.status_code = 200
        # Нам нужна реальная StreamingResponse — мокаем сервисный метод
        import io
        from fastapi.responses import StreamingResponse as SR
        csv_content = "ФИО;Отдел;Всего отчётов\nИванов Иван;IT;5\n"

        with patch("backend.database.database.get_session_by_token", return_value=hr_session), \
             patch("backend.services.export_service.ExportService.build_summary_csv") as mock_csv:
            mock_csv.return_value = SR(
                iter([csv_content.encode("utf-8-sig")]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=test.csv"},
            )
            response = await auth_client_hr.get("/api/export_reports?period=all")

        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_export_reports_employee_forbidden(self, auth_client_employee):
        """Сотрудник не может экспортировать → 403."""
        employee_session = {
            "user_id": 1, "name": "Сотрудник",
            "role": "Сотрудник", "department": "IT"
        }
        with patch("backend.database.database.get_session_by_token", return_value=employee_session):
            response = await auth_client_employee.get("/api/export_reports")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_export_reports_period_param(self, auth_client_hr):
        """Разные значения period передаются корректно."""
        hr_session = {
            "user_id": 3, "name": "HR",
            "role": "HR-администратор", "department": "HR"
        }
        from fastapi.responses import StreamingResponse as SR

        for period in ("all", "month", "quarter", "year"):
            with patch("backend.database.database.get_session_by_token", return_value=hr_session), \
                 patch("backend.services.export_service.ExportService.build_summary_csv") as mock_csv:
                mock_csv.return_value = SR(
                    iter([b"col1;col2\n"]),
                    media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=t.csv"},
                )
                response = await auth_client_hr.get(f"/api/export_reports?period={period}")

            assert response.status_code == 200, f"period='{period}' вернул {response.status_code}"
            # Проверяем, что сервис вызван с правильным period
            mock_csv.assert_called_once_with(period)


# ===========================================================================
# GET /api/export_detailed_reports
# ===========================================================================

class TestExportDetailedReports:

    @pytest.mark.asyncio
    async def test_detailed_export_hr_success(self, auth_client_hr):
        """HR получает детальный CSV-файл."""
        hr_session = {
            "user_id": 3, "name": "HR",
            "role": "HR-администратор", "department": "HR"
        }
        from fastapi.responses import StreamingResponse as SR
        csv_content = "Дата;Сотрудник;Текст\n2024-01-15;Иванов;Хороший день\n"

        with patch("backend.database.database.get_session_by_token", return_value=hr_session), \
             patch("backend.services.export_service.ExportService.build_detailed_csv") as mock_csv:
            mock_csv.return_value = SR(
                iter([csv_content.encode("utf-8-sig")]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=detailed.csv"},
            )
            response = await auth_client_hr.get(
                "/api/export_detailed_reports?start_date=2024-01-01&end_date=2024-01-31"
            )

        assert response.status_code == 200
        assert "csv" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_detailed_export_with_department_filter(self, auth_client_hr):
        """Фильтр по отделу передаётся в сервис."""
        hr_session = {
            "user_id": 3, "name": "HR",
            "role": "HR-администратор", "department": "HR"
        }
        from fastapi.responses import StreamingResponse as SR

        with patch("backend.database.database.get_session_by_token", return_value=hr_session), \
             patch("backend.services.export_service.ExportService.build_detailed_csv") as mock_csv:
            mock_csv.return_value = SR(
                iter([b"header\n"]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=t.csv"},
            )
            response = await auth_client_hr.get(
                "/api/export_detailed_reports?department=IT&start_date=2024-01-01&end_date=2024-12-31"
            )

        assert response.status_code == 200
        mock_csv.assert_called_once_with("IT", "2024-01-01", "2024-12-31")

    @pytest.mark.asyncio
    async def test_detailed_export_employee_forbidden(self, auth_client_employee):
        """Сотрудник → 403."""
        employee_session = {
            "user_id": 1, "name": "Employee",
            "role": "Сотрудник", "department": "IT"
        }
        with patch("backend.database.database.get_session_by_token", return_value=employee_session):
            response = await auth_client_employee.get(
                "/api/export_detailed_reports"
            )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_detailed_export_no_filters(self, auth_client_hr):
        """Экспорт без фильтров — None передаётся в сервис."""
        hr_session = {
            "user_id": 3, "name": "HR",
            "role": "HR-администратор", "department": "HR"
        }
        from fastapi.responses import StreamingResponse as SR

        with patch("backend.database.database.get_session_by_token", return_value=hr_session), \
             patch("backend.services.export_service.ExportService.build_detailed_csv") as mock_csv:
            mock_csv.return_value = SR(
                iter([b"header\n"]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=t.csv"},
            )
            response = await auth_client_hr.get("/api/export_detailed_reports")

        assert response.status_code == 200
        mock_csv.assert_called_once_with(None, None, None)