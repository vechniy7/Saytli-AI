"""Deterministic validation for model-generated static HTML."""
import html as html_lib
import re

from browser_qa import browser_smoke
from pipeline import static_review
from quality import publication_safety_report, quality_report
from responsive_qa import responsive_report


def _image_warnings(html: str) -> list[str]:
    warnings: list[str] = []
    for tag in re.findall(r"<img\b[^>]*>", html, re.I):
        if not re.search(r"\bloading\s*=", tag, re.I):
            warnings.append("missing_loading_hint")
        if not re.search(r"\bwidth\s*=|\baspect-ratio\s*:", tag, re.I):
            warnings.append("missing_reserved_dimensions")
        src = re.search(r"\bsrc\s*=\s*['\"]([^'\"]+)", tag, re.I)
        if src and not re.match(r"https://|/", src.group(1), re.I):
            warnings.append("non_https_image_source")
    return sorted(set(warnings))


def validate_candidate(
    raw: object,
    expected_asset_urls: list[str] | None = None,
    require_assets: bool = False,
) -> dict:
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

    # Do not rewrite a valid model design before publication. The validator
    # checks it as authored; only markdown fences are normalized above.
    candidate = candidate.strip()
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
    image_count = len(re.findall(r"<img\b", candidate, re.I))
    images_without_alt = len(re.findall(r"<img\b(?![^>]*\balt\s*=)[^>]*>", candidate, re.I))
    if images_without_alt:
        warnings.append(f"images_without_alt={images_without_alt}")
    if image_count:
        warnings.extend(f"image:{error}" for error in _image_warnings(candidate))
    asset_usage = _asset_usage(candidate, expected_asset_urls or [])
    warnings.extend(f"assets:{error}" for error in asset_usage["warnings"])
    if require_assets and asset_usage["warnings"]:
        errors.extend(f"assets:{error}" for error in asset_usage["warnings"])
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
        "assets": asset_usage,
    }


def _asset_usage(html: str, expected_urls: list[str]) -> dict:
    """Check whether model output preserved the resolver's trusted image URLs."""
    if not expected_urls:
        return {"expected": [], "used": [], "warnings": []}
    image_tags = "\n".join(re.findall(r"<img\b[^>]*>", html, re.I))
    normalized_tags = html_lib.unescape(image_tags)
    used = [url for url in expected_urls if url in normalized_tags]
    sources = re.findall(r"\bsrc\s*=\s*['\"](https://[^'\"]+)", normalized_tags, re.I)
    warnings = [] if used else ["trusted_asset_not_used"]
    if any(source not in expected_urls for source in sources):
        warnings.append("unapproved_external_image")
    return {"expected": expected_urls, "used": used, "warnings": sorted(set(warnings))}
