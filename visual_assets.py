"""Resolve a small set of real, source-attributed visual assets for generation.

Product photos are never invented by CSS. Recognized Apple product briefs use
the official product page's Open Graph image; general editorial photography
can use Unsplash only when an application key is configured.
"""
from dataclasses import dataclass
import html
import os
import re
from urllib.parse import urljoin, urlparse



@dataclass(frozen=True)
class VisualAsset:
    url: str
    alt: str
    source: str
    credit: str = ""
    required: bool = False


def _is_https_host(url: str, host: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == host


def _apple_page(brief: str) -> tuple[str, str] | None:
    text = brief.casefold()
    if not re.search(r"\biphone\b|айфон|айфона|айфону|айфоны", text):
        return None
    # Use the live official product page, rather than guessing a CDN filename.
    # If Apple's current lineup changes, the page's own metadata remains the
    # source of truth and the asset pass simply falls back when unavailable.
    model_match = re.search(r"iphone\s*(17|16|15|14)\b|айфон\s*(17|16|15|14)\b", text)
    generation = next((group for group in model_match.groups() if group), "17") if model_match else "17"
    return f"https://www.apple.com/iphone-{generation}/", f"Apple iPhone {generation}"


def _meta_content(document: str, property_name: str) -> str:
    """Read a meta content value regardless of attribute order or quote style."""
    for tag in re.findall(r"<meta\b[^>]*>", document, re.I):
        prop = re.search(r"\bproperty\s*=\s*(['\"])(.*?)\1", tag, re.I)
        if prop and prop.group(2).casefold() == property_name.casefold():
            content = re.search(r"\bcontent\s*=\s*(['\"])(.*?)\1", tag, re.I)
            return content.group(2).strip() if content else ""
    return ""


async def resolve_visual_assets(brief: str) -> list[VisualAsset]:
    """Get verifiable source URLs. Network failures are deliberately non-fatal."""
    # Keep the pure prompt/tests importable in the lightweight local test
    # environment; the production image resolver already ships with httpx.
    import httpx

    assets: list[VisualAsset] = []
    headers = {"User-Agent": "SaytliAI/1.0 (website image metadata resolver)"}
    timeout = httpx.Timeout(12.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        apple = _apple_page(brief)
        if apple:
            page_url, label = apple
            try:
                response = await client.get(page_url)
                response.raise_for_status()
                image_url = _meta_content(response.text, "og:image")
                # Apple publishes responsive product photography in the page
                # itself. Prefer product/contrast images over a social-card
                # preview, then pass a small curated set to the model.
                page_images = re.findall(
                    r"(?:src|srcset|data-src|data-lazy-src)\s*=\s*['\"]([^'\"]+)",
                    response.text,
                    re.I,
                )
                candidates = sorted(
                    page_images,
                    key=lambda url: (
                        0 if re.search(r"/(?:contrast|product|hero)/", url, re.I) else 1,
                        1 if re.search(r"(?:small|thumb)", url, re.I) else 0,
                    ),
                )
                if image_url:
                    candidates.append(image_url)
                seen: set[str] = set()
                for raw_url in candidates:
                    raw_url = html.unescape(raw_url).split(",")[0].strip().split(" ")[0]
                    image_url = urljoin(page_url, raw_url)
                    if not _is_https_host(image_url, "www.apple.com") or image_url in seen:
                        continue
                    if not re.search(r"\.(?:png|jpe?g|webp)(?:[?#]|$)", image_url, re.I):
                        continue
                    seen.add(image_url)
                    description = "Официальная фотография продукта Apple"
                    if "camera" in image_url:
                        description = "Официальная фотография камеры iPhone"
                    assets.append(VisualAsset(image_url, description, "Apple", "Изображение: Apple", required=not assets))
                    if len(assets) >= 4:
                        break
            except (httpx.HTTPError, ValueError):
                pass

        unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
        if unsplash_key and not assets:
            query = re.sub(r"\s+", " ", brief).strip()[:160]
            try:
                response = await client.get(
                    "https://api.unsplash.com/search/photos",
                    params={"query": query, "per_page": 3, "orientation": "landscape", "content_filter": "high"},
                    headers={"Authorization": f"Client-ID {unsplash_key}", "Accept-Version": "v1"},
                )
                response.raise_for_status()
                results = response.json().get("results", [])
                for photo in results[:3]:
                    image_url = photo.get("urls", {}).get("regular", "")
                    if not _is_https_host(image_url, "images.unsplash.com"):
                        continue
                    photographer = str(photo.get("user", {}).get("name", "Unsplash contributor"))
                    profile = str(photo.get("user", {}).get("links", {}).get("html", "https://unsplash.com"))
                    photo_page = str(photo.get("links", {}).get("html", "https://unsplash.com"))
                    if not _is_https_host(profile, "unsplash.com") or not _is_https_host(photo_page, "unsplash.com"):
                        profile, photo_page = "https://unsplash.com", "https://unsplash.com"
                    credit = f'Фото: <a href="{html.escape(photo_page, quote=True)}">{html.escape(photographer)}</a> / <a href="https://unsplash.com">Unsplash</a>'
                    alt = str(photo.get("alt_description") or photo.get("description") or "")[:180]
                    assets.append(VisualAsset(image_url, alt or "Фотография по теме проекта", "Unsplash", credit))
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass

        # Openverse is the no-secret path for commercially usable Creative
        # Commons/public-domain photography. Keep the license and landing page
        # in the prompt so the generated site can show attribution.
        if not assets and not apple:
            query = re.sub(r"\s+", " ", brief).strip()[:180]
            try:
                response = await client.get(
                    "https://api.openverse.org/v1/images/",
                    params={
                        "q": query,
                        "category": "photograph",
                        "license_type": "commercial",
                        "filter_dead": "true",
                        "mature": "false",
                        "size": "large",
                        "page_size": 3,
                    },
                )
                response.raise_for_status()
                for image in response.json().get("results", [])[:3]:
                    image_url = str(image.get("url", ""))
                    landing_url = str(image.get("foreign_landing_url", ""))
                    if not image_url.startswith("https://") or not landing_url.startswith("https://"):
                        continue
                    title = str(image.get("title") or "Фотография по теме проекта")[:160]
                    creator = str(image.get("creator") or "Автор не указан")[:100]
                    license_name = str(image.get("license") or "Creative Commons")
                    credit = (
                        f'Фото: <a href="{html.escape(landing_url, quote=True)}">{html.escape(title)}</a>; '
                        f'{html.escape(creator)}; лицензия {html.escape(license_name)} '
                        f'(<a href="{html.escape(landing_url, quote=True)}">источник</a>)'
                    )
                    assets.append(VisualAsset(image_url, title, "Openverse", credit))
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass
        verified: list[VisualAsset] = []
        for asset in assets:
            try:
                image_response = await client.head(asset.url)
                content_type = image_response.headers.get("content-type", "").split(";", 1)[0].lower()
                if image_response.is_success and content_type.startswith("image/"):
                    verified.append(asset)
            except httpx.HTTPError:
                continue
    return verified


def assets_prompt(assets: list[VisualAsset]) -> str:
    if not assets:
        return (
            "\n\nРЕАЛЬНЫЕ ВИЗУАЛЬНЫЕ МАТЕРИАЛЫ: проверенного предметного фото не найдено. "
            "Не рисуй реалистичные товары, устройства, людей или интерьеры CSS/SVG и не придумывай URL. "
            "Для точного продукта используй редакционную типографику, цвет, свет и геометрию без фальшивого предмета; "
            "не подменяй конкретный товар случайным стоковым изображением."
        )
    lines = ["\n\nПРОВЕРЕННЫЕ РЕАЛЬНЫЕ ИЗОБРАЖЕНИЯ (используй эти URL буквально, не меняй домен/путь):"]
    for index, asset in enumerate(assets, 1):
        requirement = "ОБЯЗАТЕЛЬНО используй минимум одно из этих официальных изображений." if asset.required else "Используй, только если изображение точно соответствует задаче."
        lines.append(f"{index}. URL: {asset.url}\n   Alt: {asset.alt}\n   Источник: {asset.source}\n   Атрибуция: {asset.credit}\n   Правило: {requirement}")
    lines.append(
        "Используй реальное фото как ключевой визуал, если оно точно соответствует товару. "
        "Не создавай рядом CSS/SVG-аналог этого предмета. Для изображений задай width/height или aspect-ratio, "
        "object-fit и корректный alt; ниже первого экрана добавь loading=lazy. Атрибуцию покажи компактно рядом с фотографией."
    )
    return "\n".join(lines)
