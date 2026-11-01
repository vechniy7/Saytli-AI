"""Deterministic checks and normalizers for generated static sites."""
import re


def publication_safety_report(html: str) -> dict:
    """Reject markup that could escape the static-site publication boundary.

    Generated HTML is untrusted model output.  The checks intentionally target
    the small, single-file frontend contract used by Saytli instead of trying
    to turn a regex parser into a general-purpose HTML sanitizer.
    """
    body_match = re.search(r"<body\b[^>]*>([\s\S]*?)</body\s*>", html, re.I)
    visible = ""
    if body_match:
        visible = re.sub(r"<script[\s\S]*?</script\s*>|<style[\s\S]*?</style\s*>|<[^>]+>", " ", body_match.group(1), flags=re.I)
        visible = re.sub(r"\s+", " ", visible).strip().casefold()

    checks = {
        "no_dangerous_embeds": not re.search(r"<(?:iframe|object|embed|applet|base)\b", html, re.I),
        "no_refresh_redirect": not re.search(r"<meta\b[^>]*http-equiv\s*=\s*[\"']?refresh", html, re.I),
        "no_inline_event_handlers": not re.search(r"\son[a-z][a-z0-9_-]*\s*=", html, re.I),
        "no_script_urls": not re.search(r"(?:href|src|action|formaction|poster|xlink:href)\s*=\s*[\"']\s*(?:javascript|vbscript):", html, re.I),
        "no_external_script_tags": not re.search(r"<script\b[^>]+\bsrc\s*=\s*[\"']\s*(?:https?:)?//", html, re.I),
        "no_external_network_code": not re.search(r"\b(?:fetch|XMLHttpRequest|WebSocket)\s*\(|navigator\.sendBeacon\s*\(|document\.cookie\b", html, re.I),
        "no_service_banners": not re.search(r"\b(?:demo(?:\s|-)?mode|prototype)\b|демо[\s-]*режим|локальн(?:ый|ая)\s+демо", visible, re.I),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "errors": [name for name, passed in checks.items() if not passed],
    }

def quality_report(html: str) -> dict:
    low = html.casefold()
    checks = {
        "html_document": bool(re.search(r"<!doctype html|<html[\s>]", html, re.I)),
        "has_title": bool(re.search(r"<title>\s*[^<]{3,}\s*</title>", html, re.I)),
        "has_viewport": bool(re.search(r"name=[\"']viewport[\"']", html, re.I)),
        "has_body_content": bool(re.search(r"<body[^>]*>[\s\S]{300,}</body>", html, re.I)),
        "has_sections": len(re.findall(r"<(?:section|main|article|header|footer|nav)\b", html, re.I)) >= 3,
        "has_responsive_css": bool(re.search(r"@media\s*\(", html, re.I)),
        "no_markdown_fence": "```" not in html,
        "not_error_page": not any(x in low for x in ("unable to generate", "generation failed", "i cannot")),
    }
    return {"checks": checks, "score": round(sum(checks.values()) / len(checks), 2), "passed": all(checks.values())}

def ensure_initial_render(html: str) -> str:
    if not re.search(r"function\s+render\s*\(", html, re.I):
        return html
    scripts = "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script\s*>", html, re.I))
    if re.search(r"(?:^|[;{}\n])\s*render\s*\(\s*\)\s*;?", scripts):
        return html
    marker = re.search(r"</script\s*>", html, re.I)
    if not marker:
        return html
    return html[:marker.start()] + "\ntry { render(); } catch (e) { console.error(e); }\n" + html[marker.start():]

def needs_fallback(html: str) -> bool:
    """Reject shells that passed superficial HTML checks but have no useful UI."""
    body = re.search(r"<body[^>]*>([\s\S]*?)</body>", html, re.I)
    if not body:
        return True
    visible = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", " ", body.group(1), flags=re.I)
    return len(re.sub(r"\s+", " ", visible).strip()) < 180
