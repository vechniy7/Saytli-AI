"""Safe emergency fallback for an unusable model response."""
from html import escape


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
