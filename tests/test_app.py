import importlib.util
import os
import runpy
import sys
import unittest
import uuid
import warnings
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_app(environment=None):
    values = {"FLASK_SECRET_KEY": ""}
    if environment:
        values.update(environment)
    name = "qquiz_test_app_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, ROOT / "app.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, values):
        spec.loader.exec_module(module)
    module.app.config.update(TESTING=True)
    return module


def question_bank(size):
    return [
        {
            "id": index,
            "category": "Тест",
            "question": "Вопрос {}?".format(index),
            "options": ["А", "Б", "В", "Г"],
            "correct": index % 4,
            "explanation": "Объяснение {}.".format(index),
            "option_explanations": ["Разбор {}.".format(option) for option in range(4)],
        }
        for index in range(size)
    ]


class HiddenInputParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = []

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            self.inputs.append(dict(attrs))

    def csrf_values(self):
        return [item.get("value") for item in self.inputs if item.get("name") == "csrf_token"]


def csrf_value(response):
    parser = HiddenInputParser()
    parser.feed(response.get_data(as_text=True))
    values = parser.csrf_values()
    if len(values) != 1:
        raise AssertionError("expected exactly one csrf_token hidden input")
    return values[0]


class AppSecurityTests(unittest.TestCase):
    def test_secret_is_loaded_from_environment(self):
        module = load_app({"FLASK_SECRET_KEY": "environment-secret"})
        self.assertEqual(module.app.secret_key, "environment-secret")

    def test_unconfigured_wsgi_session_routes_fail_clearly(self):
        module = load_app()
        self.assertIsNone(module.app.secret_key)
        client = module.app.test_client()

        requests = [
            ("/", "GET"),
            ("/start", "POST"),
            ("/question", "GET"),
            ("/question", "POST"),
            ("/next", "POST"),
            ("/result", "GET"),
            ("/restart", "POST"),
        ]
        for path, method in requests:
            with self.subTest(path=path, method=method):
                response = client.open(path, method=method)
                self.assertEqual(response.status_code, 503)
                self.assertIn(b"FLASK_SECRET_KEY", response.data)
        self.assertEqual(client.get("/api/questions").status_code, 200)
        static = client.get("/static/style.css")
        self.assertEqual(static.status_code, 200)
        static.close()

    def test_wsgi_wrapper_can_configure_secret_after_import(self):
        module = load_app()
        module.app.secret_key = "wrapper-secret"

        response = module.app.test_client().get("/")

        self.assertEqual(response.status_code, 200)

    def test_direct_launch_uses_ephemeral_secret_and_never_enables_debug(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("change-me-to-a-random-secret-key", source)

        with patch.dict(os.environ, {"FLASK_SECRET_KEY": ""}), patch.object(Flask, "run") as run:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                namespace = runpy.run_path(str(ROOT / "app.py"), run_name="__main__")

        self.assertTrue(namespace["app"].secret_key)
        self.assertFalse(run.call_args.kwargs["debug"])
        self.assertTrue(any("ephemeral" in str(item.message).lower() for item in caught))


class CsrfFormTests(unittest.TestCase):
    def setUp(self):
        self.module = load_app({"FLASK_SECRET_KEY": "test-secret"})
        self.module.ALL_QUESTIONS = question_bank(1)
        self.client = self.module.app.test_client()

    def test_all_post_forms_carry_token_and_legacy_field_can_coexist(self):
        landing = self.client.get("/")
        self.assertEqual(landing.status_code, 200)
        self.assertEqual(landing.headers["Cache-Control"], "no-store")
        self.assertNotIn("; Secure", landing.headers["Set-Cookie"])
        landing_token = csrf_value(landing)

        started = self.client.post(
            "/start",
            data={"csrf_token": landing_token, "_qquiz_csrf": "downstream-wrapper-token"},
        )
        self.assertEqual(started.status_code, 302)

        question = self.client.get("/question")
        self.assertEqual(question.status_code, 200)
        question_token = csrf_value(question)
        answered = self.client.post("/question", data={"answer": "0", "csrf_token": question_token})
        self.assertEqual(answered.status_code, 200)
        self.assertEqual(answered.headers["Cache-Control"], "no-store")
        feedback_token = csrf_value(answered)

        next_response = self.client.post("/next", data={"csrf_token": feedback_token})
        self.assertEqual(next_response.status_code, 302)
        result = self.client.get(next_response.location)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        result_token = csrf_value(result)

        restarted = self.client.post("/restart", data={"csrf_token": result_token})
        self.assertEqual(restarted.status_code, 302)

    def test_all_post_routes_reject_bad_tokens_without_changing_session(self):
        routes = {
            "start": "/start",
            "question": "/question",
            "next": "/next",
            "restart": "/restart",
        }
        for route_name, path in routes.items():
            client = self.module.app.test_client()
            own_token = csrf_value(client.get("/"))
            other_client = self.module.app.test_client()
            other_token = csrf_value(other_client.get("/"))
            self.assertNotEqual(own_token, other_token)
            if route_name != "start":
                with client.session_transaction() as session:
                    session["question_indexes"] = [0, 0]
                    session["current"] = 0
                    session["answers"] = []
                    session["finished"] = False
            baseline = self._session_snapshot(client)
            altered = ("A" if own_token[0] != "A" else "B") + own_token[1:]
            invalid_tokens = [
                ("missing", None),
                ("malformed", "short"),
                ("altered", altered),
                ("cross-session", other_token),
                ("non-ascii", "э" * 43),
            ]

            for kind, token in invalid_tokens:
                data = {"answer": "0"} if route_name == "question" else {}
                if token is not None:
                    data["csrf_token"] = token
                with self.subTest(route=route_name, token=kind):
                    response = client.post(path, data=data)
                    self.assertEqual(response.status_code, 403)
                    self.assertNotEqual(response.status_code, 500)
                    self.assertEqual(self._session_snapshot(client), baseline)

    def test_secure_cookie_setting_is_configurable(self):
        secure_module = load_app(
            {
                "FLASK_SECRET_KEY": "secure-cookie-secret",
                "FLASK_SESSION_COOKIE_SECURE": "true",
            }
        )
        response = secure_module.app.test_client().get("/")
        cookie = response.headers["Set-Cookie"]
        self.assertIn("; HttpOnly", cookie)
        self.assertIn("; SameSite=Lax", cookie)
        self.assertIn("; Secure", cookie)

    def test_missing_answer_does_not_advance_or_record_answer(self):
        landing = self.client.get("/")
        self.client.post("/start", data={"csrf_token": csrf_value(landing)})
        question = self.client.get("/question")
        with self.client.session_transaction() as session:
            before_current = session["current"]
            before_answers = list(session["answers"])

        response = self.client.post("/question", data={"csrf_token": csrf_value(question)})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Пожалуйста, выберите один из вариантов", response.get_data(as_text=True))
        with self.client.session_transaction() as session:
            self.assertEqual(session["current"], before_current)
            self.assertEqual(session["answers"], before_answers)

    def test_empty_question_bank_returns_existing_error_page(self):
        self.module.ALL_QUESTIONS = []
        self.client.get("/")
        with self.client.session_transaction() as session:
            token = session["csrf_token"]

        response = self.client.post("/start", data={"csrf_token": token})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Банк вопросов пуст", response.get_data(as_text=True))

    def test_api_static_content_and_request_size_limit(self):
        api = self.client.get("/api/questions")
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.get_json(), {"total": 1, "session_size": 1})
        static = self.client.get("/static/style.css")
        self.assertEqual(static.status_code, 200)
        self.assertIn(b".container", static.data)
        static.close()
        self.assertEqual(self.module.app.config["MAX_CONTENT_LENGTH"], 16 * 1024)

        token = csrf_value(self.client.get("/"))
        oversized_body = b"csrf_token=" + token.encode("ascii") + b"&padding=" + b"x" * (17 * 1024)
        oversized = self.client.post(
            "/start",
            data=oversized_body,
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(oversized.headers["Cache-Control"], "no-store")

    def test_thirty_answer_flow_feedback_scoring_and_restart(self):
        self.module.ALL_QUESTIONS = question_bank(30)
        landing = self.client.get("/")
        self.assertEqual(self.client.post("/start", data={"csrf_token": csrf_value(landing)}).status_code, 302)

        for answer_number in range(30):
            question = self.client.get("/question")
            with self.client.session_transaction() as session:
                q_index = session["question_indexes"][session["current"]]
            question_data = self.module.ALL_QUESTIONS[q_index]
            correct = question_data["correct"]
            chosen = correct if answer_number < 20 else (correct + 1) % len(question_data["options"])
            feedback = self.client.post(
                "/question",
                data={"answer": str(chosen), "csrf_token": csrf_value(question)},
            )
            self.assertEqual(feedback.status_code, 200)
            self.assertEqual(feedback.headers["Cache-Control"], "no-store")
            next_response = self.client.post("/next", data={"csrf_token": csrf_value(feedback)})
            self.assertEqual(next_response.status_code, 302)

        result = self.client.get(next_response.location)
        result_html = result.get_data(as_text=True)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        self.assertIn("20 из 30", result_html)
        self.assertIn("67%", result_html)
        self.assertIn("Разбор ответов", result_html)
        restart = self.client.post("/restart", data={"csrf_token": csrf_value(result)})
        self.assertEqual(restart.status_code, 302)
        self.assertEqual(restart.location, "/")
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.assertNotIn("question_indexes", session)

    def _session_snapshot(self, client):
        with client.session_transaction() as session:
            return dict(session)


if __name__ == "__main__":
    unittest.main()
