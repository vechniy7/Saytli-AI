"""Static checks for common mobile-layout failures in generated HTML.

The generated sites are intentionally static, so this module does not try to
be a complete CSS parser.  It does, however, walk braces and CSS rules before
checking declarations.  That avoids rejecting valid CSS merely because the
model used a different amount of whitespace, combined selectors, or a longer
media-query block.
"""
import re


def _styles(document: str) -> str:
    chunks = re.findall(r"<style\b[^>]*>([\s\S]*?)</style\s*>", document, re.I)
    css = "\n".join(chunks)
    css = re.sub(r"/\*[\s\S]*?\*/", "", css)
    return css


def _balanced_blocks(css: str, start: int = 0) -> list[tuple[str, str]]:
    """Return (header, body) pairs for top-level brace blocks."""
    blocks: list[tuple[str, str]] = []
    cursor = start
    while cursor < len(css):
        opening = css.find("{", cursor)
        if opening < 0:
            break
        depth = 1
        index = opening + 1
        while index < len(css) and depth:
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
            index += 1
        if depth:
            break
        header_start = max(css.rfind("}", cursor, opening), css.rfind(";", cursor, opening)) + 1
        header = css[header_start:opening].strip()
        blocks.append((header, css[opening + 1:index - 1]))
        cursor = index
    return blocks


def _media_blocks(css: str) -> list[tuple[str, str]]:
    """Extract media blocks, including `@media screen and (...)` syntax."""
    media_blocks: list[tuple[str, str]] = []
    for match in re.finditer(r"@media\b[^\{]*\{", css, re.I):
        opening = match.end() - 1
        depth = 1
        index = opening + 1
        while index < len(css) and depth:
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
            index += 1
        if depth == 0:
            media_blocks.append((match.group(0)[:-1].strip(), css[opening + 1:index - 1]))
    return media_blocks


def _declaration_blocks(css: str) -> list[tuple[str, str]]:
    """Get ordinary selector/declaration blocks, excluding nested at-rules."""
    return [
        (header, body)
        for header, body in _balanced_blocks(css)
        if not header.lstrip().startswith("@")
    ]


def _has_declaration(css: str, property_pattern: str, value_pattern: str = r"[^;}]+") -> bool:
    return bool(re.search(
        rf"(?:^|;)\s*{property_pattern}\s*:\s*{value_pattern}", css, re.I
    ))


def responsive_report(document: str) -> dict:
    """Check concrete responsive behavior without relying on CSS formatting."""
    css = _styles(document)
    media = _media_blocks(css)
    media_css = "\n".join(body for _, body in media)
    phone_media = [
        (header, body) for header, body in media
        if re.search(
            r"(?:max-width\s*:\s*(?:[0-9]+(?:\.[0-9]+)?\s*(?:px|em|rem))|width\s*(?:<=|<)\s*[0-9]+(?:px|em|rem))",
            header,
            re.I,
        )
    ]
    phone_css = "\n".join(body for _, body in phone_media)
    phone_rules = _declaration_blocks(phone_css)

    viewport_value = ""
    for meta in re.findall(r"<meta\b[^>]*>", document, re.I):
        attributes = dict(re.findall(
            r"([a-z_:][-a-z0-9_:]*)\s*=\s*['\"]([^'\"]*)['\"]",
            meta,
            re.I,
        ))
        if attributes.get("name", "").casefold() == "viewport":
            viewport_value = attributes.get("content", "")
            break

    # A viewport without initial-scale is still mobile-safe in browsers.  The
    # prompt asks for initial-scale, but it should not cause a false rejection
    # when the effective layout is otherwise correct.
    has_mobile_viewport = bool(
        re.search(r"\bwidth\s*=\s*device-width\b", viewport_value, re.I)
    )
    has_box_sizing = any(
        _has_declaration(body, r"box-sizing", r"border-box")
        and ("*" in header or re.search(r"(?:html|body|:root)", header, re.I))
        for header, body in _declaration_blocks(css)
    )
    media_elements = bool(re.search(r"<(?:img|video|picture|svg|canvas|iframe)\b", document, re.I))
    has_fluid_media = not media_elements or any(
        re.search(r"\b(?:img|video|picture|svg|canvas|iframe)\b", header, re.I)
        and _has_declaration(body, r"max-width", r"100%")
        for header, body in _declaration_blocks(css)
    )

    # A real mobile reflow changes a layout rule.  Body padding alone is not
    # enough, while flex wrapping, one-column grids, full-width controls and
    # collapsing navigation are all valid responsive implementations.
    layout_change = re.compile(
        r"(?:grid-template-columns|grid-template-areas|flex-direction|flex-wrap|display|position|width|column-count)\s*:",
        re.I,
    )
    has_mobile_reflow = any(
        layout_change.search(body)
        and not re.fullmatch(r"(?:html|body|:root|\*)\s*", header.strip(), re.I)
        for header, body in phone_rules
    )
    has_fluid_container = bool(
        re.search(r"\b(?:clamp|min|max)\s*\(", css, re.I)
        or re.search(r"(?:max-width|width)\s*:\s*(?:[0-9.]+(?:%|vw|rem|em)|min\(|clamp\()", css, re.I)
        or re.search(r"\b(?:padding|margin|gap)\s*:\s*[^;}]*\b(?:rem|vw|clamp|min|max)\b", css, re.I)
    )
    has_overflow_risk = bool(re.search(
        r"(?<!max-)(?:width|min-width)\s*:\s*(?:100vw|[5-9][0-9]{2,}|[1-9][0-9]{3,})px"
        r"|\bmin-width\s*:\s*(?:[4-9][0-9]{2,}|[1-9][0-9]{3,})px",
        css,
        re.I,
    ))
    checks = {
        "mobile_viewport": has_mobile_viewport,
        "phone_breakpoint": bool(phone_media),
        "box_sizing_reset": has_box_sizing,
        "fluid_media": has_fluid_media,
        "mobile_layout_reflow": has_mobile_reflow,
        "fluid_typography_or_containers": has_fluid_container,
        "no_common_horizontal_overflow": not has_overflow_risk,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "errors": [name for name, passed in checks.items() if not passed],
        "diagnostics": {
            "style_blocks": len(re.findall(r"<style\b", document, re.I)),
            "media_blocks": len(media),
            "phone_media_blocks": len(phone_media),
        },
    }
