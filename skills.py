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
    Skill("portfolio", "Портфолио специалиста", ("портфолио", "portfolio", "разработчик", "designer", "developer", "специалист", "фотограф", "фотостуд", "резюме", "обо мне"), "Структура: ясный hero с позиционированием, обо мне, навыки, избранные проекты или кейсы, подход к работе и контакты. Не выдумывай клиентов, цифры, отзывы и достижения."),
    Skill("services", "Страница услуг", ("услуг", "ремонт", "консульт", "агентств", "студия", "мастер", "специалист", "работаю с клиент"), "Структура: кому и чем помогаю, конкретные услуги, процесс работы, примеры работ только из описания, ответы на вопросы и понятный CTA для связи."),
    Skill("project", "Собственный проект", ("проект", "сервис", "продукт", "vpn", "бот", "платформ", "приложен", "стартап", "it"), "Структура: проблема, собственный проект, как он работает, ключевые возможности, ограничения без обещаний, сценарий подключения и CTA. Не выдумывай пользователей, метрики и гарантии."),
    Skill("business", "Личный бизнес", ("компан", "бизнес", "фирм", "предприят", "бренд", "мастерская", "фриланс"), "Структура: позиционирование, услуги или направления, процесс работы, портфолио, ответы на вопросы и контакты. Команду и факты используй только если они указаны."),
    Skill("case-study", "Кейсы и работы", ("кейс", "кейсы", "кейсов", "работы", "работ", "проекты", "проектов", "клиентские работы", "клиентск"), "Сделай выразительную витрину работ: карточки с задачей, решением и результатом только на основе данных пользователя. Не добавляй выдуманные цифры и логотипы клиентов."),
    Skill("premium-dark", "Премиальный тёмный UI", ("премиаль", "дорог", "тёмн", "dark", "glass", "glassmorphism", "apple", "ios", "минималист"), "Глубокий чёрно-графитовый фон, стеклянные карточки, мягкие градиенты и свечения, выразительная типографика, умеренные микроанимации, высокий контраст и аккуратный responsive."),
    Skill("minimal-light", "Минималистичный светлый UI", ("светл", "бел", "чист", "минимализм", "minimal", "скандинав"), "Светлая палитра, много воздуха, строгая сетка, нейтральные тени, один акцентный цвет, ясная типографика и доступный контраст."),
    Skill("editorial", "Редакционный стиль", ("блог", "журнал", "статья", "медиа", "новост", "редакц"), "Сильная типографика и читабельная ширина текста для экспертного личного сайта. Не выдумывай публикации и факты."),
)

BASE = """Ты — lead product designer и senior frontend engineer Saytli AI. Создай цельный production-ready статический сайт-портфолио, а не generic template и не демонстрационный макет. Сначала молча спроектируй информационную архитектуру и визуальную систему, затем верни один самодостаточный HTML-документ. Все видимые секции должны быть заполнены содержательным текстом и данными пользователя.

Обязательные требования: mobile-first responsive layout, сильный above-the-fold hero, ясная навигация, минимум 4 содержательные секции, интерактивное мобильное меню, плавная навигация к секциям, hover/focus/active states, keyboard accessibility, семантический HTML, title/meta/viewport, inline CSS/JS. Для портфолио обязательны: позиционирование, услуги или специализация, проекты/кейсы, процесс работы и контакты.

Не выдумывай факты о человеке, бизнесе, клиентах, отзывах, доходах и достижениях. Не добавляй слова «демо», «demo mode», «прототип» или рекламные служебные баннеры в видимый интерфейс: пользователь должен получить готовую презентационную страницу. Не добавляй магазины, корзины, оплату, каталог товаров, авторизацию или несуществующий backend — это не входит в первую версию. Контактную форму делай как понятный frontend-интерфейс с CTA в Telegram/email, без ложного обещания отправки. Не оставляй пустые app-контейнеры: вызови начальный render. Изображения подключай только по HTTPS или используй CSS-визуалы. Верни только полный HTML без markdown-обёртки."""

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
    structures = {"portfolio", "services", "business", "project", "case-study", "editorial"}
    visuals = {"premium-dark", "minimal-light"}
    selected: list[Skill] = []
    primary = next((row[2] for row in scores if row[2].name in structures), None)
    vertical = next((row[2] for row in scores if row[2].name not in structures and row[2].name not in visuals), None)
    visual = next((row[2] for row in scores if row[2].name in visuals), None)
    if primary:
        selected.append(primary)
    else:
        selected.append(next(s for s in SKILLS if s.name == "portfolio"))
    if visual:
        selected.append(visual)
    elif any(x in text for x in ("соврем", "красив", "стиль", "премиаль")):
        selected.append(next(s for s in SKILLS if s.name == "premium-dark"))
    if vertical and vertical not in selected:
        selected.append(vertical)
    # Add one additional relevant skill without combining conflicting layouts.
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
