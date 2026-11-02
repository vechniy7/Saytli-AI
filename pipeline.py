"""Frontend generation quality pipeline and AI polish contract."""
import json, re
from quality import ensure_initial_render, quality_report, needs_fallback, publication_safety_report

REVIEW_SYSTEM = """Ты — независимый principal product designer, frontend engineer и QA reviewer. Твоя задача — улучшить уже выбранный AI-дизайн, а не заменить его шаблоном. Верни только JSON без markdown с полями: score (0..10), issues (массив строк), fixed_html (полный HTML-документ).

Сохрани индивидуальную арт-дирекцию, контент, композицию и сильные решения исходника. Исправь только то, что реально ухудшает результат. Проверь и при необходимости улучши:
- визуальную иерархию, типографику, контраст, ритм, глубину и единый характер;
- выразительную, уместную CSS-анимацию появления/скролла/hover или другой motion-язык, обязательно с prefers-reduced-motion;
- каждую кнопку, ссылку, меню, tab, accordion и форму: у каждого контрола должен быть понятный рабочий сценарий, не оставляй мёртвых кнопок;
- существование целей у hash-ссылок, aria-label/aria-expanded для раскрывающихся элементов, keyboard focus;
- отсутствие ошибок в селекторах и очевидных JavaScript-ошибок, начальный render;
- мобильную версию 320–1440px без горизонтального overflow.

Не добавляй backend-заявления, выдуманные факты, внешние script-теги, iframe/object/embed, fetch, XMLHttpRequest, WebSocket, document.cookie, javascript:-ссылки или inline on* handlers. Не превращай страницу в generic SaaS, dashboard или одинаковый набор карточек. Если исходник уже хорош, верни его без изменений."""

def static_review(html: str) -> dict:
    report = quality_report(html)
    scripts = re.findall(r"<script[^>]*>([\s\S]*?)</script\s*>", html, re.I)
    report["checks"].update({
        "has_interaction": bool(scripts and re.search(r"addEventListener|onclick|function\s+", "\n".join(scripts), re.I)),
        "has_images_or_visuals": bool(re.search(r"<img\b|background(?:-image)?\s*:", html, re.I)),
        "has_focus_states": bool(re.search(r":focus(?:-visible)?", html, re.I)),
        "no_empty_app_shell": not needs_fallback(html),
    })
    report["checks"].update(publication_safety_report(html)["checks"])
    report["score"] = round(sum(report["checks"].values()) / len(report["checks"]), 2)
    report["passed"] = report["score"] >= 0.8
    report["experience"] = experience_report(html)
    return report


def experience_report(html: str) -> dict:
    """Report polish signals without making subjective design a hard gate."""
    scripts = "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script\s*>", html, re.I))
    buttons = re.findall(r"<button\b[^>]*>", html, re.I)
    anchors = re.findall(r"<a\b[^>]*>", html, re.I)
    has_motion = bool(re.search(r"@keyframes\b|\banimation(?:-name)?\s*:|\btransition\s*:", html, re.I))
    has_reduced_motion = bool(re.search(r"prefers-reduced-motion", html, re.I))
    has_event_wiring = bool(re.search(r"addEventListener\s*\(|\.onclick\s*=|function\s*\(", scripts, re.I))
    has_focus = bool(re.search(r":focus(?:-visible)?\b", html, re.I))
    buttons_have_type = not buttons or all(re.search(r"\btype\s*=", tag, re.I) for tag in buttons)
    anchor_targets = all(
        not re.search(r"href\s*=\s*[\"'](?:#|javascript:)?[\"']", tag, re.I)
        for tag in anchors
    )
    checks = {
        "has_motion": has_motion,
        "reduced_motion_support": not has_motion or has_reduced_motion,
        "controls_have_event_wiring": not buttons or has_event_wiring,
        "button_semantics": buttons_have_type,
        "links_have_targets": anchor_targets,
        "keyboard_focus": has_focus,
    }
    return {
        "checks": checks,
        "score": round(sum(checks.values()) / len(checks), 2),
        "warnings": [name for name, passed in checks.items() if not passed],
    }

def normalize_model_html(raw: str) -> str:
    html = re.sub(r"^```(?:html)?\s*|\s*```$", "", (raw or "").strip(), flags=re.I)
    return ensure_initial_render(html)

def parse_review(raw: str, original: str) -> tuple[str, dict]:
    try:
        cleaned = (raw or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
        if not cleaned.startswith("{"):
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start:end + 1]
        data = json.loads(cleaned)
        candidate = normalize_model_html(data.get("fixed_html", ""))
        if candidate:
            return candidate, data
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return original, {"score": static_review(original)["score"] * 10, "issues": []}
