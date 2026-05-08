"""
Слой доступа к данным (PostgreSQL через psycopg2).
Все операции с БД — здесь. Бизнес-логика — в services/.
"""
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

from backend.config import DATABASE_URL, DB_POOL_MIN_CONN, DB_POOL_MAX_CONN, SCORE_DECAY_FACTOR, WELLBEING_DECAY_FACTOR
from backend.utils.formatting import safe_timestamp

print("Подключение к базе данных...")

pool: Optional[SimpleConnectionPool] = None


def get_db_connection():
    global pool
    if pool is None:
        pool = SimpleConnectionPool(minconn=DB_POOL_MIN_CONN, maxconn=DB_POOL_MAX_CONN, dsn=DATABASE_URL)
    return pool.getconn()


def release_db_connection(conn):
    global pool
    if pool:
        pool.putconn(conn)


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                full_name TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                department TEXT DEFAULT 'General'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_results (
                id SERIAL PRIMARY KEY,
                report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                emotion_label TEXT NOT NULL,
                confidence REAL NOT NULL,
                burnout_index REAL NOT NULL,
                all_scores TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_reports_user_id ON reports(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_reports_timestamp ON reports(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_analysis_results_report_id ON analysis_results(report_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)",
        ]:
            cursor.execute(sql)
        conn.commit()
    finally:
        cursor.close()
        release_db_connection(conn)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# ПОЛЬЗОВАТЕЛИ
# ─────────────────────────────────────────────────────────────────────────────

def add_user(full_name: str, username: str, password: str, role: str, department: str = "General") -> Optional[int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (full_name, username, password_hash, role, department) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (full_name, username, hash_password(password), role, department),
        )
        user_id = cursor.fetchone()[0]
        conn.commit()
        return user_id
    except psycopg2.IntegrityError:
        conn.rollback()
        return None
    finally:
        cursor.close()
        release_db_connection(conn)


def verify_user(username: str, password: str) -> Optional[Tuple]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, full_name, role, department FROM users WHERE username=%s AND password_hash=%s",
            (username, hash_password(password)),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        release_db_connection(conn)


def get_all_users() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT id, full_name, username, role, department FROM users ORDER BY full_name")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()
        release_db_connection(conn)


def get_users_by_department(department: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            "SELECT id, full_name, role, department FROM users WHERE department = %s",
            (department,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()
        release_db_connection(conn)


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT id, full_name AS name, role, department FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        cursor.close()
        release_db_connection(conn)


def get_user_department(user_id: int) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT department FROM users WHERE id = %s", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else ""
    finally:
        cursor.close()
        release_db_connection(conn)


# ─────────────────────────────────────────────────────────────────────────────
# СЕССИИ
# ─────────────────────────────────────────────────────────────────────────────

def save_session(user_id: int, token: str, days: int = 7) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        expires_at = datetime.now() + timedelta(days=days)
        cursor.execute(
            """INSERT INTO sessions (user_id, token, expires_at) VALUES (%s,%s,%s)
               ON CONFLICT (token) DO UPDATE SET user_id=EXCLUDED.user_id, expires_at=EXCLUDED.expires_at""",
            (user_id, token, expires_at),
        )
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
    if not token:
        return None
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            """SELECT s.user_id, s.token, s.expires_at, u.full_name AS name, u.role, u.department
               FROM sessions s JOIN users u ON s.user_id = u.id
               WHERE s.token = %s AND s.expires_at > NOW()""",
            (token,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"Ошибка при получении сессии: {e}")
        return None
    finally:
        cursor.close()
        release_db_connection(conn)


def delete_session(token: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка при удалении сессии: {e}")
        return False
    finally:
        cursor.close()
        release_db_connection(conn)


# ─────────────────────────────────────────────────────────────────────────────
# ОТЧЁТЫ
# ─────────────────────────────────────────────────────────────────────────────

def save_report(user_id: int, text: str) -> Optional[int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO reports (user_id, text, timestamp) VALUES (%s,%s,%s) RETURNING id",
            (user_id, text, datetime.now()),
        )
        report_id = cursor.fetchone()[0]
        conn.commit()
        return report_id
    except Exception as e:
        print(f"Ошибка при сохранении отчёта: {e}")
        conn.rollback()
        return None
    finally:
        cursor.close()
        release_db_connection(conn)


def save_analysis_result(report_id: int, emotion_label: str, confidence: float,
                         burnout_index: float, all_scores: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO analysis_results
               (report_id, emotion_label, confidence, burnout_index, all_scores, timestamp)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (report_id, emotion_label, confidence, burnout_index, all_scores, datetime.now()),
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка при сохранении результатов анализа: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        release_db_connection(conn)


def _fetch_reports_with_analysis(cursor, where_clause: str, params: tuple) -> List[Dict[str, Any]]:
    """Вспомогательный метод: общий JOIN для получения отчётов с анализом."""
    cursor.execute(
        f"""
        SELECT r.id, r.text, r.timestamp, ar.emotion_label AS emotion,
               ar.confidence, ar.burnout_index
        FROM reports r
        LEFT JOIN analysis_results ar ON r.id = ar.report_id
        {where_clause}
        ORDER BY r.timestamp DESC
        """,
        params,
    )
    rows = cursor.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["timestamp"] = safe_timestamp(d["timestamp"])
        result.append(d)
    return result


def get_user_reports(user_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        return _fetch_reports_with_analysis(cursor, "WHERE r.user_id = %s", (user_id,))
    finally:
        cursor.close()
        release_db_connection(conn)


def get_user_reports_history(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            """
            SELECT r.id, r.text, r.timestamp, ar.emotion_label AS emotion,
                   ar.confidence, ar.burnout_index
            FROM reports r
            LEFT JOIN analysis_results ar ON r.id = ar.report_id
            WHERE r.user_id = %s
            ORDER BY r.timestamp DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        result = []
        for row in cursor.fetchall():
            d = dict(row)
            d["timestamp"] = safe_timestamp(d["timestamp"])
            result.append(d)
        return result
    finally:
        cursor.close()
        release_db_connection(conn)


def get_user_reports_paginated(user_id: int, limit: int = 10, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM reports WHERE user_id = %s", (user_id,))
        total = cursor.fetchone()[0]
        cursor.execute(
            """SELECT r.id, r.text, r.timestamp, ar.emotion_label, ar.confidence, ar.burnout_index
               FROM reports r
               LEFT JOIN analysis_results ar ON r.id = ar.report_id
               WHERE r.user_id = %s
               ORDER BY r.timestamp DESC
               LIMIT %s OFFSET %s""",
            (user_id, limit, offset),
        )
        rows = cursor.fetchall()
        return (
            [
                {
                    "id": r[0], "text": r[1], "timestamp": safe_timestamp(r[2]),
                    "emotion": r[3], "confidence": r[4], "burnout_index": r[5],
                }
                for r in rows
            ],
            total,
        )
    finally:
        cursor.close()
        release_db_connection(conn)


def get_all_team_reports(department: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            """
            SELECT r.id, r.user_id, u.full_name AS user_name,
                   r.text, r.timestamp,
                   ar.emotion_label AS emotion,
                   ar.confidence, ar.burnout_index
            FROM reports r
            JOIN users u ON r.user_id = u.id
            LEFT JOIN analysis_results ar ON r.id = ar.report_id
            WHERE u.department = %s AND u.role = 'Сотрудник'
            ORDER BY r.timestamp DESC
            """,
            (department,),
        )
        result = []
        for row in cursor.fetchall():
            d = dict(row)
            d["timestamp"] = safe_timestamp(d["timestamp"])
            result.append(d)
        return result
    finally:
        cursor.close()
        release_db_connection(conn)


# ─────────────────────────────────────────────────────────────────────────────
# АНАЛИТИКА
# ─────────────────────────────────────────────────────────────────────────────

def get_team_with_reports(department: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            """
            SELECT
                u.id, u.full_name, u.role, u.department,
                ar.emotion_label AS last_emotion,
                ar.confidence    AS last_confidence,
                ar.burnout_index AS last_burnout,
                ar.timestamp     AS last_report_date,
                (SELECT COUNT(*) FROM reports r2 WHERE r2.user_id = u.id) AS report_count
            FROM users u
            LEFT JOIN LATERAL (
                SELECT r.user_id, ar2.emotion_label, ar2.confidence, ar2.burnout_index, ar2.timestamp
                FROM reports r
                JOIN analysis_results ar2 ON r.id = ar2.report_id
                WHERE r.user_id = u.id
                ORDER BY ar2.timestamp DESC
                LIMIT 1
            ) ar ON true
            WHERE u.department = %s AND u.role = 'Сотрудник'
            ORDER BY u.full_name
            """,
            (department,),
        )
        result = []
        for row in cursor.fetchall():
            d = dict(row)
            d["last_report_date"] = safe_timestamp(d.get("last_report_date"))
            d["last_score"] = int(d["last_confidence"] * 100) if d["last_confidence"] is not None else None
            d["has_reports"] = d["report_count"] > 0
            result.append(d)
        return result
    finally:
        cursor.close()
        release_db_connection(conn)


def calculate_weighted_score(reports: List[Dict[str, Any]], decay_factor: float = SCORE_DECAY_FACTOR) -> float:
    if not reports:
        return 0.0
    sorted_reports = sorted(reports, key=lambda x: x["timestamp"])
    n = len(sorted_reports)
    total_weight = weighted_sum = 0.0
    for i, report in enumerate(sorted_reports):
        weight = decay_factor ** (n - i - 1)
        weighted_sum += report["confidence"] * weight
        total_weight += weight
    return weighted_sum / total_weight if total_weight else 0.0


def calculate_weighted_score_for_list(reports_list: List[dict], decay_factor: float = SCORE_DECAY_FACTOR) -> float:
    return calculate_weighted_score(reports_list, decay_factor)


def get_user_weighted_score(user_id: int) -> float:
    reports = get_user_reports(user_id)
    return calculate_weighted_score(reports) * 100 if reports else 0.0


def get_user_weighted_wellbeing(user_id: int) -> float:
    reports = get_user_reports(user_id)
    if not reports:
        return 50.0
    sorted_reports = sorted(reports, key=lambda x: x["timestamp"])
    n = len(sorted_reports)
    total_weight = weighted_sum = 0.0
    for i, report in enumerate(sorted_reports):
        burnout = report.get("burnout_index") or 0.5
        weight = WELLBEING_DECAY_FACTOR ** (n - i - 1)
        weighted_sum += (1 - burnout) * weight
        total_weight += weight
    return round((weighted_sum / total_weight if total_weight else 0.5) * 100, 1)


def get_user_score_trend(user_id: int, days: int = 7) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT r.timestamp, ar.confidence
               FROM reports r
               JOIN analysis_results ar ON r.id = ar.report_id
               WHERE r.user_id = %s
               ORDER BY r.timestamp DESC
               LIMIT %s""",
            (user_id, days + 7),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        release_db_connection(conn)

    if len(rows) < 2:
        return None

    cutoff = datetime.now() - timedelta(days=days)
    old_scores, new_scores = [], []
    for row in rows:
        ts = row[0] if isinstance(row[0], datetime) else datetime.strptime(safe_timestamp(row[0])[:10], "%Y-%m-%d")
        (new_scores if ts >= cutoff else old_scores).append(row[1])

    if not old_scores or not new_scores:
        return None

    change = (sum(new_scores) / len(new_scores) - sum(old_scores) / len(old_scores)) * 100
    if abs(change) <= 3:
        return None

    return {
        "trend": "up" if change > 0 else "down",
        "change": round(abs(change)),
        "icon": "↑" if change > 0 else "↓",
        "color": "success" if change > 0 else "error",
    }


def get_user_burnout_trend(user_id: int, days: int = 30) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT r.timestamp, ar.burnout_index
               FROM reports r
               JOIN analysis_results ar ON r.id = ar.report_id
               WHERE r.user_id = %s
               ORDER BY r.timestamp DESC
               LIMIT %s""",
            (user_id, days),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        release_db_connection(conn)

    if not rows:
        return {"current": 0.0, "trend": 0.0, "history": []}

    history = [{"date": safe_timestamp(row[0])[:10], "burnout": row[1]} for row in reversed(rows)]
    current = rows[0][1]
    trend = current - (sum(r[1] for r in rows[1:]) / len(rows[1:])) if len(rows) > 1 else 0.0
    return {"current": round(current, 4), "trend": round(trend, 4), "history": history}


def get_company_burnout_history(days: int = 30) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT DATE(r.timestamp) AS date, AVG(ar.burnout_index) AS avg_burnout
               FROM reports r
               JOIN analysis_results ar ON r.id = ar.report_id
               WHERE r.user_id IN (SELECT id FROM users WHERE role = 'Сотрудник')
               GROUP BY DATE(r.timestamp)
               ORDER BY date DESC
               LIMIT %s""",
            (days,),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        release_db_connection(conn)
    return [{"date": safe_timestamp(row[0])[:10], "burnout": round(row[1], 4)} for row in reversed(rows)]


def get_departments_burnout_history(days: int = 30) -> Dict[str, List[Dict[str, Any]]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT u.department, DATE(r.timestamp) AS date, AVG(ar.burnout_index) AS avg_burnout
               FROM reports r
               JOIN analysis_results ar ON r.id = ar.report_id
               JOIN users u ON r.user_id = u.id
               WHERE u.role = 'Сотрудник' AND u.department IS NOT NULL AND u.department != 'HR'
               GROUP BY u.department, DATE(r.timestamp)
               ORDER BY date ASC""",
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        release_db_connection(conn)

    result: Dict[str, List] = {}
    for row in rows:
        result.setdefault(row[0], []).append({"date": safe_timestamp(row[1])[:10], "burnout": round(row[2], 4)})
    for dept in result:
        result[dept] = result[dept][-days:]
    return result


def get_department_reports_stats() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT u.department, COUNT(r.id) AS report_count
               FROM users u
               LEFT JOIN reports r ON u.id = r.user_id
               WHERE u.role = 'Сотрудник' AND u.department IS NOT NULL AND u.department != ''
               GROUP BY u.department
               ORDER BY report_count DESC""",
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        release_db_connection(conn)

    if not rows:
        return []
    total = sum(r[1] for r in rows) or 1
    return [
        {"department": r[0], "report_count": r[1], "percentage": round((r[1] / total) * 100)}
        for r in rows
    ]


def get_company_burnout_stats() -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT AVG(sub.burnout_index) FROM (
                   SELECT DISTINCT ON (r.user_id) ar.burnout_index
                   FROM reports r
                   JOIN analysis_results ar ON r.id = ar.report_id
                   ORDER BY r.user_id, r.timestamp DESC
               ) sub""",
        )
        avg_burnout = cursor.fetchone()[0] or 0.0
        cursor.execute(
            """SELECT u.id, u.full_name, u.department, sub.burnout_index
               FROM users u
               JOIN (
                   SELECT DISTINCT ON (r.user_id) r.user_id, ar.burnout_index
                   FROM reports r
                   JOIN analysis_results ar ON r.id = ar.report_id
                   ORDER BY r.user_id, r.timestamp DESC
               ) sub ON u.id = sub.user_id
               WHERE sub.burnout_index > 0.5 AND u.role = 'Сотрудник'
               ORDER BY sub.burnout_index DESC""",
        )
        high_rows = cursor.fetchall()
    finally:
        cursor.close()
        release_db_connection(conn)

    return {
        "avg_burnout": round(avg_burnout, 4),
        "high_burnout_employees": [
            {"id": r[0], "name": r[1], "department": r[2], "burnout": round(r[3], 4)}
            for r in high_rows
        ],
    }


def get_period_comparison(department: str = None) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now()
        curr_start = datetime(now.year, now.month, 1).strftime("%Y-%m-%d")
        curr_end = now.strftime("%Y-%m-%d")
        if now.month == 1:
            prev_start = datetime(now.year - 1, 12, 1).strftime("%Y-%m-%d")
            prev_end = datetime(now.year - 1, 12, 31).strftime("%Y-%m-%d")
        else:
            prev_start = datetime(now.year, now.month - 1, 1).strftime("%Y-%m-%d")
            prev_end = (datetime(now.year, now.month, 1) - timedelta(days=1)).strftime("%Y-%m-%d")

        base_q = """
            SELECT AVG((1 - ar.burnout_index) * 100)
            FROM reports r
            JOIN analysis_results ar ON r.id = ar.report_id
            {join}
            WHERE {dept_filter} DATE(r.timestamp) >= %s AND DATE(r.timestamp) <= %s
                  AND ar.burnout_index IS NOT NULL
        """
        if department:
            q = base_q.format(join="JOIN users u ON r.user_id = u.id", dept_filter="u.department = %s AND")
            cursor.execute(q, (department, curr_start, curr_end))
            curr_avg = cursor.fetchone()[0]
            cursor.execute(q, (department, prev_start, prev_end))
            prev_avg = cursor.fetchone()[0]
        else:
            q = base_q.format(join="", dept_filter="")
            cursor.execute(q, (curr_start, curr_end))
            curr_avg = cursor.fetchone()[0]
            cursor.execute(q, (prev_start, prev_end))
            prev_avg = cursor.fetchone()[0]
    finally:
        cursor.close()
        release_db_connection(conn)

    curr = round(curr_avg or 0)
    prev = round(prev_avg or 0)
    change = round(curr - prev, 1)
    return {
        "current": curr,
        "previous": prev,
        "change": change,
        "trend": "up" if change > 0 else ("down" if change < 0 else "stable"),
    }


def get_team_weighted_scores(department: str) -> List[float]:
    return [get_user_weighted_score(m["id"]) for m in get_team_with_reports(department)]