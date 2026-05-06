import os
import hashlib
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from dotenv import load_dotenv

load_dotenv()

# Получаем DATABASE_URL из переменных окружения
# Пример для локального PostgreSQL: postgresql://user:password@localhost:5432/emotion_db
# Пример для Render: postgresql://user:password@host:port/dbname
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/emotion_db')

# Создаём пул соединений для производительности
pool = None

def get_db_connection():
    """Получает соединение из пула"""
    global pool
    if pool is None:
        pool = SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=DATABASE_URL
        )
    return pool.getconn()

def release_db_connection(conn):
    """Возвращает соединение в пул"""
    global pool
    if pool:
        pool.putconn(conn)

def init_db():
    """Создаёт таблицы, если они ещё не существуют"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
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
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            text TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица результатов анализа
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analysis_results (
            id SERIAL PRIMARY KEY,
            report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            emotion_label TEXT NOT NULL,
            confidence REAL NOT NULL,
            burnout_index REAL NOT NULL,
            all_scores TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица сессий
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Создаём индексы для производительности
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_reports_user_id ON reports(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_reports_timestamp ON reports(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_analysis_results_report_id ON analysis_results(report_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)')
    
    conn.commit()
    cursor.close()
    release_db_connection(conn)

def hash_password(password):
    """Шифрует пароль в SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def add_user(full_name, username, password, role, department="General"):
    """Добавляет нового пользователя в базу"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        pw_hash = hash_password(password)
        cursor.execute('''
            INSERT INTO users (full_name, username, password_hash, role, department) 
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        ''', (full_name, username, pw_hash, role, department))
        user_id = cursor.fetchone()[0]
        conn.commit()
        return user_id
    except psycopg2.IntegrityError:
        conn.rollback()
        return None
    finally:
        cursor.close()
        release_db_connection(conn)

def verify_user(username, password) -> Optional[Tuple]:
    """Проверяет данные пользователя при входе"""
    conn = get_db_connection()
    cursor = conn.cursor()
    pw_hash = hash_password(password)
    cursor.execute('''
        SELECT id, full_name, role, department FROM users 
        WHERE username = %s AND password_hash = %s
    ''', (username, pw_hash))
    user = cursor.fetchone()
    cursor.close()
    release_db_connection(conn)
    return user

def save_report(user_id: int, text: str) -> Optional[int]:
    """Сохраняет отчет пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO reports (user_id, text, timestamp) 
            VALUES (%s, %s, %s) RETURNING id
        ''', (user_id, text, datetime.now()))
        report_id = cursor.fetchone()[0]
        conn.commit()
        return report_id
    except Exception as e:
        print(f"Ошибка при сохранении отчета: {e}")
        conn.rollback()
        return None
    finally:
        cursor.close()
        release_db_connection(conn)

def save_analysis_result(report_id: int, emotion_label: str, confidence: float, 
                        burnout_index: float, all_scores: str) -> bool:
    """Сохраняет результаты анализа"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO analysis_results 
            (report_id, emotion_label, confidence, burnout_index, all_scores, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (report_id, emotion_label, confidence, burnout_index, all_scores, datetime.now()))
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка при сохранении результатов: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        release_db_connection(conn)

def get_user_reports(user_id: int) -> List[Dict[str, Any]]:
    """Получает все отчеты пользователя с результатами анализа"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute('''
        SELECT r.id, r.text, r.timestamp, ar.emotion_label as emotion, 
               ar.confidence, ar.burnout_index
        FROM reports r
        LEFT JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id = %s
        ORDER BY r.timestamp DESC
    ''', (user_id,))
    rows = cursor.fetchall()
    cursor.close()
    release_db_connection(conn)
    return [dict(row) for row in rows]

def get_user_reports_history(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """Получает историю отчётов пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute('''
        SELECT r.id, r.text, r.timestamp, ar.emotion_label as emotion, 
               ar.confidence, ar.burnout_index
        FROM reports r
        LEFT JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id = %s
        ORDER BY r.timestamp DESC
        LIMIT %s
    ''', (user_id, limit))
    rows = cursor.fetchall()
    cursor.close()
    release_db_connection(conn)
    return [dict(row) for row in rows]

def get_user_department(user_id: int) -> str:
    """Получает отдел пользователя по его ID"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT department FROM users WHERE id = %s', (user_id,))
    result = cursor.fetchone()
    cursor.close()
    release_db_connection(conn)
    return result[0] if result else ""

def get_all_users() -> List[Dict[str, Any]]:
    """Получает всех пользователей системы"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute('''
        SELECT id, full_name, username, role, department 
        FROM users 
        ORDER BY full_name
    ''')
    rows = cursor.fetchall()
    cursor.close()
    release_db_connection(conn)
    return [dict(row) for row in rows]

def get_users_by_department(department: str) -> List[Dict[str, Any]]:
    """Получает всех пользователей отдела"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        "SELECT id, full_name, role, department FROM users WHERE department = %s",
        (department,)
    )
    rows = cursor.fetchall()
    cursor.close()
    release_db_connection(conn)
    return [dict(row) for row in rows]

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Получает информацию о пользователе по ID"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute('''
        SELECT id, full_name as name, role, department FROM users WHERE id = %s
    ''', (user_id,))
    user = cursor.fetchone()
    cursor.close()
    release_db_connection(conn)
    return dict(user) if user else None

def save_session(user_id: int, token: str, days: int = 7) -> bool:
    """Сохраняет токен сессии в БД"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        expires_at = datetime.now() + timedelta(days=days)
        cursor.execute('''
            INSERT INTO sessions (user_id, token, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (token) DO UPDATE SET 
                user_id = EXCLUDED.user_id,
                expires_at = EXCLUDED.expires_at
        ''', (user_id, token, expires_at))
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка при сохранении сессии: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        release_db_connection(conn)

def get_session_by_token(token: str) -> Optional[Dict[str, Any]]:
    """Получает данные сессии по токену"""
    if not token:
        return None
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute('''
            SELECT s.user_id, s.token, s.expires_at, u.full_name as name, u.role, u.department
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = %s AND s.expires_at > NOW()
        ''', (token,))
        session = cursor.fetchone()
        return dict(session) if session else None
    except Exception as e:
        print(f"Ошибка при получении сессии: {e}")
        return None
    finally:
        cursor.close()
        release_db_connection(conn)

def delete_session(token: str) -> bool:
    """Удаляет токен сессии"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM sessions WHERE token = %s', (token,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка при удалении сессии: {e}")
        return False
    finally:
        cursor.close()
        release_db_connection(conn)

# Остальные функции остаются такими же, только синтаксис запросов меняем с ? на %s

def get_team_with_reports(department: str) -> List[Dict[str, Any]]:
    """Получает всех сотрудников отдела с их последним отчётом"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
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
        LEFT JOIN LATERAL (
            SELECT r.user_id, ar.emotion_label, ar.confidence, ar.burnout_index, ar.timestamp
            FROM reports r
            JOIN analysis_results ar ON r.id = ar.report_id
            WHERE r.user_id = u.id
            ORDER BY ar.timestamp DESC
            LIMIT 1
        ) ar ON true
        WHERE u.department = %s AND u.role = 'Сотрудник'
        ORDER BY u.full_name
    ''', (department,))
    rows = cursor.fetchall()
    cursor.close()
    release_db_connection(conn)
    
    results = []
    for row in rows:
        results.append({
            'id': row['id'],
            'full_name': row['full_name'],
            'role': row['role'],
            'department': row['department'],
            'last_emotion': row['last_emotion'],
            'last_confidence': row['last_confidence'],
            'last_burnout': row['last_burnout'],
            'last_report_date': row['last_report_date'],
            'report_count': row['report_count'],
            'last_score': int(row['last_confidence'] * 100) if row['last_confidence'] is not None else None,
            'has_reports': row['report_count'] > 0
        })
    return results

# Продолжение следует... (остальные функции аналогично переводятся на %s вместо ?)

def get_user_reports_paginated(user_id: int, limit: int = 10, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """Получает отчёты пользователя с пагинацией"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM reports WHERE user_id = %s', (user_id,))
    total = cursor.fetchone()[0]
    
    cursor.execute('''
        SELECT r.id, r.text, r.timestamp, ar.emotion_label, ar.confidence, ar.burnout_index
        FROM reports r
        LEFT JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id = %s
        ORDER BY r.timestamp DESC
        LIMIT %s OFFSET %s
    ''', (user_id, limit, offset))
    rows = cursor.fetchall()
    cursor.close()
    release_db_connection(conn)
    
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

# ВНИМАНИЕ: Все остальные функции из оригинального database.py 
# нужно переписать аналогично, заменяя ? на %s 
# и используя get_db_connection() / release_db_connection()

def get_all_team_reports(department: str) -> List[Dict[str, Any]]:
    """Получает все отчёты всех сотрудников отдела"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute('''
        SELECT 
            r.id,
            r.user_id,
            u.full_name as user_name,
            r.text,
            r.timestamp,
            ar.emotion_label as emotion,
            ar.confidence,
            ar.burnout_index
        FROM reports r
        JOIN users u ON r.user_id = u.id
        LEFT JOIN analysis_results ar ON r.id = ar.report_id
        WHERE u.department = %s AND u.role = 'Сотрудник'
        ORDER BY r.timestamp DESC
    ''', (department,))
    rows = cursor.fetchall()
    cursor.close()
    release_db_connection(conn)
    return [dict(row) for row in rows]

def calculate_weighted_score(reports: List[Dict[str, Any]], decay_factor: float = 0.7) -> float:
    """Рассчитывает взвешенное среднее confidence"""
    if not reports:
        return 0.0
    
    sorted_reports = sorted(reports, key=lambda x: x['timestamp'])
    
    total_weight = 0
    weighted_sum = 0
    n = len(sorted_reports)
    
    for i, report in enumerate(sorted_reports):
        weight = decay_factor ** (n - i - 1)
        weighted_sum += report['confidence'] * weight
        total_weight += weight
    
    return weighted_sum / total_weight if total_weight > 0 else 0

def get_user_weighted_score(user_id: int) -> float:
    """Возвращает взвешенный средний confidence пользователя в процентах"""
    reports = get_user_reports(user_id)
    if not reports:
        return 0.0
    return calculate_weighted_score(reports) * 100

def get_team_weighted_scores(department: str) -> List[float]:
    """Возвращает список взвешенных баллов всех сотрудников отдела"""
    team = get_team_with_reports(department)
    scores = []
    for member in team:
        weighted = get_user_weighted_score(member['id'])
        scores.append(weighted)
    return scores

def calculate_weighted_score_for_list(reports_list: List[dict], decay_factor: float = 0.7) -> float:
    """Упрощённая версия для списка словарей"""
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

def get_user_burnout_trend(user_id: int, days: int = 30) -> Dict[str, Any]:
    """Получает динамику burnout индекса пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.timestamp, ar.burnout_index
        FROM reports r
        JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id = %s
        ORDER BY r.timestamp DESC
        LIMIT %s
    ''', (user_id, days))
    rows = cursor.fetchall()
    cursor.close()
    release_db_connection(conn)
    
    if not rows:
        return {"current": 0.0, "trend": 0.0, "history": []}
    
    history = [{"date": row[0].strftime('%Y-%m-%d'), "burnout": row[1]} for row in reversed(rows)]
    current = rows[0][1] if rows else 0.0
    
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

def get_company_burnout_history(days: int = 30) -> List[Dict[str, Any]]:
    """Получает историю среднего burnout по компании"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DATE(r.timestamp) as date, AVG(ar.burnout_index) as avg_burnout
        FROM reports r
        JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id IN (SELECT id FROM users WHERE role = 'Сотрудник')
        GROUP BY DATE(r.timestamp)
        ORDER BY date DESC
        LIMIT %s
    ''', (days,))
    rows = cursor.fetchall()
    cursor.close()
    release_db_connection(conn)
    
    result = []
    for row in reversed(rows):
        result.append({"date": row[0].strftime('%Y-%m-%d') if hasattr(row[0], 'strftime') else row[0], "burnout": round(row[1], 4)})
    return result

def get_departments_burnout_history(days: int = 30) -> Dict[str, List[Dict[str, Any]]]:
    """Получает историю среднего burnout по каждому отделу"""
    conn = get_db_connection()
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
    cursor.close()
    release_db_connection(conn)
    
    result = {}
    for row in rows:
        dept = row[0]
        date = row[1].strftime('%Y-%m-%d') if hasattr(row[1], 'strftime') else row[1]
        if dept not in result:
            result[dept] = []
        result[dept].append({"date": date, "burnout": round(row[2], 4)})
    
    for dept in result:
        result[dept] = result[dept][-days:]
    
    return result

def get_department_reports_stats() -> List[Dict[str, Any]]:
    """Получает статистику количества отчётов по отделам"""
    conn = get_db_connection()
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
    cursor.close()
    release_db_connection(conn)
    
    if not rows:
        return []
    
    total = sum(row[1] for row in rows)
    
    return [
        {"department": row[0], "report_count": row[1], "percentage": round((row[1] / total) * 100) if total > 0 else 0}
        for row in rows
    ]

def get_company_burnout_stats() -> Dict[str, Any]:
    """Получает статистику по выгоранию по всей компании"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
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
    cursor.close()
    release_db_connection(conn)
    
    return {
        "avg_burnout": round(avg_burnout, 4),
        "departments": [{"department": row[0], "burnout": round(row[1], 4)} for row in dept_rows],
        "high_burnout_employees": [{"id": row[0], "name": row[1], "department": row[2], "burnout": round(row[3], 4)} for row in high_rows]
    }

def get_period_comparison(department: str = None) -> Dict[str, Any]:
    """Сравнивает средний wellbeing за текущий и предыдущий периоды"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now()
    current_month_start = datetime(now.year, now.month, 1).strftime('%Y-%m-%d')
    current_month_end = now.strftime('%Y-%m-%d')
    
    if now.month == 1:
        last_month_start = datetime(now.year - 1, 12, 1).strftime('%Y-%m-%d')
        last_month_end = datetime(now.year - 1, 12, 31).strftime('%Y-%m-%d')
    else:
        last_month_start = datetime(now.year, now.month - 1, 1).strftime('%Y-%m-%d')
        last_month_end = (datetime(now.year, now.month, 1) - timedelta(days=1)).strftime('%Y-%m-%d')
    
    if department:
        query = '''
            SELECT AVG((1 - ar.burnout_index) * 100)
            FROM reports r
            JOIN analysis_results ar ON r.id = ar.report_id
            JOIN users u ON r.user_id = u.id
            WHERE u.department = %s 
                AND DATE(r.timestamp) >= %s 
                AND DATE(r.timestamp) <= %s
                AND ar.burnout_index IS NOT NULL
        '''
        cursor.execute(query, (department, current_month_start, current_month_end))
        current_avg = cursor.fetchone()
        cursor.execute(query, (department, last_month_start, last_month_end))
        last_avg = cursor.fetchone()
    else:
        query = '''
            SELECT AVG((1 - ar.burnout_index) * 100)
            FROM reports r
            JOIN analysis_results ar ON r.id = ar.report_id
            WHERE DATE(r.timestamp) >= %s 
                AND DATE(r.timestamp) <= %s
                AND ar.burnout_index IS NOT NULL
        '''
        cursor.execute(query, (current_month_start, current_month_end))
        current_avg = cursor.fetchone()
        cursor.execute(query, (last_month_start, last_month_end))
        last_avg = cursor.fetchone()
    
    cursor.close()
    release_db_connection(conn)
    
    current_score = current_avg[0] if current_avg and current_avg[0] is not None else 0
    last_score = last_avg[0] if last_avg and last_avg[0] is not None else 0
    change = current_score - last_score
    
    return {
        "current": round(current_score),
        "previous": round(last_score),
        "change": round(change, 1),
        "trend": "up" if change > 0 else "down" if change < 0 else "stable"
    }

def get_user_score_trend(user_id: int, days: int = 7) -> Optional[Dict[str, Any]]:
    """Рассчитывает тренд изменения показателя сотрудника"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT r.timestamp, ar.confidence
        FROM reports r
        JOIN analysis_results ar ON r.id = ar.report_id
        WHERE r.user_id = %s
        ORDER BY r.timestamp DESC
        LIMIT %s
    ''', (user_id, days + 7))
    rows = cursor.fetchall()
    cursor.close()
    release_db_connection(conn)
    
    if len(rows) < 2:
        return None
    
    cutoff_date = datetime.now() - timedelta(days=days)
    
    old_scores = []
    new_scores = []
    
    for row in rows:
        ts = row[0] if hasattr(row[0], 'strftime') else datetime.strptime(row[0][:10], '%Y-%m-%d')
        if ts < cutoff_date:
            old_scores.append(row[1])
        else:
            new_scores.append(row[1])
    
    if not old_scores or not new_scores:
        return None
    
    old_avg = sum(old_scores) / len(old_scores) * 100
    new_avg = sum(new_scores) / len(new_scores) * 100
    change = new_avg - old_avg
    
    if abs(change) <= 3:
        return None
    
    if change > 0:
        return {"trend": "up", "change": round(change), "icon": "↑", "color": "success"}
    else:
        return {"trend": "down", "change": round(abs(change)), "icon": "↓", "color": "error"}

def get_user_weighted_wellbeing(user_id: int) -> float:
    """Возвращает взвешенное общее самочувствие сотрудника"""
    reports = get_user_reports(user_id)
    if not reports:
        return 50.0
    
    sorted_reports = sorted(reports, key=lambda x: x['timestamp'])
    
    total_weight = 0
    weighted_sum = 0
    n = len(sorted_reports)
    decay_factor = 0.75
    
    for i, report in enumerate(sorted_reports):
        burnout = report.get('burnout_index', 0.5)
        weight = decay_factor ** (n - i - 1)
        weighted_sum += (1 - burnout) * weight
        total_weight += weight
    
    weighted_wellbeing = weighted_sum / total_weight if total_weight > 0 else 0.5
    return round(weighted_wellbeing * 100, 1)


# Добавим функцию для миграции данных из SQLite в PostgreSQL (если нужно)
def migrate_from_sqlite(sqlite_path: str):
    """Мигрирует данные из SQLite в PostgreSQL"""
    import sqlite3
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()
    
    pg_conn = get_db_connection()
    pg_cursor = pg_conn.cursor()
    
    # Миграция users
    sqlite_cursor.execute('SELECT * FROM users')
    for row in sqlite_cursor.fetchall():
        pg_cursor.execute('''
            INSERT INTO users (id, full_name, username, password_hash, role, department)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        ''', (row['id'], row['full_name'], row['username'], 
              row['password_hash'], row['role'], row['department']))
    
    # Миграция reports
    sqlite_cursor.execute('SELECT * FROM reports')
    for row in sqlite_cursor.fetchall():
        pg_cursor.execute('''
            INSERT INTO reports (id, user_id, text, timestamp)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        ''', (row['id'], row['user_id'], row['text'], row['timestamp']))
    
    # Миграция analysis_results
    sqlite_cursor.execute('SELECT * FROM analysis_results')
    for row in sqlite_cursor.fetchall():
        pg_cursor.execute('''
            INSERT INTO analysis_results (id, report_id, emotion_label, confidence, burnout_index, all_scores, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        ''', (row['id'], row['report_id'], row['emotion_label'],
              row['confidence'], row['burnout_index'], row['all_scores'], row['timestamp']))
    
    # Миграция sessions
    sqlite_cursor.execute('SELECT * FROM sessions')
    for row in sqlite_cursor.fetchall():
        pg_cursor.execute('''
            INSERT INTO sessions (id, user_id, token, expires_at, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        ''', (row['id'], row['user_id'], row['token'], row['expires_at'], row['created_at']))
    
    pg_conn.commit()
    pg_cursor.close()
    release_db_connection(pg_conn)
    sqlite_conn.close()
    print("Миграция завершена!")