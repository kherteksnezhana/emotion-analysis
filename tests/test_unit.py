"""
test_unit.py — модульные тесты (Unit Tests)

Проверяемые функции:
  • preprocess_for_model()       — очистка текста, замена чисел, нормализация
  • postprocess_sentiment_scores() — коррекция вероятностей от RuBERT
  • calculate_burnout_multifactor() — многофакторный расчёт выгорания
  • extract_keywords()            — извлечение ключевых слов
"""

import pytest
from unittest.mock import patch, MagicMock


# ============================================================
# 1. preprocess_for_model & clean_text
# ============================================================

class TestPreprocessForModel:
    """Тесты предобработки текста перед подачей в RuBERT."""

    def _get_fn(self):
        from backend.model.text_preprocessor import preprocess_for_model
        return preprocess_for_model

    def test_lowercase(self):
        fn = self._get_fn()
        result = fn("ДОБРОЕ утро ВСЕМ И каждому")
        assert result == result.lower(), "Текст должен быть приведён к нижнему регистру"

    def test_numbers_replaced(self):
        fn = self._get_fn()
        result = fn("Сделал задачу за 3 часа и 15 минут")
        assert "<NUM>" in result, "Числа должны заменяться на токен <NUM>"
        assert "3" not in result
        assert "15" not in result

    def test_float_numbers_replaced(self):
        fn = self._get_fn()
        result = fn("Точность составила 98.5 процентов")
        assert "<NUM>" in result

    def test_extra_spaces_stripped(self):
        fn = self._get_fn()
        result = fn("Привет   мир   как  дела")
        assert "  " not in result, "Лишние пробелы должны быть удалены"

    def test_empty_string(self):
        fn = self._get_fn()
        result = fn("")
        assert result == ""

    def test_max_length_truncation(self):
        fn = self._get_fn()
        long_text = "слово " * 200
        result = fn(long_text, max_length=50)
        assert len(result) <= 50, "Текст должен обрезаться до max_length символов"

    def test_punctuation_preserved(self):
        """RuBERT обучался с пунктуацией — она не должна удаляться."""
        fn = self._get_fn()
        result = fn("Отлично! Всё прошло хорошо?")
        assert "!" in result or "?" in result, \
            "Пунктуация должна сохраняться (несёт эмоциональную нагрузку)"

    def test_normal_text_unchanged_structure(self):
        fn = self._get_fn()
        result = fn("Сегодня был продуктивный день")
        assert len(result) > 0
        assert isinstance(result, str)


class TestCleanText:
    """Тесты вспомогательной функции clean_text."""

    def _get_fn(self):
        from backend.model.text_preprocessor import clean_text
        return clean_text

    def test_remove_punctuation(self):
        fn = self._get_fn()
        result = fn("Привет, мир!", remove_punctuation=True)
        assert "," not in result

    def test_keep_punctuation(self):
        fn = self._get_fn()
        result = fn("Привет, мир!", remove_punctuation=False)
        assert "," in result

    def test_remove_stopwords(self):
        fn = self._get_fn()
        result = fn("я и ты на работе", remove_stopwords=True)
        for sw in ["я", "и", "ты", "на"]:
            assert sw not in result.split(), f"Стоп-слово '{sw}' должно быть удалено"

    def test_replace_numbers_false(self):
        fn = self._get_fn()
        result = fn("Год 2024", replace_numbers=False)
        assert "2024" in result


# ============================================================
# 2. postprocess_sentiment_scores
# ============================================================

class TestPostprocessSentimentScores:
    """Тесты коррекции вероятностей от RuBERT."""

    def _get_fn(self):
        from backend.model.text_preprocessor import postprocess_sentiment_scores
        return postprocess_sentiment_scores

    def test_empty_scores(self):
        fn = self._get_fn()
        result = fn({})
        assert result == {}

    def test_normalization(self):
        fn = self._get_fn()
        scores = {"positive": 0.5, "neutral": 0.3, "negative": 0.2}
        result = fn(scores)
        total = sum(result.values())
        assert abs(total - 1.0) < 0.001, "Вероятности должны суммироваться к 1"

    def test_neutral_dominance_adjustment(self):
        fn = self._get_fn()
        scores = {"positive": 0.1, "neutral": 0.8, "negative": 0.1}
        result = fn(scores)
        assert result["neutral"] < 0.8, "Нейтральная вероятность должна уменьшиться"
        assert result["positive"] > 0.1 or result["negative"] > 0.1, "Позитив или негатив должны увеличиться"

    def test_negative_high_adjustment(self):
        fn = self._get_fn()
        scores = {"positive": 0.1, "neutral": 0.2, "negative": 0.7}
        result = fn(scores)
        assert result["negative"] < 0.7, "Высокая негативная вероятность должна уменьшиться"

    def test_all_zero(self):
        fn = self._get_fn()
        scores = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
        result = fn(scores)
        assert result == scores


# ============================================================
# 3. calculate_burnout_multifactor
# ============================================================

class TestCalculateBurnoutMultifactor:
    """Тесты многофакторного расчёта выгорания."""

    def _get_fn(self):
        from backend.model.emotion_model import calculate_burnout_multifactor
        return calculate_burnout_multifactor

    def test_no_history(self):
        fn = self._get_fn()
        scores = {"positive": 0.8, "negative": 0.1}
        result = fn("Я счастлив на работе", scores)
        assert "burnout_index" in result
        assert 0 <= result["burnout_index"] <= 1

    def test_with_history(self):
        fn = self._get_fn()
        scores = {"positive": 0.5, "negative": 0.3}
        history = [{"burnout_index": 0.6}, {"burnout_index": 0.7}]
        result = fn("Устал от работы", scores, history)
        assert "burnout_index" in result
        assert "trend" in result

    def test_high_negative_burnout(self):
        fn = self._get_fn()
        scores = {"positive": 0.1, "negative": 0.8}
        result = fn("Я в отчаянии", scores)
        assert result["burnout_index"] > 0.5, "Высокий негатив должен давать высокий индекс выгорания"

    def test_low_negative_burnout(self):
        fn = self._get_fn()
        scores = {"positive": 0.9, "negative": 0.05}
        result = fn("Всё отлично", scores)
        assert result["burnout_index"] < 0.5, "Низкий негатив должен давать низкий индекс выгорания"


# ============================================================
# 4. extract_keywords
# ============================================================

class TestExtractKeywords:
    """Тесты извлечения ключевых слов."""

    def _get_fn(self):
        from backend.utils.keywords import extract_keywords
        return extract_keywords

    def test_empty_text(self):
        fn = self._get_fn()
        result = fn("")
        assert result == []

    def test_short_words_filtered(self):
        fn = self._get_fn()
        result = fn("я и ты на работе")
        assert len(result) == 0 or all(len(w) > 2 for w in result), "Короткие слова должны фильтроваться"

    def test_stopwords_filtered(self):
        fn = self._get_fn()
        result = fn("работа и стресс на работе")
        assert "и" not in result, "Стоп-слова должны удаляться"
        assert "на" not in result

    def test_unique_keywords(self):
        fn = self._get_fn()
        result = fn("работа работа стресс стресс")
        assert len(result) == len(set(result)), "Ключевые слова должны быть уникальными"

    def test_max_count(self):
        fn = self._get_fn()
        text = "работа стресс усталость переутомление выгорание проблемы сложности"
        result = fn(text, max_count=3)
        assert len(result) <= 3, "Количество ключевых слов не должно превышать max_count"

    def test_max_length(self):
        fn = self._get_fn()
        text = "оченьдлинноеслово которое нужно обрезать"
        result = fn(text, max_length=5)
        assert all(len(w) <= 5 for w in result), "Длина слов не должна превышать max_length"

    def test_strip_extra_spaces(self):
        fn = self._get_fn()
        result = fn("  много   пробелов  ", strip_extra_spaces=True)
        assert result == result.strip()
        assert "  " not in result


# ============================================================
# 2. postprocess_sentiment_scores
# ============================================================

class TestPostprocessSentimentScores:
    """Тесты коррекции вероятностей сентимент-модели."""

    def _get_fn(self):
        from backend.model.text_preprocessor import postprocess_sentiment_scores
        return postprocess_sentiment_scores

    def test_scores_sum_to_one(self):
        fn = self._get_fn()
        result = fn({"positive": 0.7, "neutral": 0.2, "negative": 0.1})
        total = sum(result.values())
        assert abs(total - 1.0) < 0.01, f"Сумма вероятностей должна быть ≈1.0, получено {total}"

    def test_no_extreme_values(self):
        """После постобработки ни одна вероятность не должна быть 0 или 1."""
        fn = self._get_fn()
        result = fn({"positive": 0.99, "neutral": 0.005, "negative": 0.005})
        for label, val in result.items():
            assert 0 < val < 1, f"Вероятность {label}={val} не должна быть экстремальной"

    def test_empty_scores(self):
        fn = self._get_fn()
        result = fn({})
        assert result == {}

    def test_high_negative_bias_correction(self):
        """Если negative > 0.7 при низком positive — negative должен быть уменьшен."""
        fn = self._get_fn()
        raw = {"positive": 0.05, "neutral": 0.05, "negative": 0.90}
        result = fn(raw)
        # После коррекции negative должен стать меньше исходного (после нормировки)
        assert result.get("negative", 1.0) < 0.90, \
            "Bias-correction: завышенный negative должен быть снижен"

    def test_dominant_neutral_smoothed(self):
        """Если neutral доминирует — он должен быть сглажен."""
        fn = self._get_fn()
        raw = {"positive": 0.05, "neutral": 0.90, "negative": 0.05}
        result = fn(raw)
        assert result["neutral"] < 0.90, \
            "Доминирующий neutral должен сглаживаться"

    def test_output_has_all_keys(self):
        fn = self._get_fn()
        result = fn({"positive": 0.4, "neutral": 0.3, "negative": 0.3})
        assert set(result.keys()) == {"positive", "neutral", "negative"}

    def test_values_are_rounded(self):
        fn = self._get_fn()
        result = fn({"positive": 0.333333, "neutral": 0.333333, "negative": 0.333334})
        for v in result.values():
            # Не более 4 знаков после запятой
            assert round(v, 4) == v


# ============================================================
# 3. calculate_burnout_multifactor (УБИРАЕМ НЕПРАВИЛЬНЫЙ PATCH)
# ============================================================

class TestCalculateBurnoutMultifactor:
    """Тесты многофакторного расчёта индекса выгорания."""
    
    def _get_fn(self):
        # НЕ используем patch - просто импортируем функцию
        from backend.model.emotion_model import calculate_burnout_multifactor
        return calculate_burnout_multifactor
    
    def test_burnout_range(self):
        fn = self._get_fn()
        scores = {"positive": 0.1, "neutral": 0.1, "negative": 0.8}
        result = fn("Устал, нет сил, выгорел", scores)
        assert 0.0 <= result["burnout_index"] <= 1.0
    
    def test_positive_text_low_burnout(self):
        fn = self._get_fn()
        scores = {"positive": 0.92, "neutral": 0.05, "negative": 0.03}
        result = fn("Отличный день! Всё получилось!", scores)
        assert result["burnout_index"] < 0.5
    
    def test_negative_text_high_burnout(self):
        fn = self._get_fn()
        scores = {"positive": 0.02, "neutral": 0.05, "negative": 0.93}
        result = fn("Нет сил совсем. Выгорел, безысходность", scores)
        assert result["burnout_index"] > 0.3
    
    def test_result_has_required_keys(self):
        fn = self._get_fn()
        scores = {"positive": 0.5, "neutral": 0.3, "negative": 0.2}
        result = fn("Нормальный день", scores)
        for key in ("burnout_index", "factors", "risk_level", "trend"):
            assert key in result, f"Ожидаемый ключ '{key}' отсутствует"
    
    def test_no_history_uses_default(self):
        fn = self._get_fn()
        scores = {"positive": 0.5, "neutral": 0.3, "negative": 0.2}
        result = fn("Обычный день", scores, user_history=None)
        assert "burnout_index" in result


# ============================================================
# 4. extract_keywords
# ============================================================

class TestExtractKeywords:
    """Тесты извлечения ключевых слов."""

    def _get_fn(self):
        from backend.utils.keywords import extract_keywords
        return extract_keywords

    def test_basic_extraction(self):
        fn = self._get_fn()
        result = fn("Сегодня завершил большой проект по разработке системы")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_stopwords_excluded(self):
        fn = self._get_fn()
        result = fn("я и ты работали над задачей")
        stopwords = {"я", "и", "ты", "над"}
        for word in result:
            assert word not in stopwords, f"Стоп-слово '{word}' не должно попадать в ключевые слова"

    def test_max_count_respected(self):
        fn = self._get_fn()
        text = "разработка тестирование деплой мониторинг аналитика безопасность производительность масштабирование"
        result = fn(text, max_count=3)
        assert len(result) <= 3, "Количество ключевых слов не должно превышать max_count"

    def test_max_length_respected(self):
        fn = self._get_fn()
        result = fn("программирование разработка", max_length=5)
        for word in result:
            assert len(word) <= 5, f"Слово '{word}' длиннее max_length=5"

    def test_empty_text(self):
        fn = self._get_fn()
        result = fn("")
        assert result == [], "Пустой текст должен возвращать пустой список"

    def test_no_duplicates(self):
        fn = self._get_fn()
        result = fn("работа работа работа проект проект")
        assert len(result) == len(set(result)), "Ключевые слова не должны дублироваться"

    def test_short_words_excluded(self):
        fn = self._get_fn()
        result = fn("я он она по да нет")
        for word in result:
            assert len(word) > 4, \
                f"Слово '{word}' слишком короткое (должно быть > KEYWORD_MIN_WORD_LENGTH)"

    def test_returns_list_of_strings(self):
        fn = self._get_fn()
        result = fn("Успешно завершил задачу по тестированию нового функционала")
        assert all(isinstance(w, str) for w in result)

    def test_real_report_text(self):
        fn = self._get_fn()
        text = ("Наконец-то закрыл тикет по миграции базы данных. "
                "Все прошло без сбоев, хотя и задержался на пару часов. "
                "Чувствую удовлетворение от проделанной работы.")
        result = fn(text, max_count=5)
        assert 1 <= len(result) <= 5
        # Должны встречаться содержательные слова
        all_words = " ".join(result).lower()
        # Хотя бы одно из значимых слов попало
        significant = {"миграции", "базы", "данных", "сбоев", "часов",
                       "удовлетворение", "проделанной", "работы", "тикет", "закрыл"}
        assert any(w in all_words for w in significant), \
            f"Ожидались значимые слова, получено: {result}"