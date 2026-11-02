"""Offline contract tests for generation scenarios and recovery paths."""
import unittest

from browser_qa import browser_smoke
from contact_actions import build_contact_actions_fallback
from generation_validation import validate_candidate
from generation_repair import build_safe_fallback_site, repair_candidate
from pipeline import static_review
from quality import publication_safety_report
from responsive_qa import responsive_report
from site_naming import extract_brand_name, set_document_title, site_title, unique_requested_slug, unique_site_slug
from llm_stream import stream_content_piece
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

    def test_brand_name_creates_short_logical_slug_and_title(self):
        brief = "Я владелец компании CuloStore. Мы продаём товары для дома, нужен современный сайт."
        self.assertEqual(extract_brand_name(brief), "CuloStore")
        self.assertEqual(site_title(brief), "CuloStore")
        self.assertEqual(unique_site_slug(brief, []), "culostore")
        self.assertEqual(unique_site_slug(brief, ["culostore"]), "culostore-2")

    def test_requested_slug_is_transliterated_and_collision_safe(self):
        self.assertEqual(unique_requested_slug("Дом Света", []), "dom-sveta")
        self.assertEqual(unique_requested_slug("TsuloIT", ["tsuloit"]), "tsuloit-2")
        self.assertEqual(unique_requested_slug("brand", ["brand", "brand-2"]), "brand-3")

    def test_russian_brand_and_fallback_titles_are_readable(self):
        self.assertEqual(site_title("Компания называется «Дом Света», сделай сайт услуг."), "Дом Света")
        self.assertEqual(unique_site_slug("Компания называется «Дом Света», сделай сайт услуг.", []), "dom-sveta")
        self.assertEqual(site_title("Я фотограф, покажи мои работы и контакты."), "Портфолио")
        document = "<html><head><title>Старое название</title></head><body></body></html>"
        self.assertIn("<title>CuloStore</title>", set_document_title(document, "CuloStore"))

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

    def test_mobile_validation_reports_weak_css_without_blocking_site(self):
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
        self.assertTrue(result["accepted"], result["errors"])
        self.assertTrue(any(error.startswith("responsive:") for error in result["warnings"]))

    def test_responsive_validation_accepts_common_css_formatting_variants(self):
        document = """<!doctype html><html><head>
        <title>TsuloIT</title><meta name="viewport" content="width=device-width">
        <style>
          html, body { box-sizing: border-box; }
          *, *::before, *::after { box-sizing: inherit; }
          img, svg { max-width: 100%; height: auto; }
          .shell { width: min(100% - 2rem, 72rem); }
          .cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
          @media screen and (max-width: 700px) {
            .cards {
              grid-template-columns: repeat(1, minmax(0, 1fr));
              gap: 1rem;
            }
            .menu { display: none; }
          }
        </style></head><body><header><nav class="menu">Menu</nav></header>
        <main class="shell"><section><h1>Заголовок страницы</h1>
        <p>Подробное описание услуги, процесса и следующего шага для клиента.</p></section>
        <section><h2>Услуги</h2><p>Полезная информация о работе и результате.</p></section>
        <section><h2>Контакты</h2><p>Свяжитесь с нами для обсуждения задачи.</p></section></main>
        <script>document.querySelector('nav').addEventListener('click', function () {});</script>
        </body></html>"""
        report = responsive_report(document)
        self.assertTrue(report["passed"], report)
        validation = validate_candidate(document)
        self.assertTrue(validation["accepted"], validation["errors"])

    def test_viewport_attribute_order_does_not_change_result(self):
        document = BASE_HTML.replace(
            '<meta name="viewport" content="width=device-width">',
            '<meta content="width=device-width, initial-scale=1" name="viewport">',
        ).replace(
            '<style>:focus-visible',
            '<style>*, *::before, *::after { box-sizing: border-box; } img { max-width: 100%; } .wrap { max-width: 72rem; width: 100%; } @media screen and (max-width: 48rem) { main { display: block; } } :focus-visible',
        )
        report = responsive_report(document)
        self.assertTrue(report["passed"], report)

    def test_stream_content_piece_supports_sse_delta_and_json_fallback(self):
        self.assertEqual(
            stream_content_piece('data: {"choices":[{"delta":{"content":"<html>"}}]}'),
            "<html>",
        )
        self.assertEqual(
            stream_content_piece('{"choices":[{"message":{"content":"<body>"}}]}'),
            "<body>",
        )
        self.assertIsNone(stream_content_piece("[DONE]"))

    def test_generation_repair_removes_embed_and_fixed_mobile_overflow(self):
        broken = BASE_HTML.replace(
            "</main>",
            '<iframe src="https://maps.example"></iframe><div style="width:1200px">Карта</div></main>',
        )
        repaired = repair_candidate(broken)
        self.assertNotIn("<iframe", repaired.lower())
        self.assertIn("Открыть внешний материал", repaired)
        self.assertNotIn("width:1200px", repaired.replace(" ", "").lower())
        result = validate_candidate(broken)
        self.assertTrue(result["accepted"], result["errors"])

    def test_quality_warnings_do_not_block_a_short_real_page(self):
        short_page = """<!doctype html><html><head><title>TsuloIT</title>
        <meta name="viewport" content="width=device-width"></head><body>
        <header><h1>TsuloIT</h1></header><main><p>Создание Telegram-ботов на заказ. Свяжитесь с нами.</p></main>
        </body></html>"""
        result = validate_candidate(short_page)
        self.assertTrue(result["accepted"], result["errors"])
        self.assertTrue(result["warnings"])

    def test_validation_still_rejects_external_scripts(self):
        unsafe = BASE_HTML.replace(
            "</body>",
            '<script src="https://evil.example/widget.js"></script></body>',
        )
        result = validate_candidate(unsafe)
        self.assertFalse(result["accepted"])
        self.assertIn("no_external_script_tags", result["errors"])

    def test_safe_fallback_is_complete_and_publishable(self):
        fallback = build_safe_fallback_site(
            "Дом Света",
            "Компания по освещению интерьеров. Показываем решения и помогаем выбрать свет.",
        )
        result = validate_candidate(fallback)
        self.assertTrue(result["accepted"], result["errors"])
        self.assertIn("Дом Света", fallback)

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
