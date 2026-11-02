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


def build_safe_fallback_site(title: str, brief: str) -> str:
    """Build a small, complete static page if the model returns unusable HTML.

    User-provided text is escaped and inserted as text only. The fallback has
    no scripts, remote resources, forms, or generated executable markup.
    """
    safe_title = escape((title or "Мой сайт").strip()[:120])
    safe_brief = escape((brief or "").strip()[:5000])
    if not safe_brief:
        safe_brief = "Здесь скоро появится информация о проекте."

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; color: #18202b; background: #f5f7fa; font: 16px/1.6 system-ui, sans-serif; }}
    header {{ padding: 1rem max(1.25rem, calc((100vw - 880px) / 2)); background: #fff; border-bottom: 1px solid #e5e9ef; }}
    main {{ width: min(100% - 2rem, 880px); margin: 4rem auto; }}
    section {{ padding: clamp(1.5rem, 5vw, 3.5rem); background: #fff; border: 1px solid #e5e9ef; border-radius: 1.25rem; }}
    h1 {{ margin: 0 0 1rem; font-size: clamp(2rem, 6vw, 3.5rem); line-height: 1.1; }}
    p {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
    .note {{ margin-top: 2rem; color: #596575; }}
    @media (max-width: 600px) {{ main {{ margin: 1.5rem auto; }} }}
  </style>
</head>
<body>
  <header><strong>{safe_title}</strong></header>
  <main>
    <section aria-labelledby="page-title">
      <h1 id="page-title">{safe_title}</h1>
      <p>{safe_brief}</p>
      <p class="note">Свяжитесь с нами, чтобы узнать подробности и обсудить ваш запрос.</p>
    </section>
  </main>
</body>
</html>"""
