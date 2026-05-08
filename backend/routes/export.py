"""
Маршруты экспорта данных в CSV.
"""
from fastapi import APIRouter, Depends, HTTPException

from backend.routes.deps import get_current_user
from backend.services.export_service import ExportService

router = APIRouter()


@router.get("/api/export_reports")
async def api_export_reports(
    period: str = "all",
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "HR-администратор":
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    return ExportService.build_summary_csv(period)


@router.get("/api/export_detailed_reports")
async def api_export_detailed_reports(
    department: str = None,
    start_date: str = None,
    end_date: str = None,
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "HR-администратор":
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    return ExportService.build_detailed_csv(department, start_date, end_date)