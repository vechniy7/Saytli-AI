"""Frontend generation quality pipeline: deterministic QA plus an optional AI polish pass."""
import json, re
from quality import ensure_initial_render, quality_report, needs_fallback

REVIEW_SYSTEM = """Ты lead frontend reviewer. Проверь HTML как строгий senior UI/UX, accessibility и JavaScript QA инженер. Верни JSON без markdown с полями: score (0..10), issues (массив строк), fixed_html (полный HTML). Если HTML уже качественный, верни его без потери функций. Всегда сохрани контент, интерактивность и ссылки. Исправь пустые render-контейнеры, отсутствующий initial render, сломанные селекторы и очевидные JS-синтаксические ошибки. Не добавляй backend-заявления."""

def static_review(html: str) -> dict:
    report = quality_report(html)
    scripts = re.findall(r"<script[^>]*>([\s\S]*?)</script\s*>", html, re.I)
    report["checks"].update({
        "has_interaction": bool(scripts and re.search(r"addEventListener|onclick|function\s+", "\n".join(scripts), re.I)),
        "has_images_or_visuals": bool(re.search(r"<img\b|background(?:-image)?\s*:", html, re.I)),
        "has_focus_states": bool(re.search(r":focus(?:-visible)?", html, re.I)),
        "no_empty_app_shell": not needs_fallback(html),
    })
    report["score"] = round(sum(report["checks"].values()) / len(report["checks"]), 2)
    report["passed"] = report["score"] >= 0.8
    return report

def normalize_model_html(raw: str) -> str:
    html = re.sub(r"^```(?:html)?\s*|\s*```$", "", (raw or "").strip(), flags=re.I)
    return ensure_initial_render(html)

def parse_review(raw: str, original: str) -> tuple[str, dict]:
    try:
        data = json.loads(raw)
        candidate = normalize_model_html(data.get("fixed_html", ""))
        if candidate and static_review(candidate)["score"] >= static_review(original)["score"]:
            return candidate, data
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return original, {"score": static_review(original)["score"] * 10, "issues": []}
