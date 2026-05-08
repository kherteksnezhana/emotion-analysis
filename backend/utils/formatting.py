"""
Утилиты форматирования: даты, строки, timestamp.
Единственное место — никакого дублирования по всему проекту.
"""
from datetime import datetime
from backend.config import MONTHS_SHORT


def safe_timestamp(value) -> str:
    """Конвертирует datetime или строку в ISO-строку «YYYY-MM-DD HH:MM:SS»."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def format_date_short(date_str: str) -> str:
    """Форматирует дату ISO → «15 янв»."""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return f"{dt.day} {MONTHS_SHORT[dt.month]}"
    except (ValueError, IndexError):
        return date_str[:10]


def date_to_str(dt: datetime) -> str:
    """datetime → 'YYYY-MM-DD'."""
    return dt.strftime("%Y-%m-%d")