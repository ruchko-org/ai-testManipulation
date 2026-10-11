# -*- coding: utf-8 -*-
"""
Flask-приложение: квиз по распознаванию манипуляций.

Логика:
- Вопросы загружаются из questions.py (список словарей).
- За одну сессию игрок отвечает на SESSION_SIZE вопросов (по умолчанию 30).
- Вопросы выбираются случайно из всего банка.
- После каждого ответа показывается подробное объяснение.
- В конце — результат и разбор ошибок.
"""

import random
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
)

# Импортируем банк вопросов. Ожидаем список словарей QUESTIONS.
try:
    from questions import QUESTIONS
except ImportError:  # pragma: no cover
    QUESTIONS = []

app = Flask(__name__)
# Секретный ключ для подписи сессионных cookie.
# В продакшене замените на случайную строку из переменной окружения.
app.secret_key = "change-me-to-a-random-secret-key"

# Сколько вопросов задаётся за одну сессию.
SESSION_SIZE = 30


def normalize_questions(raw_questions):
    """Приводит вопросы к единому виду и отбрасывает некорректные.

    Поддерживает формат:
        {"id": int, "category": str, "question": str,
         "options": [str, ...], "correct": int, "explanation": str,
         "option_explanations": [str, ...]}
    """
    cleaned = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        options = item.get("options")
        correct = item.get("correct")
        explanation = item.get("explanation", "")
        option_explanations = item.get("option_explanations")

        if not question or not isinstance(options, list):
            continue
        if len(options) < 2:
            continue
        if not isinstance(correct, int) or not (0 <= correct < len(options)):
            continue

        # Разбор по вариантам валиден только если это список строк
        # ровно по числу вариантов ответа.
        if not (
            isinstance(option_explanations, list)
            and len(option_explanations) == len(options)
            and all(isinstance(x, str) for x in option_explanations)
        ):
            option_explanations = None

        cleaned.append(
            {
                "id": item.get("id"),
                "category": item.get("category", "Без категории"),
                "question": question,
                "options": list(options),
                "correct": correct,
                "explanation": explanation,
                "option_explanations": option_explanations,
            }
        )
    return cleaned


# Готовим банк вопросов один раз при старте.
ALL_QUESTIONS = normalize_questions(QUESTIONS)


def get_total_questions():
    return len(ALL_QUESTIONS)


def build_session_questions():
    """Выбирает случайные вопросы для новой сессии."""
    total = get_total_questions()
    if total == 0:
        return []
    size = min(SESSION_SIZE, total)
    picked = random.sample(ALL_QUESTIONS, size)
    # Сохраняем только индексы, чтобы не раздувать cookie.
    index_map = {id(q): idx for idx, q in enumerate(ALL_QUESTIONS)}
    return [index_map[id(q)] for q in picked]


@app.route("/")
def index():
    """Главная страница."""
    return render_template(
        "index.html",
        total_questions=get_total_questions(),
        session_size=min(SESSION_SIZE, get_total_questions()),
    )


@app.route("/start", methods=["POST"])
def start():
    """Начинает новую сессию квиза."""
    if get_total_questions() == 0:
        return render_template(
            "error.html",
            message="Банк вопросов пуст. Добавьте вопросы в questions.py.",
        )

    session.clear()
    session["question_indexes"] = build_session_questions()
    session["current"] = 0
    session["answers"] = []
    session["finished"] = False
    return redirect(url_for("question"))


@app.route("/question", methods=["GET", "POST"])
def question():
    """Показывает текущий вопрос или страницу с объяснением."""
    indexes = session.get("question_indexes")
    if not indexes:
        return redirect(url_for("index"))

    current = session.get("current", 0)

    if current >= len(indexes):
        return redirect(url_for("result"))

    q_index = indexes[current]
    q = ALL_QUESTIONS[q_index]

    if request.method == "POST":
        chosen_raw = request.form.get("answer")
        if chosen_raw is None:
            return render_template(
                "question.html",
                q=q,
                current=current + 1,
                total=len(indexes),
                error="Пожалуйста, выберите один из вариантов.",
            )

        try:
            chosen = int(chosen_raw)
        except (TypeError, ValueError):
            chosen = -1

        is_correct = chosen == q["correct"]
        answers = session.get("answers", [])
        answers.append(
            {
                "q_index": q_index,
                "chosen": chosen,
                "correct": q["correct"],
                "is_correct": is_correct,
            }
        )
        session["answers"] = answers
        session["current"] = current + 1

        return render_template(
            "feedback.html",
            q=q,
            chosen=chosen,
            is_correct=is_correct,
            current=current + 1,
            total=len(indexes),
        )

    return render_template(
        "question.html",
        q=q,
        current=current + 1,
        total=len(indexes),
    )


@app.route("/next", methods=["POST"])
def next_question():
    """Переход к следующему вопросу после просмотра объяснения."""
    indexes = session.get("question_indexes", [])
    current = session.get("current", 0)
    if current >= len(indexes):
        return redirect(url_for("result"))
    return redirect(url_for("question"))


@app.route("/result")
def result():
    """Итоговая страница."""
    indexes = session.get("question_indexes", [])
    answers = session.get("answers", [])

    if not indexes:
        return redirect(url_for("index"))

    total = len(indexes)
    correct_count = sum(1 for a in answers if a.get("is_correct"))
    percent = round(correct_count / total * 100) if total else 0

    review = []
    for a in answers:
        q = ALL_QUESTIONS[a["q_index"]]
        chosen = a.get("chosen", -1)
        opt_expl = q.get("option_explanations")
        chosen_expl = None
        correct_expl = None
        if opt_expl:
            if isinstance(chosen, int) and 0 <= chosen < len(opt_expl):
                chosen_expl = opt_expl[chosen]
            if 0 <= q["correct"] < len(opt_expl):
                correct_expl = opt_expl[q["correct"]]
        review.append(
            {
                "question": q["question"],
                "category": q["category"],
                "is_correct": a.get("is_correct", False),
                "chosen_text": (
                    q["options"][chosen]
                    if isinstance(chosen, int) and 0 <= chosen < len(q["options"])
                    else "—"
                ),
                "correct_text": q["options"][q["correct"]],
                "explanation": q["explanation"],
                "chosen_explanation": chosen_expl,
                "correct_explanation": correct_expl,
            }
        )

    if percent >= 90:
        level = "Отличный результат! Ты хорошо распознаёшь манипуляции."
        level_class = "level-great"
    elif percent >= 70:
        level = "Хороший результат. Некоторые приёмы стоит повторить."
        level_class = "level-good"
    elif percent >= 50:
        level = "Средний результат. Стоит изучить техники внимательнее."
        level_class = "level-ok"
    else:
        level = "Низкий результат. Рекомендуем пройти квиз ещё раз и изучить материалы."
        level_class = "level-low"

    return render_template(
        "result.html",
        total=total,
        correct_count=correct_count,
        percent=percent,
        level=level,
        level_class=level_class,
        review=review,
    )


@app.route("/restart", methods=["POST"])
def restart():
    """Сброс и начало заново."""
    session.clear()
    return redirect(url_for("index"))


@app.route("/api/questions")
def api_questions():
    """Небольшой API для отладки: сколько вопросов загружено."""
    return jsonify(
        {
            "total": get_total_questions(),
            "session_size": min(SESSION_SIZE, get_total_questions()),
        }
    )


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
