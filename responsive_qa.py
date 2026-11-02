"""Static checks for common mobile-layout failures in generated HTML."""
import re


def responsive_report(document: str) -> dict:
    """Check for concrete responsive behavior, not just any @media rule."""
    css = "\n".join(re.findall(r"<style\b[^>]*>([\s\S]*?)</style\s*>", document, re.I))
    checks = {
        "mobile_viewport": bool(re.search(
            r"<meta\b(?=[^>]*\bname\s*=\s*['\"]viewport['\"])(?=[^>]*\bcontent\s*=\s*['\"][^'\"]*width\s*=\s*device-width)(?=[^>]*\bcontent\s*=\s*['\"][^'\"]*initial-scale\s*=\s*1)[^>]*>",
            document, re.I,
        )),
        "phone_breakpoint": bool(re.search(
            r"@media\s*\([^)]*max-width\s*:\s*(?:[0-9]{2,4}(?:\.[0-9]+)?\s*(?:px|em|rem))",
            css, re.I,
        )),
        "box_sizing_reset": bool(re.search(r"\*\s*,\s*\*::before\s*,\s*\*::after\s*\{[^}]*box-sizing\s*:\s*border-box", css, re.I)
                                  or re.search(r"\*\s*\{[^}]*box-sizing\s*:\s*border-box", css, re.I)),
        "fluid_media": bool(re.search(r"(?:img|video|picture|svg)\s*\{[^}]*max-width\s*:\s*100%", css, re.I)),
        "mobile_layout_reflow": bool(re.search(
            r"@media\s*\([^)]*max-width\s*:[^)]*\)\s*\{[\s\S]{0,1800}?(?:grid-template-columns\s*:\s*1fr|flex-direction\s*:\s*column|display\s*:\s*none|width\s*:\s*100%)",
            css, re.I,
        )),
        "fluid_typography_or_containers": bool(re.search(r"\b(?:clamp|min|max)\s*\(", css, re.I)
                                                     or re.search(r"max-width\s*:\s*(?:min\(|[0-9.]+(?:%|vw|rem|em))", css, re.I)),
        "no_common_horizontal_overflow": not bool(re.search(
            r"(?<!max-)(?:width|min-width)\s*:\s*(?:100vw|[5-9][0-9]{2,}|[1-9][0-9]{3,})px|\bmin-width\s*:\s*(?:[4-9][0-9]{2,}|[1-9][0-9]{3,})px",
            css, re.I,
        )),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "errors": [name for name, passed in checks.items() if not passed],
    }
