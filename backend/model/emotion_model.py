"""
ML-модель анализа эмоций (RuBERT).
Конфигурация берётся из config.py — никакого хардкода.
"""
from transformers import pipeline

from backend.config import (
    BURNOUT_KEYWORDS,
    BURNOUT_WEIGHT_HIGH,
    BURNOUT_WEIGHT_MEDIUM,
    BURNOUT_WEIGHT_LOW,
    BURNOUT_FACTOR_EMOTIONAL,
    BURNOUT_FACTOR_SEMANTIC,
    BURNOUT_FACTOR_HISTORICAL,
    BURNOUT_RISK_THRESHOLDS,
    EMOTION_MODEL_NAME,
    EMOTION_MODEL_MAX_LENGTH,
    EMOTION_MODEL_DEVICE,
)
from backend.model.text_preprocessor import preprocess_for_model, postprocess_sentiment_scores

# Глобальный кэш модели - загружается один раз при первом использовании
_classifier = None


def _get_classifier():
    """Ленивая загрузка модели с кэшированием."""
    global _classifier
    if _classifier is None:
        print("Загрузка модели RuBERT... (при первом запуске может занять 20-60 секунд)")
        _classifier = pipeline(
            "text-classification",
            model=EMOTION_MODEL_NAME,
            return_all_scores=True,
            device=EMOTION_MODEL_DEVICE,
        )
    return _classifier

_LEVEL_WEIGHTS = {
    "high": BURNOUT_WEIGHT_HIGH,
    "medium": BURNOUT_WEIGHT_MEDIUM,
    "low": BURNOUT_WEIGHT_LOW,
}


def detect_burnout_keywords(text: str) -> float:
    """Анализирует текст на наличие ключевых слов-маркеров выгорания."""
    text_lower = text.lower()
    max_score = 0.0

    for level, keywords in BURNOUT_KEYWORDS.items():
        weight = _LEVEL_WEIGHTS[level]
        for keyword in keywords:
            if keyword in text_lower:
                count = text_lower.count(keyword)
                score = weight * min(1.0, count / 3)
                max_score = max(max_score, score)

    return round(max_score, 4)


def calculate_burnout_multifactor(
    text: str,
    scores: dict,
    user_history: list = None,
) -> dict:
    """Многофакторный расчёт индекса выгорания."""
    positive = scores.get("positive", 0)
    negative = scores.get("negative", 0)

    # 1. Эмоциональный фактор (60%)
    emotional_factor = round(negative * 0.7 + (1 - positive) * 0.3, 4)

    # 2. Семантический фактор (20%)
    semantic_factor = detect_burnout_keywords(text)

    # 3. Исторический фактор (20%)
    historical_factor = 0.5
    trend = "stable"

    if user_history:
        recent = user_history[:5]
        history_values = [r.get("burnout_index", 0.5) for r in recent]
        if history_values:
            historical_factor = round(sum(history_values) / len(history_values), 4)
            if len(history_values) >= 2:
                delta = history_values[0] - history_values[1]
                trend = "up" if delta > 0.1 else ("down" if delta < -0.1 else "stable")

    burnout_index = round(
        min(
            max(
                emotional_factor * BURNOUT_FACTOR_EMOTIONAL
                + semantic_factor * BURNOUT_FACTOR_SEMANTIC
                + historical_factor * BURNOUT_FACTOR_HISTORICAL,
                0,
            ),
            1,
        ),
        4,
    )

    # Уровень риска
    thresholds = BURNOUT_RISK_THRESHOLDS
    if burnout_index >= thresholds["critical"]:
        risk_level, risk_desc = "critical", "Критический риск выгорания"
    elif burnout_index >= thresholds["high"]:
        risk_level, risk_desc = "high", "Высокий риск выгорания"
    elif burnout_index >= thresholds["medium"]:
        risk_level, risk_desc = "medium", "Средний риск выгорания"
    elif burnout_index >= thresholds["low"]:
        risk_level, risk_desc = "low", "Низкий риск выгорания"
    else:
        risk_level, risk_desc = "minimal", "Минимальный риск"

    return {
        "burnout_index": burnout_index,
        "factors": {
            "emotional": emotional_factor,
            "semantic": semantic_factor,
            "historical": historical_factor,
        },
        "risk_level": risk_level,
        "risk_desc": risk_desc,
        "trend": trend,
    }


def analyze_emotion(text: str, user_history: list = None) -> dict:
    """Анализирует эмоции и выгорание в тексте."""
    if len(text.strip()) < 10:
        return {
            "label": "Текст слишком короткий",
            "display_label": "Текст слишком короткий",
            "score": 0.0,
            "all_scores": {},
            "burnout_index": 0.0,
            "burnout_factors": {},
            "burnout_risk": "minimal",
            "burnout_trend": "stable",
        }

    try:
        cleaned_text = preprocess_for_model(text)
        print(f"[DEBUG] Оригинал: {text[:100]}...")
        print(f"[DEBUG] После очистки: {cleaned_text[:100]}...")

        output = _get_classifier()(cleaned_text[:EMOTION_MODEL_MAX_LENGTH])

        scores: dict = {}
        if isinstance(output, list) and output:
            items = output[0] if isinstance(output[0], list) else output
            for item in items:
                if isinstance(item, dict):
                    label = item.get("label")
                    score = item.get("score")
                    if label is not None and score is not None:
                        scores[label.lower()] = round(float(score), 4)

        if not scores:
            return {"error": "Модель вернула неожиданный формат", "raw_output": str(output)[:500]}

        print(f"[DEBUG] Raw scores: {scores}")
        scores = postprocess_sentiment_scores(scores)
        print(f"[DEBUG] Post-processed scores: {scores}")

        top_label = max(scores, key=scores.get)
        label_map = {
            "positive": "Положительное состояние",
            "neutral": "Нейтральное состояние",
            "negative": "Негативное состояние",
        }
        display_label = label_map.get(top_label, top_label)

        burnout_result = calculate_burnout_multifactor(cleaned_text, scores, user_history)

        return {
            "label": top_label,
            "display_label": display_label,
            "score": scores[top_label],
            "all_scores": scores,
            "burnout_index": burnout_result["burnout_index"],
            "burnout_factors": burnout_result["factors"],
            "burnout_risk": burnout_result["risk_level"],
            "burnout_risk_desc": burnout_result["risk_desc"],
            "burnout_trend": burnout_result["trend"],
        }

    except Exception as e:
        print(f"[ERROR] Ошибка при анализе: {e}")
        return {"error": f"Ошибка обработки: {str(e)}"}


# ── Тест ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_texts = [
        "Я сегодня очень устал от этой работы и уже ничего не хочу делать.",
        "Отличный день! Всё получилось, команда сработала отлично.",
        "Нормально прошёл день, сделал свои задачи.",
    ]
    for t in test_texts:
        result = analyze_emotion(t)
        print(f"\nТекст: {t}")
        print(f"Эмоция: {result['display_label']} ({result['score'] * 100:.1f}%)")
        print(f"Выгорание: {result['burnout_index'] * 100:.1f}%")