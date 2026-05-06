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

# Теперь импорты должны работать
from model.text_preprocessor import RUSSIAN_STOP_WORDS, clean_text
from model.emotion_model import analyze_emotion
import database.database as db

load_dotenv()

app = FastAPI()

# Константы
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONTHS_SHORT = {1: 'янв', 2: 'фев', 3: 'мар', 4: 'апр', 5: 'май', 6: 'июн',
                7: 'июл', 8: 'авг', 9: 'сен', 10: 'окт', 11: 'ноя', 12: 'дек'}
MONTHS_FULL = {1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля', 5: 'мая', 6: 'июня',
               7: 'июля', 8: 'августа', 9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'}

# Вспомогательные функции

def extract_keywords(text: str, max_count: int = 3, max_length: int = 20) -> list:
    """
    Извлекает ключевые слова из текста.
    Использует единый препроцессор из model.text_preprocessor
    """
    if not text:
        return []
    
    # Используем очистку из препроцессора (без замены чисел и без удаления стоп-слов)
    cleaned = clean_text(
        text,
        lowercase=True,
        remove_punctuation=True,
        replace_numbers=False,  # Не заменяем числа для ключевых слов
        remove_stopwords=False,  # Не удаляем стоп-слова здесь
        strip_extra_spaces=True
    )
    
    # Разбиваем на слова
    words = cleaned.split()
    
    keywords = []
    for word in words:
        # Проверяем длину и что это не стоп-слово
        if (len(word) > 3 and 
            word not in RUSSIAN_STOP_WORDS and 
            word not in keywords and 
            len(keywords) < max_count):
            keywords.append(word[:max_length])
    
    return keywords

def format_date(date_str: str, use_full: bool = False) -> str:
    """Форматирует дату из ISO формата"""
    try:
        dt = datetime.strptime(date_str[:10], '%Y-%m-%d')
        months = MONTHS_FULL if use_full else MONTHS_SHORT
        return f"{dt.day} {months[dt.month]}" + (f" {dt.year} г." if use_full else "")
    except (ValueError, IndexError):
        return date_str[:10]

# Монтирование static и templates
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

db.init_db()

# Dependency для проверки аутентификации через сессии
def get_current_user(request: Request):
    """
    Получает текущего пользователя из сессии.
    Если сессия недействительна, редиректит на страницу входа.
    """
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
        "department": session["department"]
    }

# --- МАРШРУТЫ ДЛЯ СТРАНИЦ ---

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None, registered: str = None):
    return templates.TemplateResponse(
        request=request, 
        name="login.html",
        context={"error": error, "registered": registered}
    )


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="register.html",
        context={"form_data": {}}
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    
    user = {
        "id": current_user["user_id"],
        "full_name": current_user["name"],
        "role": current_user["role"],
        "department": current_user["department"]
    }
    
    reports = db.get_user_reports(user_id)
    _, total_reports = db.get_user_reports_paginated(user_id, limit=1, offset=0)
    
    context = {"user": user, "reports": reports, "total_reports": total_reports}

    # ==================== СОТРУДНИК ====================
    if user['role'] == "Сотрудник":
        avg_score = int(db.get_user_weighted_wellbeing(user_id))

        reports = db.get_user_reports(user_id)
        for r in reports:
            r['keywords'] = extract_keywords(r['text'], max_count=3)
        
        if reports:
            current_score = int(reports[0]['confidence'] * 100)
            current_emotion = reports[0]['emotion']
        else:
            current_score = 0
            current_emotion = "Нет данных"

        score_trend = db.get_user_score_trend(user_id)
        burnout_data = db.get_user_burnout_trend(user_id)

        # Добавляем изменение выгорания в процентах
        burnout_change = burnout_data["trend"] * 100  # trend уже в долях (0.05 = 5%)
        
        context.update({
            "avg_score": avg_score,
            "score_trend": score_trend,
            "current_score": current_score,
            "current_emotion": current_emotion,
            "burnout_current": burnout_data["current"],
            "burnout_trend": burnout_data["trend"],
            "burnout_trend_percent": round(burnout_change)
        })

    # ==================== РУКОВОДИТЕЛЬ ====================
    elif user['role'] == "Руководитель":
        team_members = db.get_team_with_reports(user['department'])
        all_team_reports = db.get_all_team_reports(user['department'])

        for report in all_team_reports:
            report['keywords'] = extract_keywords(report['text'], max_count=5)

        # Для каждого сотрудника получаем готовые данные (БЕЗ ДУБЛИРОВАНИЯ)
        for member in team_members:
            if member['has_reports']:
                # 1. Берём готовый взвешенный балл
                member['weighted_score'] = int(db.get_user_weighted_score(member['id']))
                
                # 2. Берём готовый тренд и показываем ТОЛЬКО если изменение >3%
                trend = db.get_user_score_trend(member['id'])
                if trend and abs(trend['change']) > 1:
                    member['score_trend'] = trend
                else:
                    member['score_trend'] = None
            else:
                member['weighted_score'] = None
                member['score_trend'] = None
        
        # Средний балл по команде (на основе взвешенных)
        team_weighted_scores = [m['weighted_score'] for m in team_members if m['weighted_score'] is not None]
        avg_score = int(sum(team_weighted_scores) / len(team_weighted_scores)) if team_weighted_scores else 0
        
        team_weighted_scores = db.get_team_weighted_scores(user['department'])
        avg_score = int(sum(team_weighted_scores) / len(team_weighted_scores)) if team_weighted_scores else 0
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        reports_today_count = sum(1 for r in all_team_reports if r['timestamp'].startswith(today_str))
        employees_who_reported_today = set(r['user_id'] for r in all_team_reports if r['timestamp'].startswith(today_str))
        
        team_attention_count = sum(1 for member in team_members 
                          if member.get('last_score') is not None and member.get('last_score', 0) < 60)

        # График динамики с взвешенным усреднением
        daily_user_reports = defaultdict(lambda: defaultdict(list))

        for report in all_team_reports:
            date = report['timestamp'][:10]
            report_user_id = report['user_id']
            daily_user_reports[date][report_user_id].append({
                'confidence': report['confidence'],
                'timestamp': report['timestamp']
            })

        date_weighted_scores = {}
        for date, users in daily_user_reports.items():
            user_weighted_scores = []
            for report_user_id, reports_list in users.items():
                reports_sorted = sorted(reports_list, key=lambda x: x['timestamp'])
                weighted = db.calculate_weighted_score_for_list(reports_sorted) * 100
                user_weighted_scores.append(weighted)
            
            if user_weighted_scores:
                date_weighted_scores[date] = sum(user_weighted_scores) / len(user_weighted_scores)

        sorted_dates = sorted(date_weighted_scores.keys())[-14:]
        chart_labels = []
        chart_data = []
        daily_reports_count = []
        for date in sorted_dates:
            chart_labels.append(format_date(date))
            chart_data.append(round(date_weighted_scores[date]))
            daily_reports_count.append(len(daily_user_reports[date]))
        
        team_last_scores = [m.get('last_score', 0) for m in team_members if m.get('last_score') is not None]
        
        stats_excellent = sum(1 for s in team_last_scores if s >= 80)
        stats_good = sum(1 for s in team_last_scores if 60 <= s < 80)
        stats_warning = sum(1 for s in team_last_scores if s < 60)
        total_team = len(team_last_scores) if team_last_scores else 1
        
        dist_data = [stats_excellent, stats_good, stats_warning]
        
        # Топ-ключевые слова
        word_counts = {}
        for report in all_team_reports:
            for word in extract_keywords(report['text'], max_count=100, max_length=50):
                word_counts[word] = word_counts.get(word, 0) + 1
        
        top_keywords = sorted([{'word': w, 'count': c} for w, c in word_counts.items()], 
                              key=lambda x: x['count'], reverse=True)[:8]
        
        total_employees = len(team_members)
        reported_today = len(employees_who_reported_today)
        not_reported_today = total_employees - reported_today
        reports_percentage = int((reported_today / total_employees) * 100) if total_employees > 0 else 0

        not_reported_list = []
        for member in team_members:
            if member['id'] not in employees_who_reported_today:
                not_reported_list.append({
                    'id': member['id'],
                    'full_name': member['full_name']
                })

        # Burnout данные по команде
        team_burnout = []
        for member in team_members:
            burnout = db.get_user_burnout_trend(member['id'])
            team_burnout.append({
                "user_id": member['id'],
                "name": member['full_name'],
                "burnout": burnout["current"]
            })
        
        # Добавляем тренд для каждого члена команды
        for member in team_members:
            trend = db.get_user_score_trend(member['id'])
            member['score_trend'] = trend
        
        context.update({
            "team": team_members,
            "all_reports": all_team_reports,
            "avg_score": avg_score,
            "reports_today": reports_today_count,
            "chart_labels": chart_labels,
            "chart_data": chart_data,
            "dist_data": dist_data,
            "stats_excellent": stats_excellent,
            "stats_good": stats_good,
            "stats_warning": stats_warning,
            "stats_excellent_percent": round(stats_excellent / total_team * 100) if total_team else 0,
            "stats_good_percent": round(stats_good / total_team * 100) if total_team else 0,
            "stats_warning_percent": round(stats_warning / total_team * 100) if total_team else 0,
            "team_attention_count": team_attention_count,
            "team_attention_list": [m for m in team_members if m.get('last_score') is not None and m.get('last_score', 0) < 60],
            "top_keywords": top_keywords,
            "total_employees": total_employees,
            "reported_today": reported_today,
            "not_reported_today": not_reported_today,
            "reports_percentage": reports_percentage,
            "not_reported_list": not_reported_list,
            "reports_today_count": reports_today_count,
            "team_burnout": team_burnout,
            "team_high_burnout": [m for m in team_burnout if m["burnout"] > 0.5]
        })


    # ==================== HR-АДМИНИСТРАТОР ====================
    elif user['role'] == "HR-администратор":
        all_users = db.get_all_users()
        
        employees_data = []
        total_reports_count = 0
        need_attention = 0
        high_morale = 0
        emotion_counter = {}

        # Для русских названий месяцев
        calendar.month_name_ru = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
        }

        now = datetime.now()
        current_month_ru = calendar.month_name_ru[now.month]
              
        for u in all_users:
            if u['role'] == 'Сотрудник':
                if u['department'] == 'HR':
                    continue  # пропускаем HR-отдел полностью
                user_reports = db.get_user_reports(u['id'])
                report_count = len(user_reports)
                total_reports_count += report_count
                
                weighted_score = db.get_user_weighted_score(u['id'])
                last_score = int(weighted_score) if user_reports else None
                
                score_trend = db.get_user_score_trend(u['id'])
                
                if user_reports:
                    last_emotion = user_reports[0]['emotion']
                    if last_score < 60:
                        need_attention += 1
                    if last_score >= 80:
                        high_morale += 1
                else:
                    last_emotion = "Нет данных"
                
                for report in user_reports:
                    emotion = report['emotion']
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
                    'last_burnout': user_reports[0]['burnout_index'] if user_reports else 0,
                    'has_reports': report_count > 0
                })
        
        # Статистика эмоций
        emotion_stats = [{'label': k, 'count': v} for k, v in sorted(emotion_counter.items(), key=lambda x: x[1], reverse=True)]
        # Исключаем 'HR' из списка отделов
        departments = sorted(set([
            u['department'] for u in all_users 
            if u['department'] and u['department'] != 'HR'
        ]))
        
        # Средний балл по отделам (только сотрудники с отчётами)
        dept_weighted_scores = defaultdict(list)
        for emp in employees_data:
            if emp['has_reports'] and emp['last_score'] is not None:
                dept_weighted_scores[emp['department']].append(emp['last_score'])
        
        dept_avg_scores = []
        for dept, scores in dept_weighted_scores.items():
            avg = int(sum(scores) / len(scores)) if scores else 0
            dept_avg_scores.append({'name': dept, 'score': avg})
        dept_avg_scores.sort(key=lambda x: x['score'], reverse=True)
        
        # Средний балл по компании
        employees_with_reports = [emp for emp in employees_data if emp['has_reports'] and emp['last_score'] is not None]
        if employees_with_reports:
            total_score_sum = sum(emp['last_score'] for emp in employees_with_reports)
            avg_company_score = int(total_score_sum / len(employees_with_reports))
        else:
            avg_company_score = 0
        
        # Данные для графиков
        company_burnout_history = db.get_company_burnout_history(days=30)
        departments_burnout_history = db.get_departments_burnout_history(days=30)  
        company_burnout_avg = company_burnout_history[-1]["burnout"] if company_burnout_history else 0
        burnout_stats = db.get_company_burnout_stats()
        high_burnout_employees = burnout_stats["high_burnout_employees"]
        period_comparison = db.get_period_comparison()
        dept_reports_stats = db.get_department_reports_stats()
        total_reports_all = sum(d["report_count"] for d in dept_reports_stats)
        
        context.update({
            "total_employees": len(employees_data),
            "total_reports": total_reports_count,
            "current_month_ru": current_month_ru,
            "need_attention_count": need_attention,
            "high_morale_count": high_morale,
            "employees_data": employees_data,
            "departments": departments,
            "emotion_stats": emotion_stats,
            "dept_avg_scores": dept_avg_scores,
            "avg_company_score": avg_company_score,
            "dept_reports_stats": dept_reports_stats,
            "total_reports_all": total_reports_all,
            "company_burnout_history": company_burnout_history,
            "departments_burnout_history": departments_burnout_history,  
            "company_burnout_avg": company_burnout_avg,
            "high_burnout_employees": high_burnout_employees,
            "period_comparison": period_comparison
        })
    
    
    
    role_templates = {
        "Сотрудник": "employee.html",
        "Руководитель": "manager.html",
        "HR-администратор": "hr.html"
    }
    
    template_name = role_templates.get(user['role'], "employee.html")
    
    return templates.TemplateResponse(
        request=request, 
        name=template_name, 
        context=context
    )


# ==================== API ЭНДПОИНТЫ ====================

@app.get("/api/team_analytics")
async def api_team_analytics(
    period: str = "all",
    current_user: dict = Depends(get_current_user)
):
    """Возвращает данные для графика динамики команды за выбранный период"""
    
    if current_user["role"] != "Руководитель":
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    department = current_user["department"]
    all_team_reports = db.get_all_team_reports(department)
    
    if not all_team_reports:
        return JSONResponse({"labels": [], "values": []})
    
    now = datetime.now()
    if period == "week":
        start_date = (now - timedelta(days=7)).strftime('%Y-%m-%d')
    elif period == "month":
        start_date = (now - timedelta(days=30)).strftime('%Y-%m-%d')
    elif period == "quarter":
        start_date = (now - timedelta(days=90)).strftime('%Y-%m-%d')
    elif period == "year":
        start_date = (now - timedelta(days=365)).strftime('%Y-%m-%d')
    else:
        start_date = "2000-01-01"
    
    filtered_reports = [r for r in all_team_reports if r['timestamp'][:10] >= start_date]
    
    if not filtered_reports:
        return JSONResponse({"labels": [], "values": []})
    
    daily_user_reports = defaultdict(lambda: defaultdict(list))
    
    for report in filtered_reports:
        date = report['timestamp'][:10]
        report_user_id = report['user_id']
        daily_user_reports[date][report_user_id].append({
            'confidence': report['confidence'],
            'timestamp': report['timestamp']
        })
    
    date_weighted_scores = {}
    for date, users in daily_user_reports.items():
        user_weighted_scores = []
        for report_user_id, reports_list in users.items():
            reports_sorted = sorted(reports_list, key=lambda x: x['timestamp'])
            weighted = db.calculate_weighted_score_for_list(reports_sorted) * 100
            user_weighted_scores.append(weighted)
        
        if user_weighted_scores:
            date_weighted_scores[date] = sum(user_weighted_scores) / len(user_weighted_scores)
    
    sorted_dates = sorted(date_weighted_scores.keys())
    labels = []
    values = []
    for date in sorted_dates:
        dt = datetime.strptime(date, '%Y-%m-%d')
        labels.append(f"{dt.day} {MONTHS_SHORT[dt.month]}")
        values.append(round(date_weighted_scores[date]))
    
    return JSONResponse({
        "labels": labels,
        "values": values,
        "period": period
    })


@app.get("/api/export_reports")
async def api_export_reports(
    request: Request,
    period: str = "all",
    current_user: dict = Depends(get_current_user)
):
    """Экспорт сводки по сотрудникам в CSV"""
    
    if current_user["role"] != "HR-администратор":
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    now = datetime.now()
    if period == "month":
        start_date = (now - timedelta(days=30)).strftime('%Y-%m-%d')
    elif period == "quarter":
        start_date = (now - timedelta(days=90)).strftime('%Y-%m-%d')
    elif period == "year":
        start_date = (now - timedelta(days=365)).strftime('%Y-%m-%d')
    else:
        start_date = "2000-01-01"
    
    all_users = db.get_all_users()
    
    employees_data = []
    for u in all_users:
        if u['role'] == 'Сотрудник':
            user_reports = db.get_user_reports(u['id'])
            weighted_score = db.get_user_weighted_score(u['id'])
            burnout_data = db.get_user_burnout_trend(u['id'])
            
            filtered_reports = [r for r in user_reports if r['timestamp'][:10] >= start_date]
            period_reports_count = len(filtered_reports)
            
            employees_data.append({
                'full_name': u['full_name'],
                'department': u['department'],
                'total_reports': len(user_reports),
                'period_reports': period_reports_count,
                'weighted_score': round(weighted_score),
                'last_emotion': user_reports[0]['emotion'] if user_reports else 'Нет данных',
                'current_burnout': round(burnout_data['current'] * 100),
                'burnout_trend': '↑' if burnout_data['trend'] > 0 else '↓' if burnout_data['trend'] < 0 else '→'
            })
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    period_names = {"all": "всё время", "month": "последний месяц", "quarter": "последний квартал", "year": "последний год"}
    period_text = period_names.get(period, period)
    
    writer.writerow([
        'ФИО', 'Отдел', 'Всего отчётов', f'Отчётов за {period_text}',
        'Средний балл (взвешенный)', 'Последняя эмоция', 'Индекс выгорания (%)', 'Тренд выгорания'
    ])
    
    for emp in employees_data:
        writer.writerow([
            emp['full_name'], emp['department'], emp['total_reports'], emp['period_reports'],
            emp['weighted_score'], emp['last_emotion'], emp['current_burnout'], emp['burnout_trend']
        ])
    
    filename = f"hr_export_{period}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue().encode('utf-8-sig')]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/api/export_detailed_reports")
async def api_export_detailed_reports(
    request: Request,
    department: str = None,
    start_date: str = None,
    end_date: str = None,
    current_user: dict = Depends(get_current_user)
):
    """Экспорт детальных отчётов (тексты + анализ) в CSV"""
    
    if current_user["role"] != "HR-администратор":
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    today = datetime.now().date()
    
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            if start > today:
                raise HTTPException(status_code=400, detail="Дата начала не может быть в будущем")
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат даты начала")
    
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            if end > today:
                raise HTTPException(status_code=400, detail="Дата окончания не может быть в будущем")
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат даты окончания")
    
    if start_date and end_date:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        if start > end:
            raise HTTPException(status_code=400, detail="Дата начала не может быть позже даты окончания")
    
    if department and department != 'all':
        users = db.get_users_by_department(department)
    else:
        all_users = db.get_all_users()
        users = [u for u in all_users if u['role'] == 'Сотрудник']
    
    all_reports = []
    for user in users:
        reports = db.get_user_reports(user['id'])
        
        for report in reports:
            if start_date and report['timestamp'][:10] < start_date:
                continue
            if end_date and report['timestamp'][:10] > end_date:
                continue
            
            all_reports.append({
                'date': report['timestamp'][:10],
                'time': report['timestamp'][11:19] if len(report['timestamp']) > 10 else '',
                'employee': user['full_name'],
                'department': user['department'],
                'text': report['text'],
                'emotion': report['emotion'] or 'Не определено',
                'confidence': round(report['confidence'] * 100) if report['confidence'] else 0,
                'burnout': round(report['burnout_index'] * 100) if report['burnout_index'] else 0
            })
    
    all_reports.sort(key=lambda x: x['date'], reverse=True)
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    writer.writerow([
        'Дата', 'Время', 'Сотрудник', 'Отдел',
        'Текст отчёта', 'Эмоция', 'Уверенность (%)', 'Индекс выгорания (%)'
    ])
    
    for report in all_reports:
        text_clean = report['text'].replace('\n', ' ').replace('\r', ' ').replace(';', ',')
        writer.writerow([
            report['date'], report['time'], report['employee'], report['department'],
            text_clean, report['emotion'], report['confidence'], report['burnout']
        ])
    
    filename = f"detailed_reports_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue().encode('utf-8-sig')]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.post("/api/login")
async def api_login(username: str = Form(...), password: str = Form(...)):
    user = db.verify_user(username, password)
    if user:
        token = secrets.token_urlsafe(32)
        db.save_session(user[0], token, days=7)
        
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            max_age=60*60*24*7,
            samesite="lax"
        )
        return response
    return RedirectResponse(url="/?error=auth", status_code=303)


@app.post("/api/register")
async def api_register(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    department: str = Form(...)
):
    form_data = {"full_name": full_name, "username": username, "role": role, "department": department}
    
    if len(full_name.strip()) < 5:
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"error": "invalid_name", "form_data": form_data}
        )
    
    if len(password) < 4:
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"error": "short_password", "form_data": form_data}
        )
    
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"error": "invalid_username", "form_data": form_data}
        )
    
    user_id = db.add_user(full_name, username, password, role, department)
    if user_id:
        return RedirectResponse(url="/?registered=success", status_code=303)
    
    return templates.TemplateResponse(
        request=request, name="register.html",
        context={"error": "exists", "form_data": form_data}
    )


@app.get("/api/user_reports")
async def api_user_reports(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    reports = db.get_user_reports(user_id)
    return JSONResponse({"reports": reports})


@app.get("/api/user_reports/paginated")
async def api_user_reports_paginated(
    limit: int = 10, 
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["user_id"]
    reports, total = db.get_user_reports_paginated(user_id, limit, offset)
    return JSONResponse({
        "reports": reports,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total
    })


@app.post("/api/logout")
async def api_logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        db.delete_session(token)
    
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session_token")
    return response

@app.post("/api/analyze")
async def api_analyze(text: str = Form(...), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    
    if len(text.strip()) < 20:
        return JSONResponse({"error": "Текст слишком короткий. Минимум 20 символов"}, status_code=400)
    
    # Получаем историю отчётов пользователя (для расчёта тренда выгорания)
    user_history = db.get_user_reports_history(user_id, limit=10)
    
    # Анализ с учётом истории
    res = analyze_emotion(text, user_history)
    
    if "error" in res:
        return JSONResponse({"error": res["error"]}, status_code=500)
    
    # Сохраняем отчёт
    report_id = db.save_report(user_id, text)
    if report_id:
        db.save_analysis_result(
            report_id, 
            res['display_label'], 
            res['score'], 
            res['burnout_index'], 
            str(res['all_scores'])
        )
    
    return JSONResponse({
        "success": True,
        "emotion": res['display_label'],
        "confidence": res['score'],
        "burnout_index": res['burnout_index'],
        "burnout_risk": res.get('burnout_risk', 'minimal'),
        "burnout_trend": res.get('burnout_trend', 'stable')
    })