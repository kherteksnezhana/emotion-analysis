"""
Построители контекста для Jinja2-шаблонов.
Каждая роль — отдельный метод, изолированная логика.
"""
from collections import defaultdict
from datetime import datetime

import backend.database.database as db
from backend.config import MONTHS_FULL_RU
from backend.utils.formatting import safe_timestamp, format_date_short
from backend.utils.keywords import extract_keywords


class EmployeeContextBuilder:
    """Контекст для страницы сотрудника."""

    @staticmethod
    def build(user_id: int) -> dict:
        reports = db.get_user_reports(user_id)

        for r in reports:
            r["timestamp"] = safe_timestamp(r["timestamp"])
            r["keywords"] = extract_keywords(r["text"], max_count=3)

        avg_score = int(db.get_user_weighted_wellbeing(user_id))
        current_emotion = reports[0]["emotion"] if reports else None
        score_trend = db.get_user_score_trend(user_id)
        burnout_data = db.get_user_burnout_trend(user_id)
        burnout_change = burnout_data["trend"] * 100

        return {
            "reports": reports,
            "avg_score": avg_score,
            "score_trend": score_trend,
            "current_emotion": current_emotion,
            "burnout_current": burnout_data["current"],
            "burnout_trend": burnout_data["trend"],
            "burnout_trend_percent": round(burnout_change),
        }


class ManagerContextBuilder:
    """Контекст для страницы руководителя."""

    @staticmethod
    def build(user: dict) -> dict:
        department = user["department"]
        team_members = db.get_team_with_reports(department)
        all_team_reports = db.get_all_team_reports(department)

        today_str = datetime.now().strftime("%Y-%m-%d")
        reports_for_js: list = []
        employees_who_reported_today: set = set()

        for report in all_team_reports:
            ts = safe_timestamp(report["timestamp"])
            report["timestamp"] = ts
            report["keywords"] = extract_keywords(report["text"], max_count=5)

            if ts[:10] == today_str:
                employees_who_reported_today.add(report["user_id"])

            # Во фронтенд — только метаданные, без текста (конфиденциальность)
            reports_for_js.append(
                {
                    "user_id": report["user_id"],
                    "timestamp": ts,
                    "emotion": report["emotion"],
                    "confidence": report["confidence"],
                    "burnout_index": report["burnout_index"],
                    "keywords": report["keywords"],
                }
            )

        # Данные по каждому сотруднику
        for member in team_members:
            member["timestamp"] = safe_timestamp(member.get("last_report_date"))
            if member["has_reports"]:
                member["weighted_score"] = int(db.get_user_weighted_score(member["id"]))
                trend = db.get_user_score_trend(member["id"])
                member["score_trend"] = trend if trend and abs(trend["change"]) > 1 else None
            else:
                member["weighted_score"] = None
                member["score_trend"] = None

        # Средний балл по команде
        scored = [m["weighted_score"] for m in team_members if m["weighted_score"] is not None]
        avg_score = int(sum(scored) / len(scored)) if scored else 0

        # График динамики (взвешенный)
        daily_user_reports: dict = defaultdict(lambda: defaultdict(list))
        for report in all_team_reports:
            date = report["timestamp"][:10]
            daily_user_reports[date][report["user_id"]].append(
                {"confidence": report["confidence"], "timestamp": report["timestamp"]}
            )

        date_weighted_scores: dict = {}
        for date, users in daily_user_reports.items():
            user_scores = []
            for uid, rlist in users.items():
                rlist_sorted = sorted(rlist, key=lambda x: x["timestamp"])
                user_scores.append(db.calculate_weighted_score_for_list(rlist_sorted) * 100)
            if user_scores:
                date_weighted_scores[date] = sum(user_scores) / len(user_scores)

        sorted_dates = sorted(date_weighted_scores.keys())[-14:]
        chart_labels = [format_date_short(d) for d in sorted_dates]
        chart_data = [round(date_weighted_scores[d]) for d in sorted_dates]

        # Распределение по уровням
        last_scores = [m["weighted_score"] for m in team_members if m["weighted_score"] is not None]
        stats_excellent = sum(1 for s in last_scores if s >= 80)
        stats_good = sum(1 for s in last_scores if 60 <= s < 80)
        stats_warning = sum(1 for s in last_scores if s < 60)
        total_team = len(last_scores) or 1

        # Топ ключевые слова
        word_counts: dict = {}
        for report in all_team_reports:
            for word in extract_keywords(report["text"], max_count=100, max_length=50):
                word_counts[word] = word_counts.get(word, 0) + 1
        top_keywords = sorted(
            [{"word": w, "count": c} for w, c in word_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:8]

        total_employees = len(team_members)
        reported_today = len(employees_who_reported_today)
        not_reported_today = total_employees - reported_today
        reports_percentage = int((reported_today / total_employees) * 100) if total_employees else 0

        # Burnout по команде
        team_burnout = [
            {
                "user_id": member["id"],
                "name": member["full_name"],
                "burnout": db.get_user_burnout_trend(member["id"])["current"],
            }
            for member in team_members
        ]

        team_attention_count = sum(
            1
            for m in team_members
            if m.get("last_score") is not None and m["last_score"] < 60
        )

        return {
            "team": team_members,
            "all_reports": reports_for_js,
            "avg_score": avg_score,
            "chart_labels": chart_labels,
            "chart_data": chart_data,
            "dist_data": [stats_excellent, stats_good, stats_warning],
            "stats_excellent": stats_excellent,
            "stats_good": stats_good,
            "stats_warning": stats_warning,
            "stats_excellent_percent": round(stats_excellent / total_team * 100),
            "stats_good_percent": round(stats_good / total_team * 100),
            "stats_warning_percent": round(stats_warning / total_team * 100),
            "team_attention_count": team_attention_count,
            "top_keywords": top_keywords,
            "total_employees": total_employees,
            "reported_today": reported_today,
            "not_reported_today": not_reported_today,
            "reports_percentage": reports_percentage,
            "team_burnout": team_burnout,
            "team_high_burnout": [m for m in team_burnout if m["burnout"] > 0.5],
        }


class HRContextBuilder:
    """Контекст для страницы HR-администратора."""

    @staticmethod
    def build() -> dict:
        all_users = db.get_all_users()
        now = datetime.now()
        current_month_ru = MONTHS_FULL_RU[now.month]

        employees_data: list = []
        need_attention = 0
        high_morale = 0
        emotion_counter: dict = {}

        for u in all_users:
            if u["role"] != "Сотрудник" or u["department"] == "HR":
                continue

            user_reports = db.get_user_reports(u["id"])
            report_count = len(user_reports)
            weighted_score = db.get_user_weighted_score(u["id"])
            last_score = int(weighted_score) if user_reports else None
            score_trend = db.get_user_score_trend(u["id"])
            last_burnout = user_reports[0]["burnout_index"] if user_reports else 0

            if user_reports:
                last_emotion = user_reports[0]["emotion"]
                if last_score is not None and last_score < 60:
                    need_attention += 1
                if last_score is not None and last_score >= 80:
                    high_morale += 1
            else:
                last_emotion = "Нет данных"

            for report in user_reports:
                emotion = report.get("emotion")
                if emotion:
                    emotion_counter[emotion] = emotion_counter.get(emotion, 0) + 1

            employees_data.append(
                {
                    "id": u["id"],
                    "full_name": u["full_name"],
                    "role": u["role"],
                    "department": u["department"],
                    "last_score": last_score,
                    "last_emotion": last_emotion,
                    "report_count": report_count,
                    "score_trend": score_trend,
                    "last_burnout": last_burnout,
                    "has_reports": report_count > 0,
                }
            )

        departments = sorted(
            set(u["department"] for u in all_users if u["department"] and u["department"] != "HR")
        )

        emotion_stats = sorted(
            [{"label": k, "count": v} for k, v in emotion_counter.items()],
            key=lambda x: x["count"],
            reverse=True,
        )

        dept_weighted: dict = defaultdict(list)
        for emp in employees_data:
            if emp["has_reports"] and emp["last_score"] is not None:
                dept_weighted[emp["department"]].append(emp["last_score"])

        dept_avg_scores = sorted(
            [
                {"name": dept, "score": int(sum(scores) / len(scores))}
                for dept, scores in dept_weighted.items()
            ],
            key=lambda x: x["score"],
            reverse=True,
        )

        employees_with_scores = [
            e for e in employees_data if e["has_reports"] and e["last_score"] is not None
        ]
        avg_company_score = (
            int(sum(e["last_score"] for e in employees_with_scores) / len(employees_with_scores))
            if employees_with_scores
            else 0
        )

        company_burnout_history = db.get_company_burnout_history(days=30)
        departments_burnout_history = db.get_departments_burnout_history(days=30)
        company_burnout_avg = company_burnout_history[-1]["burnout"] if company_burnout_history else 0

        burnout_stats = db.get_company_burnout_stats()
        high_burnout_employees = burnout_stats["high_burnout_employees"]
        period_comparison = db.get_period_comparison()
        dept_reports_stats = db.get_department_reports_stats()

        return {
            "total_employees": len(employees_data),
            "total_reports": sum(e["report_count"] for e in employees_data),
            "current_month_ru": current_month_ru,
            "need_attention_count": need_attention,
            "high_morale_count": high_morale,
            "employees_data": employees_data,
            "departments": departments,
            "emotion_stats": emotion_stats,
            "dept_avg_scores": dept_avg_scores,
            "avg_company_score": avg_company_score,
            "dept_reports_stats": dept_reports_stats,
            "company_burnout_history": company_burnout_history,
            "departments_burnout_history": departments_burnout_history,
            "company_burnout_avg": company_burnout_avg,
            "high_burnout_employees": high_burnout_employees,
            "period_comparison": period_comparison,
            "team_attention_count": need_attention,
        }