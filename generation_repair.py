"""Deterministic, conservative repairs for common model-output mistakes."""
import re
from html import escape


def repair_candidate(document: str) -> str:
    """Repair safe mechanical issues without rewriting the generated page.

    This is intentionally limited to publication-boundary and responsive CSS
    fixes.  Content and layout remain model-owned; a malformed second answer
    must not replace a useful first answer merely because it used an iframe or
    a desktop-only width declaration.
    """
    result = document
    repair_needed = bool(re.search(
        r"<(?:iframe|object|embed|applet|base)\b"
        r"|(?<!max-)(?:width|min-width)\s*:\s*(?:100vw|[5-9][0-9]{2,}|[1-9][0-9]{3,})px"
        r"|\bmin-width\s*:\s*(?:[4-9][0-9]{2,}|[1-9][0-9]{3,})px",
        result,
        re.I,
    ))

    def replace_embed(match: re.Match) -> str:
        tag = match.group(0)
        src_match = re.search(r"\b(?:src|data)\s*=\s*['\"]([^'\"]+)['\"]", tag, re.I)
        src = src_match.group(1) if src_match else ""
        if not re.match(r"https?://", src, re.I):
            return "<div class=\"embedded-content\" role=\"note\">Внешний материал доступен по ссылке ниже.</div>"
        return (
            '<p class="embedded-content"><a href="'
            + escape(src, quote=True)
            + '" target="_blank" rel="noopener noreferrer">Открыть внешний материал</a></p>'
        )

    result = re.sub(
        r"<(?:iframe|object|embed|applet)\b[^>]*(?:>.*?</(?:iframe|object|applet)>|/\s*>)",
        replace_embed,
        result,
        flags=re.I | re.S,
    )
    result = re.sub(r"<base\b[^>]*\/?>", "", result, flags=re.I)
    result = re.sub(
        r"(?<!max-)\bwidth\s*:\s*(?:100vw|[5-9][0-9]{2,}|[1-9][0-9]{3,})px",
        "width: 100%; max-width: 100%",
        result,
        flags=re.I,
    )
    result = re.sub(
        r"\bmin-width\s*:\s*(?:[4-9][0-9]{2,}|[1-9][0-9]{3,})px",
        "min-width: 0",
        result,
        flags=re.I,
    )

    styles = """
<style id="saytli-generated-safety">
*, *::before, *::after { box-sizing: border-box; }
img, video, picture, svg, canvas { max-width: 100%; height: auto; }
html, body { max-width: 100%; overflow-x: hidden; }
@media screen and (max-width: 700px) {
  main, section, article, .container, .content, .grid, .cards, .columns, .hero {
    width: 100%; max-width: 100%; min-width: 0;
    grid-template-columns: 1fr !important;
    flex-direction: column !important;
  }
  img, video, picture, svg, canvas { max-width: 100%; height: auto; }
}
</style>
"""
    if repair_needed and 'id="saytli-generated-safety"' not in result:
        head = re.search(r"</head\s*>", result, re.I)
        if head:
            result = result[:head.start()] + styles + result[head.start():]
    return result
