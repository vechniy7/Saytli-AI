"""Deterministic validation for model-generated static HTML."""
import re

from browser_qa import browser_smoke
from pipeline import static_review
from quality import ensure_initial_render, needs_fallback, publication_safety_report, quality_report
from responsive_qa import responsive_report


def validate_candidate(raw: object) -> dict:
    """Normalize and validate one model response without network or bot state."""
    if not isinstance(raw, str) or not raw.strip():
        return {"accepted": False, "candidate": "", "errors": ["empty_response"]}

    candidate = re.sub(r"^```(?:html)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    if not re.search(r"<html[\s>]|<!doctype html", candidate, re.I):
        return {"accepted": False, "candidate": candidate, "errors": ["not_html_document"]}

    candidate = ensure_initial_render(candidate)
    safety = publication_safety_report(candidate)
    quality = quality_report(candidate)
    frontend = static_review(candidate)
    browser = browser_smoke(candidate)
    responsive = responsive_report(candidate)
    browser_hard = all(
        browser["checks"].get(key, False)
        for key in ("quality", "not_blank", "has_navigation", "has_interaction", "has_mobile_css")
    )
    errors = list(safety["errors"])
    if quality["score"] < 0.75:
        errors.append(f"quality_score={quality['score']}")
    if frontend["score"] < 0.75:
        errors.append(f"frontend_score={frontend['score']}")
    if not browser_hard:
        errors.extend(f"browser:{error}" for error in browser["errors"])
    if not responsive["passed"]:
        errors.extend(f"responsive:{error}" for error in responsive["errors"])
    accepted = (
        not errors
        and not needs_fallback(candidate)
        and safety["passed"]
        and quality["score"] >= 0.75
        and frontend["score"] >= 0.75
        and browser_hard
        and responsive["passed"]
    )
    return {
        "accepted": accepted,
        "candidate": candidate,
        "errors": errors,
        "safety": safety,
        "quality": quality,
        "frontend": frontend,
        "browser": browser,
        "responsive": responsive,
    }
