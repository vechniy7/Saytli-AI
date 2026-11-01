"""Deterministic checks and normalizers for generated static sites."""
import re

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
