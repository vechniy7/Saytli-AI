"""Offline contract tests for generation scenarios and recovery paths."""
import unittest

from browser_qa import browser_smoke
from contact_actions import build_contact_actions_fallback
from generation_validation import validate_candidate
from pipeline import static_review
from quality import publication_safety_report
from responsive_qa import responsive_report
from skills import choose_skills


BASE_HTML = """<!doctype html>
<html><head><title>Сайт специалиста</title><meta name="viewport" content="width=device-width">
<style>:focus-visible { outline: 2px solid currentColor; } @media (max-width: 700px) { body { padding: 1rem; } }</style>
</head><body><header><nav><a href="#about">Обо мне</a></nav></header>
<main><section id="about"><h1>Специалист</h1><p>Описание специалиста и его подхода к работе. Здесь достаточно полезной информации для посетителя сайта и будущего клиента.</p></section>
<section><h2>Услуги</h2><p>Помогаю решить задачу, уточняю детали, показываю понятный процесс и передаю аккуратно подготовленный результат.</p></section>
<section><h2>Контакты</h2><p>Свяжитесь со мной, чтобы обсудить задачу и следующий шаг сотрудничества.</p></section></main>
<script>document.querySelector('a').addEventListener('click', function () {});</script></body></html>"""


class UXGenerationTests(unittest.TestCase):
    def test_common_site_scenarios_route_to_supported_structures(self):
        scenarios = {
            "Личное портфолио UX-дизайнера": "portfolio",
            "Страница услуг мастера по ремонту техники": "services",
            "Сайт собственного AI проекта": "project",
            "Витрина клиентских кейсов и работ": "case-study",
            "Сайт фотографа с проектами": "portfolio",
        }
        for brief, expected in scenarios.items():
            with self.subTest(brief=brief):
                self.assertIn(expected, [skill.name for skill in choose_skills(brief)])

    def test_valid_model_candidate_is_accepted(self):
        result = validate_candidate(BASE_HTML.replace(
            '<meta name="viewport" content="width=device-width">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
        ).replace(
            '<style>:focus-visible',
            '<style>*, *::before, *::after { box-sizing: border-box; } img, video, picture, svg { max-width: 100%; height: auto; } .wrap { max-width: min(100% - 2rem, 72rem); } @media (max-width: 700px) { main { grid-template-columns: 1fr; } } :focus-visible',
        ))
        self.assertTrue(result["accepted"], result["errors"])
        self.assertEqual(result["candidate"].count("<html"), 1)

    def test_mobile_validation_rejects_media_query_without_reflow(self):
        weak = BASE_HTML.replace(
            '<meta name="viewport" content="width=device-width">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
        ).replace(
            '<style>:focus-visible',
            '<style>*, *::before, *::after { box-sizing: border-box; } img, video, picture, svg { max-width: 100%; height: auto; } .wrap { max-width: min(100% - 2rem, 72rem); } :focus-visible',
        ).replace('@media (max-width: 700px) { body { padding: 1rem; } }', '@media (max-width: 700px) { body { padding: 1rem; } }')
        report = responsive_report(weak)
        self.assertFalse(report["passed"])
        self.assertIn("mobile_layout_reflow", report["errors"])
        result = validate_candidate(weak)
        self.assertFalse(result["accepted"])
        self.assertTrue(any(error.startswith("responsive:") for error in result["errors"]))

    def test_invalid_first_candidate_is_rejected_with_actionable_reasons(self):
        result = validate_candidate("```html\n<iframe src='https://example.com'></iframe>\n```")
        self.assertFalse(result["accepted"])
        self.assertTrue(result["errors"])
        self.assertIn("not_html_document", result["errors"])

    def test_contact_fallback_is_safe_and_idempotent(self):
        updated = build_contact_actions_fallback(BASE_HTML, "добавь карту, маршрут через Яндекс.Карты и кнопку Telegram @tsuloew")
        self.assertIsNotNone(updated)
        self.assertIn("https://yandex.ru/maps/", updated)
        self.assertIn("https://t.me/tsuloew", updated)
        self.assertTrue(publication_safety_report(updated)["passed"])
        self.assertTrue(static_review(updated)["passed"])
        self.assertTrue(browser_smoke(updated)["passed"])
        self.assertEqual(build_contact_actions_fallback(updated, "добавь карту и Telegram"), updated)


if __name__ == "__main__":
    unittest.main()
