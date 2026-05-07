import re
from typing import Set

# ─────────────────────────────────────────────────────────────────────────────
# Стоп-слова русского языка
# ─────────────────────────────────────────────────────────────────────────────

RUSSIAN_STOP_WORDS: Set[str] = {
    # Местоимения
    'я', 'ты', 'он', 'она', 'оно', 'мы', 'вы', 'они',
    'меня', 'тебя', 'него', 'нее', 'нас', 'вас', 'них',
    'мне', 'тебе', 'нему', 'ней', 'нам', 'вам', 'ним',
    'мой', 'твой', 'его', 'её', 'их', 'наш', 'ваш',
    'свой', 'этот', 'тот', 'такой', 'такая', 'такое', 'такие',
    # Предлоги и союзы
    'и', 'в', 'во', 'на', 'с', 'со', 'к', 'у', 'о', 'об',
    'по', 'за', 'под', 'над', 'перед', 'через', 'для', 'без',
    'до', 'из', 'от', 'про', 'при', 'между', 'сквозь',
    'а', 'но', 'да', 'или', 'либо', 'то', 'что', 'чтобы',
    'потому', 'поэтому', 'также', 'тоже', 'как', 'будто',
    # Частицы и вводные слова
    'не', 'ни', 'ли', 'же', 'бы', 'ж', 'ведь', 'вот', 'вон',
    'даже', 'уже', 'ещё', 'только', 'почти', 'совсем',
    'очень', 'слишком', 'так', 'как-то', 'где-то', 'когда-то',
    # Глаголы-связки
    'быть', 'стать', 'являться', 'казаться', 'становиться',
    'есть', 'было', 'была', 'были', 'будет', 'будут',
    # Временны́е наречия
    'сегодня', 'вчера', 'завтра', 'сейчас', 'тогда', 'там', 'тут',
    'здесь', 'везде', 'всюду', 'никогда', 'всегда',
    # Слова-паразиты
    'короче', 'например', 'вообще', 'наверное',
    'конечно', 'действительно', 'наверняка', 'практически',
}

# ─────────────────────────────────────────────────────────────────────────────
# Регулярные выражения
# ─────────────────────────────────────────────────────────────────────────────

_NUMBER_RE = re.compile(r'\b\d+(?:[.,]\d+)?\b')
_EXTRA_SPACE_RE = re.compile(r'\s+')
_PUNCT_RE = re.compile(r'[^\w\s!?<>\'"()]')
_EXCL_RE = re.compile(r'([!?]+)')


def clean_text(
    text: str,
    lowercase: bool = True,
    remove_punctuation: bool = True,
    replace_numbers: bool = True,
    remove_stopwords: bool = False,
    strip_extra_spaces: bool = True,
) -> str:
    """Многофункциональная очистка текста."""
    if not text:
        return ""

    result = text.lower() if lowercase else text

    if replace_numbers:
        result = _NUMBER_RE.sub(' <NUM> ', result)

    if remove_punctuation:
        result = _PUNCT_RE.sub(' ', result)
        result = _EXCL_RE.sub(r' \1 ', result)

    if remove_stopwords:
        result = ' '.join(w for w in result.split() if w not in RUSSIAN_STOP_WORDS)

    if strip_extra_spaces:
        result = _EXTRA_SPACE_RE.sub(' ', result).strip()

    return result


def preprocess_for_model(text: str, max_length: int = 512) -> str:
    """Предобработка текста для RuBERT: нижний регистр + нормализация чисел."""
    cleaned = clean_text(
        text,
        lowercase=True,
        remove_punctuation=False,   # Пунктуация несёт эмоциональную нагрузку
        replace_numbers=True,
        remove_stopwords=False,     # Модель обучалась со стоп-словами
        strip_extra_spaces=True,
    )
    return cleaned[:max_length]


def postprocess_sentiment_scores(scores: dict) -> dict:
    """
    Коррекция вероятностей от RuBERT.

    Модель склонна завышать класс «negative» из-за дисбаланса обучающей выборки.
    Применяем мягкое сглаживание и перенормировку.
    """
    if not scores:
        return scores

    pos = scores.get('positive', 0.0)
    neu = scores.get('neutral', 0.0)
    neg = scores.get('negative', 0.0)

    # Нормализуем до суммы = 1
    total = pos + neu + neg
    if total > 0:
        pos /= total
        neu /= total
        neg /= total

    # Если нейтраль доминирует — слегка размазываем
    if neu > max(pos, neg):
        neu *= 0.6
        pos *= 1.2
        neg *= 1.2
        s = pos + neu + neg
        if s:
            pos, neu, neg = pos / s, neu / s, neg / s

    # Если negative неправдоподобно высок при низком positive — уменьшаем
    if neg > 0.7 and pos < 0.2:
        neg *= 0.8
        pos *= 1.2
        s = pos + neu + neg
        if s:
            pos, neu, neg = pos / s, neu / s, neg / s

    # Сглаживание: не допускаем экстремальных значений
    epsilon = 0.05
    pos = min(max(pos, epsilon), 1 - epsilon)
    neu = min(max(neu, epsilon), 1 - epsilon)
    neg = min(max(neg, epsilon), 1 - epsilon)

    s = pos + neu + neg
    return {
        'positive': round(pos / s, 4),
        'neutral':  round(neu / s, 4),
        'negative': round(neg / s, 4),
    }
