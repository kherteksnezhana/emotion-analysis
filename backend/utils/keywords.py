"""
Утилита извлечения ключевых слов из текста отчётов.
"""
from backend.config import KEYWORD_MAX_COUNT, KEYWORD_MAX_LENGTH, KEYWORD_MIN_WORD_LENGTH
from backend.model.text_preprocessor import RUSSIAN_STOP_WORDS, clean_text


def extract_keywords(
    text: str,
    max_count: int = KEYWORD_MAX_COUNT,
    max_length: int = KEYWORD_MAX_LENGTH,
) -> list[str]:
    """
    Извлекает ключевые слова из текста, исключая стоп-слова.

    Args:
        text: исходный текст
        max_count: максимальное количество ключевых слов
        max_length: максимальная длина одного слова

    Returns:
        список уникальных ключевых слов
    """
    if not text:
        return []

    cleaned = clean_text(
        text,
        lowercase=True,
        remove_punctuation=True,
        replace_numbers=False,
        remove_stopwords=False,
        strip_extra_spaces=True,
    )

    keywords: list[str] = []
    for word in cleaned.split():
        if (
            len(word) > KEYWORD_MIN_WORD_LENGTH
            and word not in RUSSIAN_STOP_WORDS
            and word not in keywords
            and len(keywords) < max_count
        ):
            keywords.append(word[:max_length])

    return keywords