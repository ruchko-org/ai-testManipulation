# Квиз: распознай манипуляцию

Веб-приложение на Flask — тест для старшеклассников на распознавание манипулятивных приёмов в общении.

## Что внутри

- `questions.py` — банк из 200 вопросов (список словарей) с разбором каждого варианта ответа.
- `app.py` — Flask-приложение с логикой квиза.
- `templates/` — HTML-шаблоны (главная, вопрос, объяснение, результат, ошибка).
- `static/style.css` — оформление.
- `requirements.txt` — зависимости.

## Формат вопроса

```python
{
    "id": 1,
    "category": "Определение манипуляции",
    "question": "Текст вопроса?",
    "options": ["Вариант 1", "Вариант 2", "Вариант 3", "Вариант 4"],
    "correct": 1,
    "explanation": "Почему правильный ответ именно такой.",
    "option_explanations": [
        "Неверно. Почему этот вариант неправильный.",
        "Верно. Почему этот вариант правильный.",
        "Неверно. ...",
        "Неверно. ...",
    ],
}
```

Поле `option_explanations` содержит 4 строки — по одной на каждый вариант ответа.
Ровно одна из них начинается со слова «Верно.», и её индекс совпадает с полем `correct`.

## Установка и запуск

```bash
# Создать и активировать виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Установить зависимости
pip install -r requirements.txt

# Для постоянного ключа в локальной разработке
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"

# Запустить приложение
python app.py
```

Открой в браузере: http://127.0.0.1:5000

При прямом запуске без `FLASK_SECRET_KEY` приложение создаёт временный ключ и предупреждает об этом.
После перезапуска такой ключ меняется. WSGI-сервер без настроенного ключа отвечает `503` на страницах, использующих сессию.

## Production

Задай постоянный `FLASK_SECRET_KEY` через защищённую конфигурацию сервера или менеджер секретов.
Используй одно и то же значение для всех WSGI workers. Не добавляй ключ в репозиторий.

При работе по HTTPS включи защищённую cookie:

```bash
FLASK_SESSION_COOKIE_SECURE=true
```

Для production используй WSGI-сервер, например Gunicorn, за HTTPS reverse proxy. Установи Gunicorn отдельно от зависимостей приложения, затем запусти:

```bash
gunicorn --workers 2 --bind 127.0.0.1:8000 app:app
```

Установи `FLASK_SECRET_KEY` и `FLASK_SESSION_COOKIE_SECURE=true` в окружении systemd или WSGI-сервера.
Для локального HTTP оставь `FLASK_SESSION_COOKIE_SECURE` выключенным.

`SESSION_SIZE` в `app.py` задаёт число вопросов за прохождение; по умолчанию — 30.

## Тесты

Тесты используют стандартный `unittest` и Flask test client:

```bash
python -m pip install Flask==3.1.3 Werkzeug==3.1.9
python -m unittest discover -s tests -v
```

## Проверка API

`GET /api/questions` — покажет, сколько вопросов загружено.
