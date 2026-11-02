"""Deterministic validation for model-generated static HTML."""
import re

from browser_qa import browser_smoke
from pipeline import static_review
from quality import ensure_initial_render, publication_safety_report, quality_report
from responsive_qa import responsive_report
from generation_repair import repair_candidate


def validate_candidate(raw: object) -> dict:
    """Normalize one model response.

    Publication safety and a non-empty HTML document are hard gates. Visual
    quality, interaction and responsive heuristics are reported as warnings so
    a useful site is not discarded because a model omitted one CSS convention.
    """
    if not isinstance(raw, str) or not raw.strip():
        return {"accepted": False, "candidate": "", "errors": ["empty_response"]}

    candidate = re.sub(r"^```(?:html)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    if not re.search(r"<html[\s>]|<!doctype html", candidate, re.I):
        return {"accepted": False, "candidate": candidate, "errors": ["not_html_document"]}

    candidate = repair_candidate(ensure_initial_render(candidate))
    safety = publication_safety_report(candidate)
    quality = quality_report(candidate)
    frontend = static_review(candidate)
    browser = browser_smoke(candidate)
    responsive = responsive_report(candidate)
    errors = list(safety["errors"])
    if not re.search(r"<body\b[\s>][\s\S]*?</body\s*>", candidate, re.I):
        errors.append("missing_body")
    # Keep a very small guard against a blank/error shell, but do not require
    # a large amount of copy: short landing pages are valid sites too.
    visible_body = re.search(r"<body\b[^>]*>([\s\S]*?)</body\s*>", candidate, re.I)
    visible_text = re.sub(r"<script[\s\S]*?</script\s*>|<style[\s\S]*?</style\s*>|<[^>]+>", " ", visible_body.group(1), flags=re.I) if visible_body else ""
    if len(re.sub(r"\s+", " ", visible_text).strip()) < 40:
        errors.append("empty_interface")

    warnings = []
    if quality["score"] < 0.75:
        warnings.append(f"quality_score={quality['score']}")
    if frontend["score"] < 0.75:
        warnings.append(f"frontend_score={frontend['score']}")
    warnings.extend(f"browser:{error}" for error in browser["errors"] if error not in {"quality", "not_blank"})
    if not responsive["passed"]:
        warnings.extend(f"responsive:{error}" for error in responsive["errors"])
    accepted = not errors and safety["passed"]
    return {
        "accepted": accepted,
        "candidate": candidate,
        "errors": errors,
        "warnings": warnings,
        "safety": safety,
        "quality": quality,
        "frontend": frontend,
        "browser": browser,
        "responsive": responsive,
    }
