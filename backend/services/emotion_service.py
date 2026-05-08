"""
Сервис анализа эмоций.
Инкапсулирует бизнес-логику: вызов модели, сохранение результата в БД.
"""
from fastapi import HTTPException

import backend.database.database as db
from backend.model.emotion_model import analyze_emotion
from backend.config import REPORT_MIN_LENGTH


class EmotionService:
    """Анализирует эмоции из текста и сохраняет результат."""

    @staticmethod
    def analyze_and_save(user_id: int, text: str) -> dict:
        """
        Анализирует текст, сохраняет отчёт и результат анализа в БД.

        Args:
            user_id: идентификатор пользователя
            text: текст отчёта

        Returns:
            словарь с результатами анализа

        Raises:
            HTTPException 400: текст слишком короткий
            HTTPException 500: ошибка модели или БД
        """
        text = text.strip()
        if len(text) < REPORT_MIN_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Текст слишком короткий. Минимум {REPORT_MIN_LENGTH} символов",
            )

        # Получаем историю для контекста выгорания
        user_history = db.get_user_reports_history(user_id, limit=10)

        # Вызов ML-модели
        result = analyze_emotion(text, user_history)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        # Сохраняем отчёт
        report_id = db.save_report(user_id, text)
        if not report_id:
            raise HTTPException(status_code=500, detail="Не удалось сохранить отчёт")

        # Сохраняем результат анализа
        db.save_analysis_result(
            report_id,
            result["display_label"],
            result["score"],
            result["burnout_index"],
            str(result["all_scores"]),
        )

        return {
            "success": True,
            "emotion": result["display_label"],
            "confidence": result["score"],
            "burnout_index": result["burnout_index"],
            "burnout_risk": result.get("burnout_risk", "minimal"),
            "burnout_trend": result.get("burnout_trend", "stable"),
        }