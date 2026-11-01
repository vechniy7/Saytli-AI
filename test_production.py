"""Focused regression tests for the production v1 contract."""
import unittest

from browser_qa import browser_smoke
from design_systems import select_design_system
from pipeline import static_review
from quality import publication_safety_report
from skills import choose_skills


SAFE_HTML = """<!doctype html>
<html><head><title>Portfolio</title><meta name="viewport" content="width=device-width"></head>
<body><header><nav><a href="#work">Работы</a></nav></header>
<main><section id="work">Работы специалиста. Контакты и описание услуг. Свяжитесь со мной для обсуждения проекта. Здесь собраны ключевые задачи, подход к работе и понятные следующие шаги для нового сотрудничества.</section>
<section>Процесс работы и специализация. Сначала уточняем задачу, затем собираем решение, показываем промежуточный результат и передаём аккуратно подготовленный итоговый материал.</section></main><footer>Контакты и способы связи</footer>
<style>@media (max-width: 700px) { body { padding: 1rem; } }</style>
<script>document.querySelector('a').addEventListener('click', function () {});</script></body></html>"""


class ProductionContractTests(unittest.TestCase):
    def test_supported_routing_has_no_legacy_verticals(self):
        for brief, expected in (
            ("личное портфолио разработчика", "portfolio"),
            ("страница услуг мастера по ремонту телефонов", "services"),
            ("сайт собственного AI проекта", "project"),
        ):
            names = [skill.name for skill in choose_skills(brief)]
            self.assertIn(expected, names)
            self.assertNotIn(names[0], {"restaurant", "ecommerce", "fashion", "landing", "shop"})

    def test_design_systems_match_v1_scenarios(self):
        self.assertEqual(select_design_system(["portfolio"])["id"], "studio-portfolio")
        self.assertEqual(select_design_system(["services"])["id"], "clear-service-studio")
        self.assertEqual(select_design_system(["project"])["id"], "product-story")

    def test_safe_html_passes_static_and_browser_checks(self):
        self.assertTrue(publication_safety_report(SAFE_HTML)["passed"])
        self.assertTrue(static_review(SAFE_HTML)["passed"])
        self.assertTrue(browser_smoke(SAFE_HTML)["passed"])

    def test_unsafe_markup_is_rejected(self):
        unsafe = SAFE_HTML.replace("</main>", "<iframe src=\"https://evil.example\"></iframe></main>")
        report = publication_safety_report(unsafe)
        self.assertFalse(report["passed"])
        self.assertIn("no_dangerous_embeds", report["errors"])

    def test_service_banner_is_rejected_only_when_visible(self):
        unsafe = SAFE_HTML.replace("Контакты и способы связи", "prototype")
        self.assertFalse(publication_safety_report(unsafe)["passed"])


if __name__ == "__main__":
    unittest.main()
