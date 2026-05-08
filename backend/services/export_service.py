"""
Сервис экспорта данных в CSV.
Вся логика формирования файлов — в одном месте.
"""
import csv
import io
from datetime import datetime, timedelta

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

import backend.database.database as db
from backend.config import EXPORT_PERIOD_NAMES
from backend.utils.formatting import safe_timestamp, date_to_str


class ExportService:
    """Формирует CSV-файлы для скачивания."""

    # ── СВОДНЫЙ ОТЧЁТ ────────────────────────────────────────────────────────

    @staticmethod
    def build_summary_csv(period: str = "all") -> StreamingResponse:
        """Сводка по сотрудникам (один ряд = один сотрудник)."""
        now = datetime.now()
        period_map = {
            "month": timedelta(days=30),
            "quarter": timedelta(days=90),
            "year": timedelta(days=365),
        }
        start_date = (
            date_to_str(now - period_map[period]) if period in period_map else "2000-01-01"
        )

        all_users = db.get_all_users()
        rows = []
        for u in all_users:
            if u["role"] != "Сотрудник":
                continue
            user_reports = db.get_user_reports(u["id"])
            weighted_score = db.get_user_weighted_score(u["id"])
            burnout_data = db.get_user_burnout_trend(u["id"])
            period_reports_count = sum(
                1
                for r in user_reports
                if safe_timestamp(r["timestamp"])[:10] >= start_date
            )
            rows.append(
                {
                    "full_name": u["full_name"],
                    "department": u["department"],
                    "total_reports": len(user_reports),
                    "period_reports": period_reports_count,
                    "weighted_score": round(weighted_score),
                    "last_emotion": user_reports[0]["emotion"] if user_reports else "Нет данных",
                    "current_burnout": round(burnout_data["current"] * 100),
                    "burnout_trend": (
                        "↑" if burnout_data["trend"] > 0 else ("↓" if burnout_data["trend"] < 0 else "→")
                    ),
                }
            )

        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(
            [
                "ФИО",
                "Отдел",
                "Всего отчётов",
                f"Отчётов за {EXPORT_PERIOD_NAMES.get(period, period)}",
                "Средний балл (взвешенный)",
                "Последняя эмоция",
                "Индекс выгорания (%)",
                "Тренд выгорания",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r["full_name"],
                    r["department"],
                    r["total_reports"],
                    r["period_reports"],
                    r["weighted_score"],
                    r["last_emotion"],
                    r["current_burnout"],
                    r["burnout_trend"],
                ]
            )

        filename = f"hr_export_{period}_{now.strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(
            iter([output.getvalue().encode("utf-8-sig")]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # ── ДЕТАЛЬНЫЙ ОТЧЁТ ──────────────────────────────────────────────────────

    @staticmethod
    def build_detailed_csv(
        department: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> StreamingResponse:
        """Детальные отчёты с текстами, опциональная фильтрация по отделу и датам."""
        today = datetime.now().date()

        def _parse(s: str, label: str):
            try:
                d = datetime.strptime(s, "%Y-%m-%d").date()
                if d > today:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{label} не может быть в будущем",
                    )
                return d
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Неверный формат даты: {label}",
                )

        s_date = _parse(start_date, "Дата начала") if start_date else None
        e_date = _parse(end_date, "Дата окончания") if end_date else None
        if s_date and e_date and s_date > e_date:
            raise HTTPException(
                status_code=400,
                detail="Дата начала не может быть позже даты окончания",
            )

        if department and department != "all":
            users = db.get_users_by_department(department)
        else:
            users = [u for u in db.get_all_users() if u["role"] == "Сотрудник"]

        all_rows = []
        for user in users:
            for report in db.get_user_reports(user["id"]):
                ts = safe_timestamp(report["timestamp"])
                if start_date and ts[:10] < start_date:
                    continue
                if end_date and ts[:10] > end_date:
                    continue
                all_rows.append(
                    {
                        "date": ts[:10],
                        "time": ts[11:19],
                        "employee": user["full_name"],
                        "department": user["department"],
                        "text": report["text"],
                        "emotion": report["emotion"] or "Не определено",
                        "confidence": round(report["confidence"] * 100) if report["confidence"] else 0,
                        "burnout": round(report["burnout_index"] * 100) if report["burnout_index"] else 0,
                    }
                )

        all_rows.sort(key=lambda x: x["date"], reverse=True)

        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(
            [
                "Дата",
                "Время",
                "Сотрудник",
                "Отдел",
                "Текст отчёта",
                "Эмоция",
                "Уверенность (%)",
                "Индекс выгорания (%)",
            ]
        )
        for r in all_rows:
            text_clean = r["text"].replace("\n", " ").replace("\r", " ").replace(";", ",")
            writer.writerow(
                [
                    r["date"],
                    r["time"],
                    r["employee"],
                    r["department"],
                    text_clean,
                    r["emotion"],
                    r["confidence"],
                    r["burnout"],
                ]
            )

        filename = f"detailed_reports_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(
            iter([output.getvalue().encode("utf-8-sig")]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )