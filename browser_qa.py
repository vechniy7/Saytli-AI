"""Host-owned lightweight browser smoke checks using stdlib HTML inspection."""
import re
from quality import quality_report, needs_fallback

def browser_smoke(html: str) -> dict:
    scripts = "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script\s*>", html, re.I))
    links = re.findall(r"href=[\"']#([^\"']+)", html, re.I)
    ids = set(re.findall(r"id=[\"']([^\"']+)[\"']", html, re.I))
    checks = {
        "quality": quality_report(html)["passed"],
        "not_blank": not needs_fallback(html),
        "has_navigation": bool(re.search(r"<nav\b|<header\b", html, re.I)),
        "has_interaction": bool(re.search(r"addEventListener|onclick|function\s+", scripts, re.I)),
        "has_mobile_css": bool(re.search(r"@media\b[^{}]*\(", html, re.I)),
        "routes_have_targets": not links or all(x in ids or x in {"home", "menu", "cart", "checkout", "booking", "contacts", "login", "register", "account", "admin", "about"} or re.search(re.escape(x), html, re.I) for x in links),
    }
    return {"checks": checks, "passed": all(checks.values()), "errors": [] if all(checks.values()) else [k for k,v in checks.items() if not v]}
