import sys
import os
import csv
import io
import secrets
import re
import calendar
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model.text_preprocessor import RUSSIAN_STOP_WORDS, clean_text
from model.emotion_model import analyze_emotion
import database.database as db

load_dotenv()

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MONTHS_SHORT = {
    1: 'янв', 2: 'фев', 3: 'мар', 4: 'апр', 5: 'май', 6: 'июн',
    7: 'июл', 8: 'авг', 9: 'сен', 10: 'окт', 11: 'ноя', 12: 'дек'
}
MONTHS_FULL_RU = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
    5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
    9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
}

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

db.init_db()


# ─────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────

def extract_keywords(text: str, max_count: int = 3, max_length: int = 20) -> list:
    """Извлекает ключевые слова из текста, исключая стоп-слова."""
    if not text:
        return []
    cleaned = clean_text(
        text,
        lowercase=True,
        remove_punctuation=True,
        replace_numbers=False,
        remove_stopwords=False,
        strip_extra_spaces=True
    )
    keywords = []
    for word in cleaned.split():
        if (len(word) > 3
                and word not in RUSSIAN_STOP_WORDS
                and word not in keywords
                and len(keywords) < max_count):
            keywords.append(word[:max_length])
    return keywords


def format_date(date_str: str) -> str:
    """Форматирует дату ISO → «15 янв»."""
    try:
        dt = datetime.strptime(date_str[:10], '%Y-%m-%d')
        return f"{dt.day} {MONTHS_SHORT[dt.month]}"
    except (ValueError, IndexError):
        return date_str[:10]


def safe_timestamp(ts) -> str:
    """Гарантирует строковое представление timestamp."""
    if isinstance(ts, datetime):
        return ts.strftime('%Y-%m-%d %H:%M:%S')
    return str(ts) if ts else ''


def get_current_user(request: Request):
    """Dependency: возвращает текущего пользователя или редиректит на /."""
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/"})
    session = db.get_session_by_token(token)
    if not session:
        raise HTTPException(status_code=302, headers={"Location": "/"})
    return {
        "user_id": session["user_id"],
        "name": session["name"],
        "role": session["role"],
        "department": session["department"],
    }


# ─────────────────────────────────────────────
# СТРАНИЦЫ
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None, registered: str = None):
    return templates.TemplateResponse(
        request=request, name="login.html",
        context={"error": error, "registered": registered}
    )


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="register.html", context={"form_data": {}}
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: dict = Depends(get_current_user)):
    user = {
        "id": current_user["user_id"],
        "full_name": current_user["name"],
        "role": current_user["role"],
        "department": current_user["department"],
    }
    context = {"user": user}

    role = user["role"]

    if role == "Сотрудник":
        context.update(_build_employee_context(user["id"]))
        template_name = "employee.html"

    elif role == "Руководитель":
        context.update(_build_manager_context(user))
        template_name = "manager.html"

    elif role == "HR-администратор":
        context.update(_build_hr_context())
        template_name = "hr.html"

    else:
        template_name = "employee.html"

    return templates.TemplateResponse(request=request, name=template_name, context=context)


# ─────────────────────────────────────────────
# ПОСТРОИТЕЛИ КОНТЕКСТА (выделены из dashboard)
# ─────────────────────────────────────────────

def _build_employee_context(user_id: int) -> dict:
    reports = db.get_user_reports(user_id)

    # Конвертируем timestamp в строку для шаблона
    for r in reports:
        r['timestamp'] = safe_timestamp(r['timestamp'])
        r['keywords'] = extract_keywords(r['text'], max_count=3)

    avg_score = int(db.get_user_weighted_wellbeing(user_id))

    if reports:
        current_emotion = reports[0]['emotion']
    else:
        current_emotion = None

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


def _build_manager_context(user: dict) -> dict:
    department = user["department"]
    team_members = db.get_team_with_reports(department)
    all_team_reports = db.get_all_team_reports(department)

    today_str = datetime.now().strftime('%Y-%m-%d')

    # Конвертируем timestamp и добавляем ключевые слова
    # Для менеджера НЕ передаём тексты отчётов во фронтенд (конфиденциальность)
    reports_for_js = []
    employees_who_reported_today = set()

    for report in all_team_reports:
        ts = safe_timestamp(report['timestamp'])
        report['timestamp'] = ts
        report['keywords'] = extract_keywords(report['text'], max_count=5)

        if ts[:10] == today_str:
            employees_who_reported_today.add(report['user_id'])

        # В JS передаём только метаданные, без текста
        reports_for_js.append({
            'user_id': report['user_id'],
            'timestamp': ts,
            'emotion': report['emotion'],
            'confidence': report['confidence'],
            'burnout_index': report['burnout_index'],
            'keywords': report['keywords'],
        })

    # Данные по каждому сотруднику
    for member in team_members:
        member['timestamp'] = safe_timestamp(member.get('last_report_date'))
        if member['has_reports']:
            member['weighted_score'] = int(db.get_user_weighted_score(member['id']))
            trend = db.get_user_score_trend(member['id'])
            member['score_trend'] = trend if trend and abs(trend['change']) > 1 else None
        else:
            member['weighted_score'] = None
            member['score_trend'] = None

    # Средний балл по команде (один расчёт)
    scored = [m['weighted_score'] for m in team_members if m['weighted_score'] is not None]
    avg_score = int(sum(scored) / len(scored)) if scored else 0

    # График динамики (взвешенный)
    daily_user_reports: dict = defaultdict(lambda: defaultdict(list))
    for report in all_team_reports:
        date = report['timestamp'][:10]
        daily_user_reports[date][report['user_id']].append({
            'confidence': report['confidence'],
            'timestamp': report['timestamp'],
        })

    date_weighted_scores = {}
    for date, users in daily_user_reports.items():
        user_scores = []
        for uid, rlist in users.items():
            rlist_sorted = sorted(rlist, key=lambda x: x['timestamp'])
            user_scores.append(db.calculate_weighted_score_for_list(rlist_sorted) * 100)
        if user_scores:
            date_weighted_scores[date] = sum(user_scores) / len(user_scores)

    sorted_dates = sorted(date_weighted_scores.keys())[-14:]
    chart_labels = [format_date(d) for d in sorted_dates]
    chart_data = [round(date_weighted_scores[d]) for d in sorted_dates]

    # Распределение
    last_scores = [m['weighted_score'] for m in team_members if m['weighted_score'] is not None]
    stats_excellent = sum(1 for s in last_scores if s >= 80)
    stats_good = sum(1 for s in last_scores if 60 <= s < 80)
    stats_warning = sum(1 for s in last_scores if s < 60)
    total_team = len(last_scores) or 1

    # Топ ключевые слова
    word_counts: dict = {}
    for report in all_team_reports:
        for word in extract_keywords(report['text'], max_count=100, max_length=50):
            word_counts[word] = word_counts.get(word, 0) + 1
    top_keywords = sorted(
        [{'word': w, 'count': c} for w, c in word_counts.items()],
        key=lambda x: x['count'], reverse=True
    )[:8]

    total_employees = len(team_members)
    reported_today = len(employees_who_reported_today)
    not_reported_today = total_employees - reported_today
    reports_percentage = int((reported_today / total_employees) * 100) if total_employees else 0

    # Burnout по команде
    team_burnout = []
    for member in team_members:
        burnout = db.get_user_burnout_trend(member['id'])
        team_burnout.append({
            "user_id": member['id'],
            "name": member['full_name'],
            "burnout": burnout["current"],
        })

    team_attention_count = sum(
        1 for m in team_members
        if m.get('last_score') is not None and m['last_score'] < 60
    )

    return {
        "team": team_members,
        "all_reports": reports_for_js,          # без текстов!
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


def _build_hr_context() -> dict:
    all_users = db.get_all_users()
    now = datetime.now()
    current_month_ru = MONTHS_FULL_RU[now.month]

    employees_data = []
    need_attention = 0
    high_morale = 0
    emotion_counter: dict = {}

    for u in all_users:
        if u['role'] != 'Сотрудник' or u['department'] == 'HR':
            continue

        user_reports = db.get_user_reports(u['id'])
        report_count = len(user_reports)
        weighted_score = db.get_user_weighted_score(u['id'])
        last_score = int(weighted_score) if user_reports else None
        score_trend = db.get_user_score_trend(u['id'])
        last_burnout = user_reports[0]['burnout_index'] if user_reports else 0

        if user_reports:
            last_emotion = user_reports[0]['emotion']
            if last_score is not None and last_score < 60:
                need_attention += 1
            if last_score is not None and last_score >= 80:
                high_morale += 1
        else:
            last_emotion = "Нет данных"

        for report in user_reports:
            emotion = report.get('emotion')
            if emotion:
                emotion_counter[emotion] = emotion_counter.get(emotion, 0) + 1

        employees_data.append({
            'id': u['id'],
            'full_name': u['full_name'],
            'role': u['role'],
            'department': u['department'],
            'last_score': last_score,
            'last_emotion': last_emotion,
            'report_count': report_count,
            'score_trend': score_trend,
            'last_burnout': last_burnout,
            'has_reports': report_count > 0,
        })

    departments = sorted(set(
        u['department'] for u in all_users
        if u['department'] and u['department'] != 'HR'
    ))

    emotion_stats = sorted(
        [{'label': k, 'count': v} for k, v in emotion_counter.items()],
        key=lambda x: x['count'], reverse=True
    )

    dept_weighted: dict = defaultdict(list)
    for emp in employees_data:
        if emp['has_reports'] and emp['last_score'] is not None:
            dept_weighted[emp['department']].append(emp['last_score'])

    dept_avg_scores = sorted(
        [{'name': dept, 'score': int(sum(scores) / len(scores))}
         for dept, scores in dept_weighted.items()],
        key=lambda x: x['score'], reverse=True
    )

    employees_with_scores = [e for e in employees_data if e['has_reports'] and e['last_score'] is not None]
    avg_company_score = (
        int(sum(e['last_score'] for e in employees_with_scores) / len(employees_with_scores))
        if employees_with_scores else 0
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
        "total_reports": sum(e['report_count'] for e in employees_data),
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
        # нужна для шаблона hr.html
        "team_attention_count": need_attention,
    }


# ─────────────────────────────────────────────
# API ЭНДПОИНТЫ
# ─────────────────────────────────────────────

@app.post("/api/login")
async def api_login(username: str = Form(...), password: str = Form(...)):
    user = db.verify_user(username, password)
    if not user:
        return RedirectResponse(url="/?error=auth", status_code=303)
    token = secrets.token_urlsafe(32)
    db.save_session(user[0], token, days=7)
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key="session_token", value=token,
        httponly=True, max_age=60 * 60 * 24 * 7, samesite="lax"
    )
    return response


@app.post("/api/logout")
async def api_logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        db.delete_session(token)
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session_token")
    return response


@app.post("/api/register")
async def api_register(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    department: str = Form(...),
):
    form_data = {"full_name": full_name, "username": username, "role": role, "department": department}

    if len(full_name.strip()) < 5:
        return templates.TemplateResponse(request=request, name="register.html",
                                          context={"error": "invalid_name", "form_data": form_data})
    if len(password) < 4:
        return templates.TemplateResponse(request=request, name="register.html",
                                          context={"error": "short_password", "form_data": form_data})
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return templates.TemplateResponse(request=request, name="register.html",
                                          context={"error": "invalid_username", "form_data": form_data})

    user_id = db.add_user(full_name, username, password, role, department)
    if user_id:
        return RedirectResponse(url="/?registered=success", status_code=303)
    return templates.TemplateResponse(request=request, name="register.html",
                                      context={"error": "exists", "form_data": form_data})


@app.post("/api/analyze")
async def api_analyze(text: str = Form(...), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]

    if len(text.strip()) < 20:
        return JSONResponse({"error": "Текст слишком короткий. Минимум 20 символов"}, status_code=400)

    user_history = db.get_user_reports_history(user_id, limit=10)
    res = analyze_emotion(text, user_history)

    if "error" in res:
        return JSONResponse({"error": res["error"]}, status_code=500)

    report_id = db.save_report(user_id, text)
    if report_id:
        db.save_analysis_result(
            report_id,
            res['display_label'],
            res['score'],
            res['burnout_index'],
            str(res['all_scores']),
        )

    return JSONResponse({
        "success": True,
        "emotion": res['display_label'],
        "confidence": res['score'],
        "burnout_index": res['burnout_index'],
        "burnout_risk": res.get('burnout_risk', 'minimal'),
        "burnout_trend": res.get('burnout_trend', 'stable'),
    })


@app.get("/api/team_analytics")
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
    start_date = (now - period_map[period]).strftime('%Y-%m-%d') if period in period_map else "2000-01-01"

    # Конвертируем timestamp
    for r in all_team_reports:
        r['timestamp'] = safe_timestamp(r['timestamp'])

    filtered = [r for r in all_team_reports if r['timestamp'][:10] >= start_date]
    if not filtered:
        return JSONResponse({"labels": [], "values": []})

    daily: dict = defaultdict(lambda: defaultdict(list))
    for r in filtered:
        daily[r['timestamp'][:10]][r['user_id']].append({
            'confidence': r['confidence'], 'timestamp': r['timestamp']
        })

    date_scores = {}
    for date, users in daily.items():
        user_scores = []
        for uid, rlist in users.items():
            rlist_sorted = sorted(rlist, key=lambda x: x['timestamp'])
            user_scores.append(db.calculate_weighted_score_for_list(rlist_sorted) * 100)
        if user_scores:
            date_scores[date] = sum(user_scores) / len(user_scores)

    sorted_dates = sorted(date_scores.keys())
    labels = [format_date(d) for d in sorted_dates]
    values = [round(date_scores[d]) for d in sorted_dates]

    return JSONResponse({"labels": labels, "values": values, "period": period})


@app.get("/api/export_reports")
async def api_export_reports(
    period: str = "all",
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "HR-администратор":
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    now = datetime.now()
    period_map = {
        "month": timedelta(days=30),
        "quarter": timedelta(days=90),
        "year": timedelta(days=365),
    }
    start_date = (now - period_map[period]).strftime('%Y-%m-%d') if period in period_map else "2000-01-01"
    period_names = {"all": "всё время", "month": "последний месяц",
                    "quarter": "последний квартал", "year": "последний год"}

    all_users = db.get_all_users()
    rows = []
    for u in all_users:
        if u['role'] != 'Сотрудник':
            continue
        user_reports = db.get_user_reports(u['id'])
        weighted_score = db.get_user_weighted_score(u['id'])
        burnout_data = db.get_user_burnout_trend(u['id'])
        period_reports_count = sum(
            1 for r in user_reports
            if safe_timestamp(r['timestamp'])[:10] >= start_date
        )
        rows.append({
            'full_name': u['full_name'],
            'department': u['department'],
            'total_reports': len(user_reports),
            'period_reports': period_reports_count,
            'weighted_score': round(weighted_score),
            'last_emotion': user_reports[0]['emotion'] if user_reports else 'Нет данных',
            'current_burnout': round(burnout_data['current'] * 100),
            'burnout_trend': '↑' if burnout_data['trend'] > 0 else ('↓' if burnout_data['trend'] < 0 else '→'),
        })

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'ФИО', 'Отдел', 'Всего отчётов',
        f"Отчётов за {period_names.get(period, period)}",
        'Средний балл (взвешенный)', 'Последняя эмоция',
        'Индекс выгорания (%)', 'Тренд выгорания',
    ])
    for r in rows:
        writer.writerow([
            r['full_name'], r['department'], r['total_reports'], r['period_reports'],
            r['weighted_score'], r['last_emotion'], r['current_burnout'], r['burnout_trend'],
        ])

    filename = f"hr_export_{period}_{now.strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode('utf-8-sig')]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/export_detailed_reports")
async def api_export_detailed_reports(
    department: str = None,
    start_date: str = None,
    end_date: str = None,
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "HR-администратор":
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    today = datetime.now().date()

    def parse_date(s, label):
        try:
            d = datetime.strptime(s, '%Y-%m-%d').date()
            if d > today:
                raise HTTPException(status_code=400, detail=f"{label} не может быть в будущем")
            return d
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Неверный формат даты: {label}")

    if start_date:
        s = parse_date(start_date, "Дата начала")
    if end_date:
        e = parse_date(end_date, "Дата окончания")
    if start_date and end_date and s > e:
        raise HTTPException(status_code=400, detail="Дата начала не может быть позже даты окончания")

    if department and department != 'all':
        users = db.get_users_by_department(department)
    else:
        users = [u for u in db.get_all_users() if u['role'] == 'Сотрудник']

    all_rows = []
    for user in users:
        for report in db.get_user_reports(user['id']):
            ts = safe_timestamp(report['timestamp'])
            if start_date and ts[:10] < start_date:
                continue
            if end_date and ts[:10] > end_date:
                continue
            all_rows.append({
                'date': ts[:10],
                'time': ts[11:19],
                'employee': user['full_name'],
                'department': user['department'],
                'text': report['text'],
                'emotion': report['emotion'] or 'Не определено',
                'confidence': round(report['confidence'] * 100) if report['confidence'] else 0,
                'burnout': round(report['burnout_index'] * 100) if report['burnout_index'] else 0,
            })

    all_rows.sort(key=lambda x: x['date'], reverse=True)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'Дата', 'Время', 'Сотрудник', 'Отдел',
        'Текст отчёта', 'Эмоция', 'Уверенность (%)', 'Индекс выгорания (%)',
    ])
    for r in all_rows:
        text_clean = r['text'].replace('\n', ' ').replace('\r', ' ').replace(';', ',')
        writer.writerow([
            r['date'], r['time'], r['employee'], r['department'],
            text_clean, r['emotion'], r['confidence'], r['burnout'],
        ])

    filename = f"detailed_reports_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode('utf-8-sig')]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
