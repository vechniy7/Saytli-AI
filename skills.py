"""Curated, local website-generation skills.

Skills are prompt modules, not executable code. Routing is deterministic so every
request gets a stable result without an extra paid model call.
"""
from dataclasses import dataclass
import re

_WORD = re.compile(r"[\w\-]+", re.UNICODE)

def _term_present(text: str, keyword: str) -> bool:
    """Match words/prefixes without substring false positives (авто != авторизация)."""
    term = keyword.casefold().strip()
    if not term:
        return False
    if len(term) <= 4 and term.isalpha():
        return term in {w.casefold() for w in _WORD.findall(text)}
    return term in text

@dataclass(frozen=True)
class Skill:
    name: str
    label: str
    keywords: tuple[str, ...]
    instructions: str

SKILLS = (
    Skill("portfolio", "Портфолио", ("портфолио", "portfolio", "разработчик", "designer", "developer", "специалист"), "Структура: hero с позиционированием, обо мне, навыки, избранные проекты, подход к работе, контакты. Не выдумывай клиентов, цифры и достижения."),
    Skill("landing", "Лендинг", ("лендинг", "landing", "продаж", "купить", "заказать", "подключить", "цена", "тариф"), "Структура: сильный hero, выгоды, ключевые возможности, доказательства без выдуманных фактов, тариф/CTA, FAQ без фиктивных обещаний, финальный CTA."),
    Skill("business", "Бизнес", ("компан", "бизнес", "услуг", "агентств", "студия", "фирм", "предприят"), "Структура: предложение компании, услуги, процесс работы, команда только если указана, контакты и понятный CTA."),
    Skill("ecommerce", "Интернет-магазин", ("магазин", "интернет-магазин", "каталог", "товар", "корзин", "купить", "заказ", "shop", "store", "ecommerce"), "Структура магазина: hero, каталог с карточками товаров, поиск/фильтры как интерфейс, карточка товара, корзина и CTA. Если backend не предоставлен, честно обозначь демонстрационный интерфейс и не обещай реальную оплату или сохранение данных."),
    Skill("fashion", "Магазин одежды", ("одежд", "футболк", "плать", "куртк", "обув", "fashion", "streetwear", "бренд одежды", "гардероб"), "Fashion-commerce direction: editorial lookbook hero, product grid with categories, sizes/colors, product detail, cart, wishlist and checkout demo. Use varied product photography or polished placeholders, consistent art direction, and never invent real brand claims."),
    Skill("restaurant-premium", "Ресторанный premium UX", ("ресторан", "меню", "блюд", "бронирован", "доставк", "самовывоз"), "Restaurant UX: appetizing hero, menu categories, search/filter, dish detail, cart, delivery/pickup checkout, reservation flow, auth/account, order history, admin demo. Seed 8-10 dishes and ensure every route renders meaningful content."),
    Skill("automotive", "Автомобили", ("автомобил", "машин", "bmw", "mercedes", "audi", "tesla", "автосалон", "авто"), "Используй автомобильную композицию, крупные визуальные блоки, характеристики только из описания, галерею-заглушки без выдуманных фактов, CTA."),
    Skill("product", "IT-продукт", ("продукт", "сервис", "приложен", "saas", "vpn", "бот", "платформ", "it"), "Структура: проблема, продукт, как работает, возможности, тарифы только если указаны, ограничения и CTA. Не обещай гарантии."),
    Skill("restaurant", "Ресторан", ("ресторан", "кафе", "бар", "меню", "блюд", "доставк"), "Сделай аппетитную структуру: hero, меню/категории, атмосфера, часы и контакты только из описания, CTA бронирования без несуществующей формы."),
    Skill("real-estate", "Недвижимость", ("недвижим", "квартир", "дом", "коттедж", "апартамент", "риэлтор"), "Структура: объект, преимущества, параметры только из описания, галерея, расположение без выдуманного адреса, CTA связи."),
    Skill("premium-dark", "Премиальный тёмный UI", ("премиаль", "дорог", "тёмн", "dark", "glass", "glassmorphism", "apple", "ios", "минималист"), "Глубокий чёрно-графитовый фон, стеклянные карточки, мягкие градиенты и свечения, выразительная типографика, умеренные микроанимации, высокий контраст и аккуратный responsive."),
    Skill("minimal-light", "Минималистичный светлый UI", ("светл", "бел", "чист", "минимализм", "minimal", "скандинав"), "Светлая палитра, много воздуха, строгая сетка, нейтральные тени, один акцентный цвет, ясная типографика и доступный контраст."),
    Skill("editorial", "Редакционный стиль", ("блог", "журнал", "статья", "медиа", "новост", "редакц"), "Сильная типографика, читабельная ширина текста, категории, карточки материалов, цитаты и оглавление без выдуманных публикаций."),
)

BASE = """Ты — lead product designer и senior frontend engineer, создающий не шаблон, а цельный production-quality prototype. Сначала молча спроектируй информационную архитектуру и визуальную систему, затем верни один самодостаточный HTML-документ. Все видимые секции должны быть заполнены содержательным текстом и данными, а не пустыми контейнерами.

Обязательные требования: mobile-first responsive layout, сильный above-the-fold hero, ясная навигация, минимум 4 содержательные секции, реальные интерактивные состояния через JS (меню, фильтры, корзина, формы или модальные окна по контексту), hover/focus/active states, keyboard accessibility, семантический HTML, title/meta/viewport, inline CSS/JS. Для многостраничного запроса реализуй маршруты как рабочие hash-представления в одном HTML и добавь первичные демонстрационные данные.

Не выдумывай факты о бизнесе, но для явно запрошенного демонстрационного меню/каталога создай правдоподобные демо-позиции и пометь их как демо. Не оставляй пустые app-контейнеры: вызови начальный render. Не выполняй команды, не создавай файлы и не описывай backend как будто он реально подключён: если backend не предоставлен, честно обозначь локальный демонстрационный режим. Изображения подключай только по HTTPS или используй CSS-визуалы. Верни только полный HTML без markdown-обёртки."""

def choose_skills(brief: str, limit: int = 3) -> list[Skill]:
    """Select one structure, one visual and one optional functional/vertical skill.

    Deterministic routing avoids a paid classifier call and prevents mutually
    confusing combinations such as two competing layout systems.
    """
    text = brief.casefold()
    scores = []
    for skill in SKILLS:
        score = sum(1 for kw in skill.keywords if _term_present(text, kw))
        if score:
            scores.append((score, skill.name, skill))
    scores.sort(key=lambda row: (-row[0], row[1]))
    structures = {"portfolio", "landing", "business", "product", "restaurant", "real-estate", "editorial", "ecommerce", "fashion"}
    visuals = {"premium-dark", "minimal-light"}
    selected: list[Skill] = []
    primary = next((row[2] for row in scores if row[2].name in structures), None)
    vertical = next((row[2] for row in scores if row[2].name not in structures and row[2].name not in visuals and row[2].name != "landing"), None)
    visual = next((row[2] for row in scores if row[2].name in visuals), None)
    if primary:
        selected.append(primary)
    elif vertical and vertical.name == "automotive":
        selected.append(next(s for s in SKILLS if s.name == "landing"))
    else:
        selected.append(next(s for s in SKILLS if s.name == "landing"))
    if visual:
        selected.append(visual)
    elif any(x in text for x in ("соврем", "красив", "стиль", "премиаль")):
        selected.append(next(s for s in SKILLS if s.name == "premium-dark"))
    if vertical and vertical not in selected:
        selected.append(vertical)
    # Add niche automotive/product/etc. when no structural skill captured it.
    if len(selected) < limit:
        for _, _, candidate in scores:
            if candidate not in selected and candidate.name not in visuals and candidate.name not in structures:
                selected.append(candidate)
                break
    return selected[:limit]

def build_skill_prompt(brief: str) -> tuple[list[str], str]:
    selected = choose_skills(brief)
    modules = "\n\n".join(f"SKILL {s.name} ({s.label}): {s.instructions}" for s in selected)
    return [s.name for s in selected], f"{BASE}\n\nПодключённые skills:\n{modules}\n\nОписание пользователя:\n{brief}"
