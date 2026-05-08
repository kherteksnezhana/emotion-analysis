# Emotion Analysis System

Платформа для оценки эмоционального состояния сотрудников на основе анализа текстовых отчётов (RuBERT).

---

## Стек

| Компонент | Технология |
|---|---|
| Backend | FastAPI + Uvicorn |
| ML-модель | `blanchefort/rubert-base-cased-sentiment` (HuggingFace) |
| БД | PostgreSQL (psycopg2, connection pool) |
| Шаблоны | Jinja2 |
| Фронтенд | Vanilla JS + Chart.js + Flatpickr + Lucide |
| Контейнер | Docker |

---

## Роли пользователей

- **Сотрудник** — пишет ежедневные отчёты, видит свою аналитику и риск выгорания
- **Руководитель** — видит состояние своего отдела, аналитику команды (без текстов отчётов)
- **HR-администратор** — полная аналитика по компании, экспорт данных в CSV

---

## Структура проекта

```
backend/
├── config.py                  # Константы и переменные окружения
├── main.py                    # Точка входа (только init + роутеры)
├── database/
│   └── database.py            # DAL: все SQL-запросы
├── model/
│   ├── emotion_model.py       # ML-модель RuBERT + расчёт выгорания
│   └── text_preprocessor.py  # Предобработка текста
├── routes/
│   ├── auth.py                # /  /register  /api/login  /api/logout  /api/register
│   ├── dashboard.py           # /dashboard (роутинг по ролям)
│   ├── api.py                 # /api/analyze  /api/team_analytics
│   ├── export.py              # /api/export_reports  /api/export_detailed_reports
│   └── deps.py                # Dependency: get_current_user
├── services/
│   ├── emotion_service.py     # Анализ + сохранение в БД
│   ├── export_service.py      # Генерация CSV-файлов
│   └── context_builders.py   # Контекст для Jinja2-шаблонов (по ролям)
├── schemas/
│   └── __init__.py            # Pydantic-модели валидации
└── utils/
    ├── formatting.py          # safe_timestamp, format_date_short
    └── keywords.py            # extract_keywords

templates/                     # Jinja2 HTML-шаблоны
static/css/                    # Стили
```

---

## Быстрый старт

### 1. Переменные окружения

Создайте файл `.env` в корне проекта:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/emotion_db
```

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 3. Запуск

```bash
python -m uvicorn backend.main:app --reload
```

### 4. Docker

```bash
docker build -t emotion-app .
docker run -p 8000:8000 --env-file .env emotion-app
```

---

## Алгоритм расчёта выгорания

Индекс выгорания рассчитывается по трём факторам:

| Фактор | Вес | Описание |
|---|---|---|
| Эмоциональный | 60% | На основе вероятностей positive/negative от RuBERT |
| Семантический | 20% | Наличие ключевых слов-маркеров (устал, выгорел и т.д.) |
| Исторический | 20% | Средний burnout из последних 5 отчётов |

Пороги риска: `minimal < 0.1 < low < 0.3 < medium < 0.5 < high < 0.7 < critical`

---

## Конфигурация

Все настройки централизованы в `backend/config.py`:

- `BURNOUT_KEYWORDS` — маркеры выгорания по уровням тяжести
- `BURNOUT_RISK_THRESHOLDS` — пороги уровней риска
- `SCORE_DECAY_FACTOR` — коэффициент затухания для взвешенного балла
- `EMOTION_MODEL_NAME` — название HuggingFace-модели
- `SESSION_DAYS` — срок жизни сессии
- `REPORT_MIN_LENGTH` — минимальная длина отчёта