"""
API-маршруты: анализ эмоций, аналитика команды для руководителя.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse

import backend.database.database as db
from backend.routes.deps import get_current_user
from backend.services.emotion_service import EmotionService
from backend.utils.formatting import safe_timestamp, format_date_short

router = APIRouter()


@router.post("/api/analyze")
async def api_analyze(
    text: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    result = EmotionService.analyze_and_save(current_user["user_id"], text)
    return JSONResponse(result)


@router.get("/api/team_analytics")
async def api_team_analytics(
    period: str = "all",
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "Руководитель":
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    department = current_user["department"]
    all_team_reports = db.get_all_team_reports(department)

    if not all_team_reports:
        return JSONResponse({"labels": [], "values": []})

    now = datetime.now()
    period_map = {
        "week": timedelta(days=7),
        "month": timedelta(days=30),
        "quarter": timedelta(days=90),
        "year": timedelta(days=365),
    }
    start_date = (
        (now - period_map[period]).strftime("%Y-%m-%d")
        if period in period_map
        else "2000-01-01"
    )

    for r in all_team_reports:
        r["timestamp"] = safe_timestamp(r["timestamp"])

    filtered = [r for r in all_team_reports if r["timestamp"][:10] >= start_date]
    if not filtered:
        return JSONResponse({"labels": [], "values": []})

    daily: dict = defaultdict(lambda: defaultdict(list))
    for r in filtered:
        daily[r["timestamp"][:10]][r["user_id"]].append(
            {"confidence": r["confidence"], "timestamp": r["timestamp"]}
        )

    date_scores: dict = {}
    for date, users in daily.items():
        user_scores = []
        for uid, rlist in users.items():
            rlist_sorted = sorted(rlist, key=lambda x: x["timestamp"])
            user_scores.append(db.calculate_weighted_score_for_list(rlist_sorted) * 100)
        if user_scores:
            date_scores[date] = sum(user_scores) / len(user_scores)

    sorted_dates = sorted(date_scores.keys())
    labels = [format_date_short(d) for d in sorted_dates]
    values = [round(date_scores[d]) for d in sorted_dates]

    return JSONResponse({"labels": labels, "values": values, "period": period})