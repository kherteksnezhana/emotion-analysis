import sqlite3
import hashlib
import os
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any, Union

# Путь к файлу базы данных в той же папке, где лежит этот скрипт
DB_PATH = os.path.join(os.path.dirname(__file__), 'users.db')

def init_db():
    """Создает таблицы, если они еще не существуют"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            department TEXT DEFAULT 'General'
        )
    ''')
    
    # Таблица отчетов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    
    # Таблица результатов анализа
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analysis_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            emotion_label TEXT NOT NULL,
            confidence REAL NOT NULL,
            burnout_index REAL NOT NULL,
            all_scores TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(report_id) REFERENCES reports(id)
        )
    ''')
    
    # Таблица сессий
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at DATETIME NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    conn.close()

def hash_password(password):
    """Шифрует пароль в SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def add_user(full_name, username, password, role, department="General"):
    """Добавляет нового пользователя в базу"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        pw_hash = hash_password(password)
        cursor.execute('''
            INSERT INTO users (full_name, username, password_hash, role, department) 
            VALUES (?, ?, ?, ?, ?)
        ''', (full_name, username, pw_hash, role, department))
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        return None  # Логин уже занят

def verify_user(username, password) -> Optional[Tuple]:
    """Проверяет данные пользователя при входе"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    pw_hash = hash_password(password)
    cursor.execute('''
        SELECT id, full_name, role, department FROM users 
        WHERE username = ? AND password_hash = ?
    ''', (username, pw_hash))
    user = cursor.fetchone()
    conn.close()
    return user  # Вернет (id, Имя, Роль, Отдел) или None

def save_report(user_id: int, text: str) -> Optional[int]:
    """Сохраняет отчет пользователя"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO reports (user_id, text, timestamp) 
            VALUES (?, ?, ?)
        ''', (user_id, text, datetime.now()))
        conn.commit()
        report_id = cursor.lastrowid
        conn.close()
        return report_id
    except Exception as e:
        print(f"Ошибка при сохранении отчета: {e}")
        return None

def save_analysis_result(report_id: int, emotion_label: str, confidence: float, 
                        burnout_index: float, all_scores: str) -> bool:
    """Сохраняет результаты анализа"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO analysis_results 
            (report_id, emotion_label, confidence, burnout_index, all_scores, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (report_id, emotion_label, confidence, burnout_index, all_scores, datetime.now()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка при сохранении результатов: {e}")
        return False

def get_user_reports(user_id: int) -> List[Dict[str, Any]]:
    """Получает все отчеты пользователя с результатами анализа"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.id, r.text, r.timestamp, ar.emotion_label, ar.confidence, ar.burnout_index
        FROM reports r
        LEFT JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id = ?
        ORDER BY r.timestamp DESC
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            'id': row[0],
            'text': row[1],
            'timestamp': row[2],
            'emotion': row[3],
            'confidence': row[4],
            'burnout_index': row[5]
        })
    return results


def get_user_reports_history(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Получает историю отчётов пользователя с результатами анализа
    для расчёта тренда выгорания
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.id, r.text, r.timestamp, ar.emotion_label, ar.confidence, ar.burnout_index
        FROM reports r
        LEFT JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id = ?
        ORDER BY r.timestamp DESC
        LIMIT ?
    ''', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            'id': row[0],
            'text': row[1],
            'timestamp': row[2],
            'emotion': row[3],
            'confidence': row[4],
            'burnout_index': row[5] or 0.0
        })
    return results

def get_user_department(user_id: int) -> str:
    """Получает отдел пользователя по его ID"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT department FROM users WHERE id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else ""

def get_all_users() -> List[Dict[str, Any]]:
    """Получает всех пользователей системы"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, full_name, username, role, department 
        FROM users 
        ORDER BY full_name
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            'id': row[0],
            'full_name': row[1],
            'username': row[2],
            'role': row[3],
            'department': row[4]
        }
        for row in rows
    ]

def get_users_by_department(department: str) -> List[Dict[str, Any]]:
    """Получает всех пользователей отдела"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, full_name, role, department FROM users WHERE department = ?",
        (department,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {"id": row[0], "full_name": row[1], "role": row[2], "department": row[3]}
        for row in rows
    ]

def get_department_employees(department: str) -> List[Dict[str, Any]]:
    """Получает всех сотрудников отдела с их последним статусом"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.id, u.full_name, ar.emotion_label, ar.confidence, ar.burnout_index, ar.timestamp
        FROM users u
        LEFT JOIN (
            SELECT r.user_id, ar.emotion_label, ar.confidence, ar.burnout_index, ar.timestamp
            FROM reports r
            JOIN analysis_results ar ON r.id = ar.report_id
            WHERE ar.timestamp = (
                SELECT MAX(ar2.timestamp) FROM analysis_results ar2 
                JOIN reports r2 ON ar2.report_id = r2.id
                WHERE r2.user_id = r.user_id
            )
        ) ar ON u.id = ar.user_id
        WHERE u.department = ? AND u.role = 'Сотрудник'
        ORDER BY u.full_name
    ''', (department,))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            'id': row[0],
            'name': row[1],
            'emotion': row[2],
            'confidence': row[3],
            'burnout_index': row[4],
            'timestamp': row[5]
        })
    return results

def get_all_emotions_heatmap() -> List[Dict[str, Any]]:
    """Получает данные для тепловой карты по всей компании"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.department, ar.emotion_label, COUNT(*) as count, AVG(ar.burnout_index) as avg_burnout
        FROM users u
        JOIN reports r ON u.id = r.user_id
        JOIN analysis_results ar ON r.id = ar.report_id
        WHERE ar.timestamp = (
            SELECT MAX(ar2.timestamp) FROM analysis_results ar2 
            JOIN reports r2 ON ar2.report_id = r2.id
            WHERE r2.user_id = r.user_id
        )
        GROUP BY u.department, ar.emotion_label
        ORDER BY u.department, ar.emotion_label
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            'department': row[0],
            'emotion': row[1],
            'count': row[2],
            'avg_burnout': row[3]
        })
    return results

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Получает информацию о пользователе по ID"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, full_name, role, department FROM users WHERE id = ?
    ''', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return {
            'id': user[0],
            'name': user[1],
            'role': user[2],
            'department': user[3]
        }
    return None

def save_session(user_id: int, token: str, days: int = 7) -> bool:
    """Сохраняет токен сессии в БД"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        expires_at = datetime.now() + timedelta(days=days)
        cursor.execute('''
            INSERT OR REPLACE INTO sessions (user_id, token, expires_at)
            VALUES (?, ?, ?)
        ''', (user_id, token, expires_at))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка при сохранении сессии: {e}")
        return False

def get_session_by_token(token: str) -> Optional[Dict[str, Any]]:
    """Получает данные сессии по токену"""
    if not token:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT s.user_id, s.token, s.expires_at, u.full_name, u.role, u.department
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ? AND s.expires_at > datetime('now')
        ''', (token,))
        session = cursor.fetchone()
        conn.close()
        
        if session:
            return {
                'user_id': session[0],
                'token': session[1],
                'expires_at': session[2],
                'name': session[3],
                'role': session[4],
                'department': session[5]
            }
        return None
    except Exception as e:
        print(f"Ошибка при получении сессии: {e}")
        return None

def delete_session(token: str) -> bool:
    """Удаляет токен сессии"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sessions WHERE token = ?', (token,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка при удалении сессии: {e}")
        return False

def cleanup_expired_sessions() -> bool:
    """Очищает просроченные сессии"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка при очистке сессий: {e}")
        return False

# 🔒 FIXED: Оптимизированный запрос - получает сотрудников отдела с последним отчётом одним JOIN
def get_team_with_reports(department: str) -> List[Dict[str, Any]]:
    """Получает всех сотрудников отдела с их последним отчётом"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            u.id,
            u.full_name,
            u.role,
            u.department,
            ar.emotion_label as last_emotion,
            ar.confidence as last_confidence,
            ar.burnout_index as last_burnout,
            ar.timestamp as last_report_date,
            (SELECT COUNT(*) FROM reports r2 WHERE r2.user_id = u.id) as report_count
        FROM users u
        LEFT JOIN (
            SELECT r.user_id, ar.emotion_label, ar.confidence, ar.burnout_index, ar.timestamp
            FROM reports r
            JOIN analysis_results ar ON r.id = ar.report_id
            WHERE ar.timestamp = (
                SELECT MAX(ar2.timestamp) 
                FROM analysis_results ar2 
                JOIN reports r2 ON ar2.report_id = r2.id
                WHERE r2.user_id = r.user_id
            )
        ) ar ON u.id = ar.user_id
        WHERE u.department = ? AND u.role = 'Сотрудник'
        ORDER BY u.full_name
    ''', (department,))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        report_count = row[8]
        results.append({
            'id': row[0],
            'full_name': row[1],
            'role': row[2],
            'department': row[3],
            'last_emotion': row[4],
            'last_confidence': row[5],
            'last_burnout': row[6],
            'last_report_date': row[7],
            'report_count': report_count,
            # 🔥 КЛЮЧЕВОЕ ИЗМЕНЕНИЕ:
            'last_score': int(row[5] * 100) if row[5] is not None else None,  # None вместо 0
            'has_reports': report_count > 0
        })
    return results

# 🔒 FIXED: Пагинированная версия получения отчётов пользователя
def get_user_reports_paginated(user_id: int, limit: int = 10, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """
    Получает отчёты пользователя с пагинацией.
    Возвращает кортеж (список отчётов, общее количество).
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Получаем общее количество отчётов
    cursor.execute('SELECT COUNT(*) FROM reports WHERE user_id = ?', (user_id,))
    total = cursor.fetchone()[0]
    
    # Получаем отчёты с пагинацией
    cursor.execute('''
        SELECT r.id, r.text, r.timestamp, ar.emotion_label, ar.confidence, ar.burnout_index
        FROM reports r
        LEFT JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id = ?
        ORDER BY r.timestamp DESC
        LIMIT ? OFFSET ?
    ''', (user_id, limit, offset))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            'id': row[0],
            'text': row[1],
            'timestamp': row[2],
            'emotion': row[3],
            'confidence': row[4],
            'burnout_index': row[5]
        })
    return results, total

# 🔒 FIXED: Оптимизация - получает ВСЕ отчёты команды одним запросом
def get_all_team_reports(department: str) -> List[Dict[str, Any]]:
    """
    Получает все отчёты всех сотрудников отдела одним запросом.
    Используется для аналитики руководителя.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            r.id,
            r.user_id,
            u.full_name as user_name,
            r.text,
            r.timestamp,
            ar.emotion_label,
            ar.confidence,
            ar.burnout_index
        FROM reports r
        JOIN users u ON r.user_id = u.id
        LEFT JOIN analysis_results ar ON r.id = ar.report_id
        WHERE u.department = ? AND u.role = 'Сотрудник'
        ORDER BY r.timestamp DESC
    ''', (department,))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            'id': row[0],
            'user_id': row[1],
            'user_name': row[2],
            'text': row[3],
            'timestamp': row[4],
            'emotion': row[5],
            'confidence': row[6],
            'burnout_index': row[7]
        })
    return results

# 🔄 FIXED: Функция для взвешенного усреднения с экспоненциальным затуханием
def calculate_weighted_score(reports: List[Dict[str, Any]], decay_factor: float = 0.7) -> float:
    """
    Рассчитывает взвешенное среднее confidence с экспоненциальным затуханием.
    
    Аргументы:
        reports: список отчётов, каждый с ключом 'confidence' и 'timestamp'
        decay_factor: коэффициент затухания (0.7 = новые весят на 30% больше)
    
    Возвращает:
        взвешенный confidence (от 0 до 1)
    """
    if not reports:
        return 0.0
    
    # Сортируем по времени (старые → новые)
    sorted_reports = sorted(reports, key=lambda x: x['timestamp'])
    
    total_weight = 0
    weighted_sum = 0
    n = len(sorted_reports)
    
    for i, report in enumerate(sorted_reports):
        # Экспоненциальный вес: чем новее отчёт, тем больше вес
        weight = decay_factor ** (n - i - 1)
        weighted_sum += report['confidence'] * weight
        total_weight += weight
    
    return weighted_sum / total_weight if total_weight > 0 else 0

# 🔄 FIXED: Получить взвешенный средний балл для пользователя в процентах
def get_user_weighted_score(user_id: int) -> float:
    """Возвращает взвешенный средний confidence пользователя в процентах (0-100)"""
    reports = get_user_reports(user_id)
    if not reports:
        return 0.0
    return calculate_weighted_score(reports) * 100

# 🔄 FIXED: Получить взвешенные баллы для всех сотрудников отдела
def get_team_weighted_scores(department: str) -> List[float]:
    """Возвращает список взвешенных баллов всех сотрудников отдела"""
    team = get_team_with_reports(department)
    scores = []
    for member in team:
        weighted = get_user_weighted_score(member['id'])
        scores.append(weighted)
    return scores

# 🔄 FIXED: Упрощённая версия для списка словарей
def calculate_weighted_score_for_list(reports_list: List[dict], decay_factor: float = 0.7) -> float:
    """
    Упрощённая версия calculate_weighted_score для списка словарей 
    с ключами 'confidence' и 'timestamp'.
    """
    if not reports_list:
        return 0.0
    
    sorted_reports = sorted(reports_list, key=lambda x: x['timestamp'])
    
    total_weight = 0
    weighted_sum = 0
    n = len(sorted_reports)
    
    for i, report in enumerate(sorted_reports):
        weight = decay_factor ** (n - i - 1)
        weighted_sum += report['confidence'] * weight
        total_weight += weight
    
    return weighted_sum / total_weight if total_weight > 0 else 0

# ============= НОВЫЕ ФУНКЦИИ =============

def get_user_burnout_trend(user_id: int, days: int = 30) -> Dict[str, Any]:
    """
    Получает динамику burnout индекса пользователя за последние N дней
    
    Возвращает:
        dict: {
            "current": текущий burnout (0-1),
            "trend": тренд (положительный = рост выгорания),
            "history": список для графика
        }
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.timestamp, ar.burnout_index
        FROM reports r
        JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id = ?
        ORDER BY r.timestamp DESC
        LIMIT ?
    ''', (user_id, days))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return {"current": 0.0, "trend": 0.0, "history": []}
    
    # История для графика (от старых к новым)
    history = [{"date": row[0][:10], "burnout": row[1]} for row in reversed(rows)]
    current = rows[0][1] if rows else 0.0
    
    # Тренд (разница между текущим и средним за предыдущий период)
    if len(rows) > 1:
        prev_avg = sum(row[1] for row in rows[1:]) / len(rows[1:])
        trend = current - prev_avg
    else:
        trend = 0.0
    
    return {
        "current": round(current, 4),
        "trend": round(trend, 4),
        "history": history
    }

def get_department_reports_stats() -> List[Dict[str, Any]]:
    """
    Получает статистику количества отчётов по отделам
    
    Возвращает:
        list: [{"department": "IT", "report_count": 42, "percentage": 30}, ...]
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.department, COUNT(r.id) as report_count
        FROM users u
        LEFT JOIN reports r ON u.id = r.user_id
        WHERE u.role = 'Сотрудник' AND u.department IS NOT NULL AND u.department != ''
        GROUP BY u.department
        ORDER BY report_count DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return []
    
    total = sum(row[1] for row in rows)
    
    return [
        {
            "department": row[0],
            "report_count": row[1],
            "percentage": round((row[1] / total) * 100) if total > 0 else 0
        }
        for row in rows
    ]

def get_company_burnout_stats() -> Dict[str, Any]:
    """
    Получает статистику по выгоранию по всей компании
    
    Возвращает:
        dict: {
            "avg_burnout": средний burnout по компании,
            "departments": список отделов с их burnout,
            "high_burnout_employees": сотрудники с высоким выгоранием (>0.5)
        }
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Средний burnout по компании (по последним отчётам)
    cursor.execute('''
        SELECT AVG(ar.burnout_index)
        FROM analysis_results ar
        JOIN reports r ON ar.report_id = r.id
        WHERE ar.timestamp = (
            SELECT MAX(ar2.timestamp) 
            FROM analysis_results ar2 
            JOIN reports r2 ON ar2.report_id = r2.id 
            WHERE r2.user_id = r.user_id
        )
    ''')
    avg_burnout = cursor.fetchone()[0] or 0.0
    
    # Burnout по отделам
    cursor.execute('''
        SELECT u.department, AVG(ar.burnout_index) as avg_burnout
        FROM users u
        JOIN reports r ON u.id = r.user_id
        JOIN analysis_results ar ON r.id = ar.report_id
        WHERE ar.timestamp = (
            SELECT MAX(ar2.timestamp) 
            FROM analysis_results ar2 
            JOIN reports r2 ON ar2.report_id = r2.id 
            WHERE r2.user_id = r.user_id
        )
        AND u.role = 'Сотрудник'
        GROUP BY u.department
        ORDER BY avg_burnout DESC
    ''')
    dept_rows = cursor.fetchall()
    
    # Сотрудники с высоким выгоранием
    cursor.execute('''
        SELECT u.id, u.full_name, u.department, ar.burnout_index
        FROM users u
        JOIN reports r ON u.id = r.user_id
        JOIN analysis_results ar ON r.id = ar.report_id
        WHERE ar.timestamp = (
            SELECT MAX(ar2.timestamp) 
            FROM analysis_results ar2 
            JOIN reports r2 ON ar2.report_id = r2.id 
            WHERE r2.user_id = r.user_id
        )
        AND ar.burnout_index > 0.5
        AND u.role = 'Сотрудник'
        ORDER BY ar.burnout_index DESC
    ''')
    high_rows = cursor.fetchall()
    conn.close()
    
    return {
        "avg_burnout": round(avg_burnout, 4),
        "departments": [
            {"department": row[0], "burnout": round(row[1], 4)} 
            for row in dept_rows
        ],
        "high_burnout_employees": [
            {"id": row[0], "name": row[1], "department": row[2], "burnout": round(row[3], 4)}
            for row in high_rows
        ]
    }

# ============= НОВЫЕ ФУНКЦИИ ДЛЯ HR =============

def get_department_burnout_trend(department: str, days: int = 30) -> List[Dict[str, Any]]:
    """
    Получает динамику среднего burnout индекса по отделу за последние N дней
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DATE(r.timestamp) as date, AVG(ar.burnout_index) as avg_burnout
        FROM reports r
        JOIN analysis_results ar ON r.id = ar.report_id
        JOIN users u ON r.user_id = u.id
        WHERE u.department = ? AND u.role = 'Сотрудник'
        GROUP BY DATE(r.timestamp)
        ORDER BY date DESC
        LIMIT ?
    ''', (department, days))
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {"date": row[0], "burnout": round(row[1], 4)}
        for row in reversed(rows)  # от старых к новым
    ]


def get_all_departments_burnout_trend(days: int = 30) -> Dict[str, List[Dict[str, Any]]]:
    """
    Получает динамику burnout по всем отделам
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.department, DATE(r.timestamp) as date, AVG(ar.burnout_index) as avg_burnout
        FROM reports r
        JOIN analysis_results ar ON r.id = ar.report_id
        JOIN users u ON r.user_id = u.id
        WHERE u.role = 'Сотрудник' AND u.department IS NOT NULL
        GROUP BY u.department, DATE(r.timestamp)
        ORDER BY date DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    result = {}
    for row in rows:
        dept = row[0]
        if dept not in result:
            result[dept] = []
        result[dept].append({
            "date": row[1],
            "burnout": round(row[2], 4)
        })
    
    # Оставляем только последние days дней для каждого отдела
    for dept in result:
        result[dept] = result[dept][-days:]
    
    return result


def get_company_burnout_history(days: int = 30) -> List[Dict[str, Any]]:
    """
    Получает историю среднего burnout по компании
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DATE(r.timestamp) as date, AVG(ar.burnout_index) as avg_burnout
        FROM reports r
        JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id IN (SELECT id FROM users WHERE role = 'Сотрудник')
        GROUP BY DATE(r.timestamp)
        ORDER BY date DESC
        LIMIT ?
    ''', (days,))
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {"date": row[0], "burnout": round(row[1], 4)}
        for row in reversed(rows)
    ]


def get_period_comparison(department: str = None) -> Dict[str, Any]:
    """
    Сравнивает средний wellbeing за текущий и предыдущий периоды.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    now = datetime.now()
    
    # Вариант А: Сравнение календарных месяцев
    current_month_start = datetime(now.year, now.month, 1).strftime('%Y-%m-%d')
    current_month_end = now.strftime('%Y-%m-%d')
    
    # Предыдущий месяц
    if now.month == 1:
        last_month_start = datetime(now.year - 1, 12, 1).strftime('%Y-%m-%d')
        last_month_end = datetime(now.year - 1, 12, 31).strftime('%Y-%m-%d')
    else:
        last_month_start = datetime(now.year, now.month - 1, 1).strftime('%Y-%m-%d')
        last_month_end = (datetime(now.year, now.month, 1) - timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Получаем wellbeing (1 - burnout_index) * 100
    if department:
        query = '''
            SELECT AVG((1 - ar.burnout_index) * 100), COUNT(DISTINCT r.user_id)
            FROM reports r
            JOIN analysis_results ar ON r.id = ar.report_id
            JOIN users u ON r.user_id = u.id
            WHERE u.department = ? 
                AND DATE(r.timestamp) >= ? 
                AND DATE(r.timestamp) <= ?
                AND ar.burnout_index IS NOT NULL
        '''
        cursor.execute(query, (department, current_month_start, current_month_end))
        current_avg = cursor.fetchone()
        cursor.execute(query, (department, last_month_start, last_month_end))
        last_avg = cursor.fetchone()
    else:
        query = '''
            SELECT AVG((1 - ar.burnout_index) * 100), COUNT(DISTINCT r.user_id)
            FROM reports r
            JOIN analysis_results ar ON r.id = ar.report_id
            WHERE DATE(r.timestamp) >= ? 
                AND DATE(r.timestamp) <= ?
                AND ar.burnout_index IS NOT NULL
        '''
        cursor.execute(query, (current_month_start, current_month_end))
        current_avg = cursor.fetchone()
        cursor.execute(query, (last_month_start, last_month_end))
        last_avg = cursor.fetchone()
    
    conn.close()
    
    current_score = current_avg[0] if current_avg and current_avg[0] is not None else 0
    last_score = last_avg[0] if last_avg and last_avg[0] is not None else 0
    change = current_score - last_score
    
    return {
        "current": round(current_score),    # wellbeing за текущий период (%)
        "previous": round(last_score),      # wellbeing за прошлый период (%)
        "change": round(change, 1),         # изменение в процентах
        "trend": "up" if change > 0 else "down" if change < 0 else "stable"
    }

def get_user_score_trend(user_id: int, days: int = 7) -> Dict[str, Any]:
    """
    Рассчитывает тренд изменения показателя сотрудника за N дней
    
    Возвращает:
        dict: {
            "trend": "up" / "down" / "stable",
            "change": абсолютное изменение в процентах,
            "icon": "↑" / "↓" / "→",
            "color": "success" / "error" / "neutral"
        }
        Если изменение 0 или меньше 3% - возвращает None
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Получаем отчёты за последние N+7 дней (чтобы было с запасом)
    cursor.execute('''
        SELECT r.timestamp, ar.confidence
        FROM reports r
        JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id = ?
        ORDER BY r.timestamp DESC
        LIMIT ?
    ''', (user_id, days + 7))
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) < 2:
        return None  # Недостаточно данных
    
    # Берём период days дней назад
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    old_scores = []
    new_scores = []
    
    for row in rows:
        if row[0][:10] < cutoff_date:
            old_scores.append(row[1])
        else:
            new_scores.append(row[1])
    
    if not old_scores or not new_scores:
        return None  # Недостаточно данных для сравнения
    
    old_avg = sum(old_scores) / len(old_scores) * 100
    new_avg = sum(new_scores) / len(new_scores) * 100
    change = new_avg - old_avg
    
    # Возвращаем None если изменение меньше 3% или равно 0
    if abs(change) <= 3:
        return None
    
    if change > 0:
        return {"trend": "up", "change": round(change), "icon": "↑", "color": "success"}
    else:
        return {"trend": "down", "change": round(abs(change)), "icon": "↓", "color": "error"}
    


def get_departments_burnout_history(days: int = 30) -> Dict[str, List[Dict[str, Any]]]:
    """
    Получает историю среднего burnout по каждому отделу
    
    Возвращает:
        {
            "IT": [{"date": "2024-01-01", "burnout": 0.25}, ...],
            "Маркетинг": [...],
            ...
        }
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.department, DATE(r.timestamp) as date, AVG(ar.burnout_index) as avg_burnout
        FROM reports r
        JOIN analysis_results ar ON r.id = ar.report_id
        JOIN users u ON r.user_id = u.id
        WHERE u.role = 'Сотрудник' 
            AND u.department IS NOT NULL 
            AND u.department != 'HR'
        GROUP BY u.department, DATE(r.timestamp)
        ORDER BY date ASC
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    result = {}
    for row in rows:
        dept = row[0]
        if dept not in result:
            result[dept] = []
        result[dept].append({
            "date": row[1],
            "burnout": round(row[2], 4)
        })
    
    # Оставляем только последние days дней для каждого отдела
    for dept in result:
        result[dept] = result[dept][-days:]
    
    return result


def get_user_weighted_wellbeing(user_id: int) -> float:
    """
    Возвращает взвешенное общее самочувствие сотрудника (0-100)
    Основывается на burnout_index, а не на сыром confidence
    """
    reports = get_user_reports(user_id)
    if not reports:
        return 50.0  # нейтральное значение по умолчанию
    
    # Используем ту же логику взвешивания, что и раньше, но на burnout_index
    sorted_reports = sorted(reports, key=lambda x: x['timestamp'])
    
    total_weight = 0
    weighted_sum = 0
    n = len(sorted_reports)
    decay_factor = 0.75  # чуть выше, чем было, т.к. burnout более стабильная метрика
    
    for i, report in enumerate(sorted_reports):
        burnout = report.get('burnout_index', 0.5)
        weight = decay_factor ** (n - i - 1)
        weighted_sum += (1 - burnout) * weight   # ← ключевой момент
        total_weight += weight
    
    weighted_wellbeing = weighted_sum / total_weight if total_weight > 0 else 0.5
    return round(weighted_wellbeing * 100, 1)