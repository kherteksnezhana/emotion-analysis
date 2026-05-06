# emotion_model.py (обновлённая версия)
from transformers import pipeline
import torch
import re
from model.text_preprocessor import preprocess_for_model, postprocess_sentiment_scores

print("Загрузка модели RuBERT... (при первом запуске может занять 20-60 секунд)")

classifier = pipeline(
    "text-classification",
    model="blanchefort/rubert-base-cased-sentiment",
    return_all_scores=True,
    device=-1  # CPU
)

# Слова-маркеры выгорания (можно расширять)
BURNOUT_KEYWORDS = {
    'high': [  # Критические маркеры (вес 1.0)
        'выгорел', 'выгорание', 'сгорел', 'не могу больше',
        'нет сил совсем', 'опускаются руки', 'безысходность',
        'ненавижу работу', 'бессмысленно', 'не хочу жить'
    ],
    'medium': [  # Средние маркеры (вес 0.7)
        'устал', 'устала', 'усталость', 'истощение', 'опустошение',
        'нет энергии', 'выжат как лимон', 'без сил', 'переутомление',
        'вымотан', 'вымотана', 'измотан', 'утомлён', 'утомлена'
    ],
    'low': [  # Лёгкие маркеры (вес 0.4)
        'утомление', 'сонный', 'вялость', 'апатия', 'безразличие',
        'ничего не хочется', 'лень', 'тяжело', 'не высыпаюсь',
        'утомительно', 'надоело', 'раздражает'
    ]
}

def detect_burnout_keywords(text: str) -> float:
    """Анализирует текст на наличие ключевых слов-маркеров выгорания"""
    text_lower = text.lower()
    max_score = 0.0
    
    for level, keywords in BURNOUT_KEYWORDS.items():
        weight = 1.0 if level == 'high' else 0.7 if level == 'medium' else 0.4
        for keyword in keywords:
            if keyword in text_lower:
                # Чем больше совпадений, тем выше оценка (но не больше 1)
                count = text_lower.count(keyword)
                score = weight * min(1.0, count / 3)
                max_score = max(max_score, score)
    
    return round(max_score, 4)


def calculate_burnout_multifactor(
    text: str, 
    scores: dict, 
    user_history: list = None
) -> dict:
    """Многофакторный расчёт выгорания (без изменений)"""
    # 1. Эмоциональный фактор (60%)
    positive = scores.get('positive', 0)
    negative = scores.get('negative', 0)
    
    # Формула: чем выше негатив и ниже позитив — тем выше выгорание
    emotional_factor = (negative * 0.7 + (1 - positive) * 0.3)
    emotional_factor = round(emotional_factor, 4)
    
    # 2. Семантический фактор (20%)
    semantic_factor = detect_burnout_keywords(text)
    
    # 3. Исторический фактор (20%)
    historical_factor = 0.5
    trend = "stable"
    
    if user_history and len(user_history) > 0:
        recent_reports = user_history[:5]
        historical_values = [r.get('burnout_index', 0.5) for r in recent_reports]
        
        if historical_values:
            historical_factor = sum(historical_values) / len(historical_values)
            historical_factor = round(historical_factor, 4)
            
            if len(historical_values) >= 2:
                current = historical_values[0]
                previous = historical_values[1]
                if current > previous + 0.1:
                    trend = "up"
                elif current < previous - 0.1:
                    trend = "down"
                else:
                    trend = "stable"
    
    # Итоговый индекс выгорания
    burnout_index = (
        emotional_factor * 0.60 +
        semantic_factor * 0.20 +
        historical_factor * 0.20
    )
    burnout_index = round(min(max(burnout_index, 0), 1), 4)
    
    # Определение уровня риска
    if burnout_index >= 0.7:
        risk_level = "critical"
        risk_desc = "Критический риск выгорания"
    elif burnout_index >= 0.5:
        risk_level = "high"
        risk_desc = "Высокий риск выгорания"
    elif burnout_index >= 0.3:
        risk_level = "medium"
        risk_desc = "Средний риск выгорания"
    elif burnout_index >= 0.1:
        risk_level = "low"
        risk_desc = "Низкий риск выгорания"
    else:
        risk_level = "minimal"
        risk_desc = "Минимальный риск"
    
    return {
        "burnout_index": burnout_index,
        "factors": {
            "emotional": emotional_factor,
            "semantic": semantic_factor,
            "historical": historical_factor
        },
        "risk_level": risk_level,
        "risk_desc": risk_desc,
        "trend": trend
    }


def analyze_emotion(text: str, user_history: list = None):
    """Анализирует эмоции и выгорание в тексте (с предобработкой)"""
    
    if len(text.strip()) < 10:
        return {
            "label": "Текст слишком короткий",
            "display_label": "Текст слишком короткий",
            "score": 0.0,
            "all_scores": {},
            "burnout_index": 0.0,
            "burnout_factors": {},
            "burnout_risk": "minimal",
            "burnout_trend": "stable"
        }
    
    try:
        # 🔧 ПРЕДОБРАБОТКА ТЕКСТА перед отправкой в модель
        cleaned_text = preprocess_for_model(text)
        print(f"[DEBUG] Оригинал: {text[:100]}...")
        print(f"[DEBUG] После очистки: {cleaned_text[:100]}...")
        
        # Получаем результат от RuBERT
        output = classifier(cleaned_text[:512])
        
        # Разбираем результаты
        scores = {}
        if isinstance(output, list) and len(output) > 0:
            items = output[0] if isinstance(output[0], list) else output
            
            for item in items:
                if isinstance(item, dict):
                    label = item.get('label')
                    score = item.get('score')
                    if label is not None and score is not None:
                        if label.lower() == 'positive':
                            scores['positive'] = round(float(score), 4)
                        elif label.lower() == 'neutral':
                            scores['neutral'] = round(float(score), 4)
                        elif label.lower() == 'negative':
                            scores['negative'] = round(float(score), 4)
        
        if not scores:
            return {
                "error": "Модель вернула неожиданный формат",
                "raw_output": str(output)[:500]
            }
        
        print(f"[DEBUG] Raw scores: {scores}")
        
        # 🔧 ПОСТОБРАБОТКА - корректируем дисбаланс модели
        scores = postprocess_sentiment_scores(scores)
        print(f"[DEBUG] Post-processed scores: {scores}")
        
        # Определяем основную эмоцию
        top_label = max(scores, key=scores.get)
        
        label_map = {
            "positive": "Положительное состояние",
            "neutral": "Нейтральное состояние",
            "negative": "Негативное состояние"
        }
        
        display_label = label_map.get(top_label.lower(), top_label)
        
        # Многофакторный расчёт выгорания
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
            "burnout_trend": burnout_result["trend"]
        }
        
    except Exception as e:
        print(f"[ERROR] Ошибка при анализе: {e}")
        return {"error": f"Ошибка обработки: {str(e)}"}


# Тест
if __name__ == "__main__":
    test_texts = [
        "Я сегодня очень устал от этой работы и уже ничего не хочу делать.",
        "Отличный день! Всё получилось, команда сработала отлично.",
        "Нормально прошёл день, сделал свои задачи."
    ]
    
    for t in test_texts:
        result = analyze_emotion(t)
        print(f"\nТекст: {t}")
        print(f"Эмоция: {result['display_label']} ({result['score']*100:.1f}%)")
        print(f"Выгорание: {result['burnout_index']*100:.1f}%")