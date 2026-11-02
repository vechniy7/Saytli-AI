"""Human-readable site titles and compact, shareable URL slugs."""
import re
from html import escape


_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_BRAND_LABEL = re.compile(
    r"(?:назван\w*\s*(?:бренд\w*|компан\w*|магазин\w*|проект\w*)?\s*(?:это|—|:|-)??|"
    r"(?:бренд|компания|магазин|проект|сервис)\s+(?:называется|название\s*[:—-]?)|"
    r"называется|название\s*[:—-]?)\s*[«\"'`]?"
    r"([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9]*(?:[\s_-]+[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9]*){0,2})",
    re.I,
)
_QUOTED = re.compile(r"[«\"]([^»\"\n]{2,48})[»\"]")
_LATIN_BRAND = re.compile(r"\b(?=[A-Za-z0-9_-]{3,32}\b)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)?\b")


def transliterate(value: str) -> str:
    result = []
    for char in value.casefold():
        if char in _CYRILLIC:
            result.append(_CYRILLIC[char])
        elif char.isascii() and char.isalnum():
            result.append(char)
        elif char.isspace() or char in "-_":
            result.append("-")
    return re.sub(r"-+", "-", "".join(result)).strip("-")


def extract_brand_name(brief: str) -> str | None:
    """Find explicit quoted or named brands without using arbitrary brief text."""
    text = re.sub(r"\s+", " ", brief or "").strip()
    for pattern in (_QUOTED, _BRAND_LABEL):
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip(" .,!?:;—-«»\"'`")
            if 2 <= len(candidate) <= 40:
                return candidate

    # CamelCase and mixed-case Latin names are strong brand signals. Ordinary
    # lowercase words (store, shop, company) are deliberately not candidates.
    for match in _LATIN_BRAND.finditer(text):
        token = match.group(0)
        if (re.search(r"[a-z][A-Z]", token) or re.search(r"\d", token)
                or "-" in token or "_" in token):
            if token.casefold() not in {"telegram", "yandex", "ai", "html", "website"}:
                return token
    return None


def site_title(brief: str) -> str:
    brand = extract_brand_name(brief)
    if brand:
        return brand
    text = (brief or "").casefold()
    for terms, title in (
        (("услуг", "мастер", "ремонт", "салон", "студия", "агентств"), "Сайт услуг"),
        (("проект", "сервис", "приложен", "платформ", "стартап", "продукт"), "Сайт проекта"),
        (("кейс", "работ", "портфолио", "фотограф", "дизайнер", "разработчик"), "Портфолио"),
    ):
        if any(term in text for term in terms):
            return title
    return "Сайт специалиста"


def unique_site_slug(brief: str, existing_ids) -> str:
    """Generate a short URL slug and a stable numeric suffix on name collision."""
    brand = extract_brand_name(brief)
    base = transliterate(brand) if brand else ""
    if not base:
        title = site_title(brief)
        base = transliterate(title)
    base = re.sub(r"[^a-z0-9-]", "", base).strip("-")[:32].rstrip("-") or "site"
    existing = set(existing_ids or ())
    if base not in existing:
        return base
    index = 2
    while f"{base}-{index}" in existing:
        index += 1
    return f"{base}-{index}"


def set_document_title(document: str, title: str) -> str:
    """Make browser/tab title agree with the recognizable site name."""
    safe_title = escape(title, quote=False)
    title_tag = re.compile(r"<title\b[^>]*>[\s\S]*?</title\s*>", re.I)
    if title_tag.search(document):
        return title_tag.sub(f"<title>{safe_title}</title>", document, count=1)
    head_close = re.search(r"</head\s*>", document, re.I)
    if head_close:
        return document[:head_close.start()] + f"<title>{safe_title}</title>\n" + document[head_close.start():]
    return document
