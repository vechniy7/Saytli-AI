import asyncio
import html
import json
import logging
import os
import re
import secrets
import hashlib
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    BotCommandScopeDefault,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from dotenv import load_dotenv
from skills import build_skill_prompt
from quality import ensure_initial_render, quality_report, needs_fallback, publication_safety_report
from pipeline import static_review
from design_systems import select_design_system
from browser_qa import browser_smoke
from generation_validation import validate_candidate
from contact_actions import build_contact_actions_fallback as build_safe_contact_actions_fallback
from site_naming import set_document_title, site_title, unique_site_slug

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("saytli")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
LLM_KEY = os.environ.get("LLM_ROUTER_API_KEY", "")
LLM_BASE = os.environ.get("LLM_ROUTER_BASE_URL", "https://llm-router.org/v1").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "gpt-6-luna")
GENERATION_TIMEOUT_SECONDS = float(os.environ.get("GENERATION_TIMEOUT_SECONDS", "180"))
GENERATION_ATTEMPTS = max(1, int(os.environ.get("GENERATION_ATTEMPTS", "2")))
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "https://saytli-ai.ru").rstrip("/")
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
SITES_DIR = DATA_DIR / "sites"
DB_FILE = DATA_DIR / "sites.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SITES_DIR.mkdir(parents=True, exist_ok=True)
_db_lock = threading.Lock()
DB_LOCK_FILE = DATA_DIR / "sites.json.lock"
_active_tasks: dict[int, asyncio.Task] = {}


def _remember_task(user_id: int, task: asyncio.Task) -> None:
    """Keep long-running bot work cancellable from the inline cancel button."""
    _active_tasks[user_id] = task

    def clear_task(done: asyncio.Task) -> None:
        if _active_tasks.get(user_id) is done:
            _active_tasks.pop(user_id, None)
        if done.cancelled():
            return
        try:
            done.exception()
        except Exception:
            logger.exception("background bot task failed")

    task.add_done_callback(clear_task)


def _start_background_task(user_id: int, coroutine) -> asyncio.Task:
    previous = _active_tasks.get(user_id)
    if previous and not previous.done():
        previous.cancel()
    task = asyncio.create_task(coroutine)
    _remember_task(user_id, task)
    return task


async def _cancel_background_task(user_id: int) -> None:
    task = _active_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()


@contextmanager
def _database_lock():
    """Lock the shared JSON database across the bot and web processes."""
    DB_LOCK_FILE.touch(exist_ok=True)
    with _db_lock:
        handle = DB_LOCK_FILE.open("r+b")
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def load_db() -> dict:
    with _database_lock():
        if not DB_FILE.exists():
            return {"sites": {}}
        try:
            data = json.loads(DB_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) and isinstance(data.get("sites", {}), dict) else {"sites": {}}
        except (json.JSONDecodeError, OSError):
            return {"sites": {}}


def save_db(db: dict) -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _database_lock():
        tmp = DB_FILE.with_name(f".{DB_FILE.name}.{os.getpid()}.tmp")
        payload = json.dumps(db, ensure_ascii=False, indent=2)
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(DB_FILE)


def update_db(mutator):
    """Read, mutate and atomically save the database under one process lock."""
    with _database_lock():
        if DB_FILE.exists():
            try:
                db = json.loads(DB_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                db = {"sites": {}}
        else:
            db = {"sites": {}}
        if not isinstance(db, dict) or not isinstance(db.get("sites", {}), dict):
            db = {"sites": {}}
        result = mutator(db)
        tmp = DB_FILE.with_name(f".{DB_FILE.name}.{os.getpid()}.tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(db, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(DB_FILE)
        return result


def safe_site_path(raw_path: str | None, site_id: str) -> Path | None:
    """Resolve an active artifact and keep it inside the publication root."""
    root = SITES_DIR.resolve()
    candidates = []
    if raw_path:
        candidates.append(Path(raw_path))
    candidates.append(SITES_DIR / site_id)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                continue
            target = resolved if resolved.is_file() else resolved / "index.html"
            if target.is_relative_to(root) and target.is_file():
                return target
        except (OSError, RuntimeError, ValueError):
            continue
    return None


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ _-]", "", value).strip().lower()
    value = re.sub(r"[ _]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:48] or secrets.token_hex(5)


def site_key(site_id: str) -> str:
    """Stable short callback key; Telegram callback_data is max 64 bytes."""
    return hashlib.sha256(site_id.encode("utf-8")).hexdigest()[:16]


def site_keyboard(site_id: str) -> InlineKeyboardMarkup:
    key = site_key(site_id)
    url = f"{PUBLIC_BASE}/s/{site_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 Открыть в Telegram", web_app=WebAppInfo(url=url)),
            InlineKeyboardButton(text="🌐 В браузере", url=url),
        ],
        [
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit:{key}"),
            InlineKeyboardButton(text="↩️ Откат версии", callback_data=f"rollback:{key}"),
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить сайт", callback_data=f"delete:{key}"),
            InlineKeyboardButton(text="📁 Все сайты", callback_data="list"),
        ],
    ])


def edit_keyboard(site_id: str) -> InlineKeyboardMarkup:
    key = site_key(site_id)
    url = f"{PUBLIC_BASE}/s/{site_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Изменить через ИИ", callback_data=f"ai_edit:{key}")],
        [
            InlineKeyboardButton(text="📱 Просмотр", web_app=WebAppInfo(url=url)),
            InlineKeyboardButton(text="↩️ Вернуть предыдущую версию", callback_data=f"rollback:{key}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад к карточке", callback_data=f"view:{key}"),
            InlineKeyboardButton(text="📁 Мои сайты", callback_data="list"),
        ],
    ])


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Создать сайт", callback_data="create")],
        [
            InlineKeyboardButton(text="📁 Мои сайты", callback_data="list"),
            InlineKeyboardButton(text="💬 Помощь AI", callback_data="chat"),
        ],
        [InlineKeyboardButton(text="ℹ️ Как это работает", callback_data="help")],
    ])


def presets_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Личное портфолио", callback_data="preset:portfolio"),
            InlineKeyboardButton(text="🛠 Услуги специалиста", callback_data="preset:services"),
        ],
        [
            InlineKeyboardButton(text="🚀 Собственный проект", callback_data="preset:project"),
            InlineKeyboardButton(text="📚 Кейсы и работы", callback_data="preset:case-study"),
        ],
        [
            InlineKeyboardButton(text="✍️ Свой вариант", callback_data="preset:custom"),
        ],
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"),
        ]
    ])


def input_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_action")],
    ])


def chat_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Создать сайт", callback_data="create")],
        [InlineKeyboardButton(text="📁 Мои сайты", callback_data="list")],
        [InlineKeyboardButton(text="❌ Выйти из чата", callback_data="cancel_action")],
    ])


def generation_error_text(exc: Exception) -> str:
    """Turn common generation failures into useful, non-technical guidance."""
    if isinstance(exc, httpx.TimeoutException):
        return "AI долго не отвечает. Ваш сайт не изменён — попробуйте ещё раз чуть позже."
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return "Сервис генерации временно недоступен. Мы уже получили технический сигнал; попробуйте позже."
        if status == 429:
            return "Сейчас много запросов. Подождите минуту и запустите генерацию ещё раз."
        if status >= 500:
            return "AI-сервис временно перегружен. Попробуйте ещё раз через пару минут."
    if isinstance(exc, (httpx.ConnectError, httpx.RemoteProtocolError)):
        return "Не удалось связаться с AI-сервисом. Проверьте попытку чуть позже."
    if "quality" in str(exc).casefold() or "html" in str(exc).casefold():
        return "AI не собрал страницу, прошедшую проверку. Попробуйте описать сайт проще: кто вы, что показать и как связаться."
    if "responsive" in str(exc).casefold() or "mobile" in str(exc).casefold():
        return "AI собрал страницу без надёжной мобильной адаптации. Повторите попытку — мы автоматически проверяем ширину телефона перед публикацией."
    return "Не получилось завершить генерацию. Ваши данные сохранены — попробуйте ещё раз или обратитесь в поддержку."


PRESET_BRIEFS = {
    "portfolio": "Современное личное портфолио специалиста. Покажи кто я, чем занимаюсь, мои ключевые навыки, избранные проекты, процесс работы и способы связи. Используй только факты, которые я укажу, без выдуманных отзывов и цифр.",
    "services": "Понятная страница услуг специалиста. Покажи кому я помогаю, какие задачи решаю, список услуг, этапы работы, примеры работ и простой способ связаться со мной. Не добавляй цены или гарантии, если я их не указал.",
    "project": "Сайт собственного цифрового проекта или сервиса. Объясни проблему, решение, ключевые возможности, сценарий использования, ограничения и способ связи или знакомства с проектом. Не выдумывай пользователей, метрики и интеграции.",
    "case-study": "Витрина клиентских кейсов и выполненных работ. Для каждого кейса покажи задачу, ход работы и результат только на основе информации пользователя. Не выдумывай клиентов, цифры, логотипы и отзывы.",
}


class CreateSite(StatesGroup):
    brief = State()
    edit_brief = State()
    chat = State()


router = Router()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await _cancel_background_task(message.from_user.id)
    await state.clear()
    welcome_text = (
        "🚀 <b>Добро пожаловать в Saytli AI!</b>\n\n"
        "Создам и опубликую адаптивный сайт по вашему описанию. Не нужно знать код — просто расскажите, что показать.\n\n"
        "• <b>✨ Создать сайт</b> — выберите пример или опишите идею своими словами\n"
        "• <b>📁 Мои сайты</b> — просмотр, редактирование и откат версий\n"
        "• <b>💬 AI-консультант</b> — помощь со структурой и текстами\n"
        "• <b>📱 Mini App</b> — открывайте сайты прямо внутри Telegram!"
    )
    await message.answer(welcome_text, reply_markup=main_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _cancel_background_task(callback.from_user.id)
    await state.clear()
    welcome_text = (
        "🏠 <b>Главное меню Saytli AI</b>\n\n"
        "Выберите действие из меню ниже:"
    )
    await callback.message.edit_text(welcome_text, reply_markup=main_keyboard(), parse_mode="HTML")


@router.message(Command("create", "new"))
@router.callback_query(F.data == "create")
async def create_start(event: Message | CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    await _cancel_background_task(user_id)
    if isinstance(event, CallbackQuery):
        await event.answer()
        msg = event.message
    else:
        msg = event

    await state.set_state(CreateSite.brief)
    prompt_text = (
        "✨ <b>Создание нового сайта</b>\n\n"
        "Сначала выберите тип сайта или нажмите «Свой вариант». Затем одним сообщением напишите:\n"
        "1) кто вы или чем занимаетесь; 2) что показать; 3) как с вами связаться.\n\n"
        "<i>Пример: «Я мастер по ремонту велосипедов в Казани. Покажи услуги, адрес и телефон. Стиль — светлый и современный»</i>\n\n"
        "Можно написать обычным текстом, без специальных команд. Отмена: /cancel"
    )
    if isinstance(event, CallbackQuery):
        await msg.edit_text(prompt_text, reply_markup=presets_keyboard(), parse_mode="HTML")
    else:
        await msg.answer(prompt_text, reply_markup=presets_keyboard(), parse_mode="HTML")


@router.callback_query(F.data.startswith("preset:"))
async def preset_chosen(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    preset_key = callback.data.split(":", 1)[1]
    if preset_key == "custom":
        await state.set_state(CreateSite.brief)
        await callback.message.edit_text(
            "✍️ <b>Опишите будущий сайт</b>\n\n"
            "Напишите одним сообщением: кто вы/ваш проект, для кого сайт, какие разделы нужны, контакты и желаемый стиль. Если чего-то пока нет — пропустите. Можно своими словами.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]]),
            parse_mode="HTML",
        )
        return
    brief = PRESET_BRIEFS.get(preset_key)
    if not brief:
        await callback.answer("Не нашёл этот вариант", show_alert=True)
        await callback.message.answer("Шаблон не найден. Опишите сайт своими словами.")
        return

    await state.clear()
    try:
        status = await callback.message.edit_text(
            "⏳ <b>Инициализация генерации...</b>\nШаблон выбран, запускаю разработку.",
            reply_markup=input_cancel_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        status = await callback.message.answer(
            "⏳ <b>Инициализация генерации...</b>\nШаблон выбран, запускаю разработку.",
            parse_mode="HTML"
        )
    _start_background_task(callback.from_user.id, generate_site(callback.message, status, brief))


@router.message(Command("cancel"))
@router.callback_query(F.data == "cancel_action")
async def cancel(event: Message | CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    await _cancel_background_task(user_id)
    if isinstance(event, CallbackQuery):
        await event.answer("Действие отменено")
        msg = event.message
    else:
        msg = event

    await state.clear()
    text = "🛑 <b>Текущее действие остановлено.</b>\nВы вернулись в главное меню."
    if isinstance(event, CallbackQuery):
        await msg.edit_text(text, reply_markup=main_keyboard(), parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")


@router.message(Command("chat"))
@router.callback_query(F.data == "chat")
async def chat_start(event: Message | CallbackQuery, state: FSMContext):
    await _cancel_background_task(event.from_user.id)
    if isinstance(event, CallbackQuery):
        await event.answer()
        msg = event.message
    else:
        msg = event

    await state.set_state(CreateSite.chat)
    await state.update_data(chat_site_id=None)
    text = (
        "💬 <b>AI-консультант Saytli</b>\n\n"
        "Напишите вопрос или задачу — помогу с текстом, структурой, стилем и правками сайта.\n\n"
        "<i>Примеры: «Какие блоки нужны фотографу?» или «Как лучше показать мои услуги?»</i>\n\n"
        "Для выхода нажмите кнопку ниже или отправьте /cancel."
    )
    if isinstance(event, CallbackQuery):
        await msg.edit_text(text, reply_markup=chat_keyboard(), parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=chat_keyboard(), parse_mode="HTML")


@router.message(Command("help"))
@router.callback_query(F.data == "help")
async def help_command(event: Message | CallbackQuery):
    await _cancel_background_task(event.from_user.id)
    if isinstance(event, CallbackQuery):
        await event.answer()
        msg = event.message
    else:
        msg = event

    text = (
        "ℹ️ <b>Возможности и команды Saytli AI</b>\n\n"
        "<b>Как создать сайт:</b>\n"
        "1. Нажмите «Создать сайт».\n"
        "2. Выберите направление или «Свой вариант».\n"
        "3. Напишите, кто вы, что показать, контакты и желаемый стиль.\n"
        "4. Подождите результат — ссылка появится в этом чате.\n\n"
        "<b>Команды:</b> /create — создать · /sites — мои сайты · /chat — спросить AI · /cancel — отмена\n\n"
        "<b>Ключевые фичи:</b>\n"
        "✓ <b>Telegram Mini Apps</b> — мгновенный просмотр сайта прямо в боте.\n"
        "✓ <b>Умные правки через ИИ</b> — доработка конкретных блоков естественным языком.\n"
        "✓ <b>Мгновенный откат</b> — верните предыдущую версию, если правка не подошла.\n"
        "✓ <b>Понятные направления</b> — портфолио, услуги, проект и кейсы.\n"
        "✓ <b>Дизайн-системы</b> — профессиональная адаптивная верстка без шаблонного вида."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Создать сайт", callback_data="create")],
        [InlineKeyboardButton(text="📁 Мои сайты", callback_data="list")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
    ])
    if isinstance(event, CallbackQuery):
        await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("support"))
async def support_command(message: Message):
    text = (
        "💬 <b>Поддержка Saytli AI</b>\n\n"
        "Если у вас есть идеи, вопросы или отзывы по работе сервиса:\n"
        "• Обратная связь: @vechniy7\n"
        "• Платформа: saytli-ai.ru\n\n"
        "Мы регулярно улучшаем алгоритмы генерации и безопасность!"
    )
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")


async def ask_ai(message: Message, user_text: str, site_context: str = ""):
    prompt = (
        "Ты AI-продуктовый дизайнер Saytli AI. Отвечай по-русски, практично и кратко. "
        "Помогай пользователю создавать сайты. Не утверждай, что статический HTML имеет "
        "настоящую серверную авторизацию или платежи. Если пользователь просит изменить сайт, "
        "предложи конкретный план. "
        f"Контекст сайта: {site_context}\nСообщение пользователя: {user_text}"
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
        response = await client.post(
            f"{LLM_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_KEY}"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": "Ты полезный AI-консультант Saytli AI."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5,
                "max_tokens": 1800
            }
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()


@router.message(CreateSite.chat)
async def chat_message(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        return
    data = await state.get_data()
    site_id = data.get("chat_site_id")
    context = ""
    if site_id:
        site = load_db().get("sites", {}).get(site_id, {})
        context = f"site_id={site_id}; brief={site.get('brief','')}; version={site.get('version',1)}"
    try:
        answer = await ask_ai(message, text, context)
        await message.answer(f"🤖 <b>Saytli AI</b>\n\n{html.escape(answer)}", parse_mode="HTML", reply_markup=chat_keyboard())
    except Exception:
        logger.exception("AI consultant request failed")
        await message.answer("Не удалось получить ответ сейчас. Ваш вопрос не потерян — отправьте его ещё раз через минуту или вернитесь в главное меню.", reply_markup=chat_keyboard())


@router.message(CreateSite.brief)
async def receive_brief(message: Message, state: FSMContext):
    brief = (message.text or "").strip()
    if not brief:
        await message.answer("Отправьте описание сайта текстом. Например: «Я фотограф в Казани, покажи портфолио, услуги и контакты».")
        return
    if len(brief) < 10:
        await message.answer("Опишите идею чуть подробнее (минимум 10 символов).")
        return
    if len(brief) > 5000:
        await message.answer("Описание слишком длинное. Укажите его в пределах 5000 символов.")
        return
    await state.clear()
    try:
        status = await message.answer(
            "⚡ <b>Запуск генерации сайта</b>\n\nПодключаюсь к дизайн-системе...",
            reply_markup=input_cancel_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        logger.warning("could not send generation status")
        return
    _start_background_task(message.from_user.id, generate_site(message, status, brief))


def render_progress_bar(current: int, total: int = 5) -> str:
    pct = int((current / total) * 100)
    pct = min(100, max(0, pct))
    filled = int(pct / 10)
    empty = 10 - filled
    bar = "▰" * filled + "▱" * empty
    return f"<code>[{bar}] {pct}%</code>"


async def progress(status: Message, stages: list[str], current: int):
    bar_str = render_progress_bar(min(current, len(stages)), len(stages))
    lines = []
    for i, stage in enumerate(stages):
        if i < current:
            lines.append(f"✓ <i>{stage}</i>")
        elif i == current:
            lines.append(f"🔄 <b>{stage}...</b>")
        else:
            lines.append(f"○ {stage}")

    text = (
        f"⚡ <b>Разработка вашего сайта</b>\n"
        f"{bar_str}\n\n"
        + "\n".join(lines)
    )
    try:
        await status.edit_text(text, parse_mode="HTML", reply_markup=input_cancel_keyboard())
    except Exception:
        logger.debug("could not update generation progress", exc_info=True)


async def generate_site(message: Message, status: Message, brief: str):
    stages = [
        "Анализ задачи и подбор структуры",
        "Выбор дизайн-системы и палитры",
        "Генерация адаптивного кода и контента",
        "Проверка верстки, скриптов и безопасности",
        "Публикация и запуск страницы",
    ]
    try:
        await progress(status, stages, 0)
        site_name = site_title(brief)
        skill_names, prompt = build_skill_prompt(brief)
        design = select_design_system(skill_names)
        await progress(status, stages, 1)
        prompt += (
            f"\n\nART DIRECTION SYSTEM (must follow): {json.dumps(design, ensure_ascii=False)}\n"
            f"НАЗВАНИЕ САЙТА: используй название «{site_name}» как основной бренд в title, hero и навигации. Не заменяй его случайной фразой из брифа и не добавляй слово 'сайт' к названию бренда без необходимости.\n"
            "Выбери визуальную систему осознанно и не смешивай её с generic SaaS шаблонами.\n\n"
            "ПУБЛИКАЦИЯ: не добавляй поверх сайта баннеры или надписи 'ДЕМО-РЕЖИМ', 'Demo mode', 'Local demo mode', 'no real payment'. "
            "Интерфейс должен выглядеть как законченный продукт. Не выдумывай факт реального backend: "
            "интерактивные функции реализуй в рамках frontend, а неподключённые операции оформляй нейтральными рабочими формами."
        )
        logger.info("site generation skills=%s design=%s", ",".join(skill_names), design['id'])
        if not LLM_KEY:
            raise RuntimeError("LLM_ROUTER_API_KEY is not configured")

        request_payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Ты профессиональный frontend-разработчик. Верни только HTML."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 12000
        }
        content = None
        last_error = None
        await progress(status, stages, 2)
        validation_errors = []
        for attempt in range(GENERATION_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(GENERATION_TIMEOUT_SECONDS, connect=20.0)) as client:
                    response = await client.post(
                        f"{LLM_BASE}/chat/completions",
                        headers={"Authorization": f"Bearer {LLM_KEY}"},
                        json=request_payload
                    )
                    response.raise_for_status()
                    last_error = None
                    validation = validate_candidate(response.json()["choices"][0]["message"].get("content"))
                    candidate = validation["candidate"]
                    validation_errors = validation["errors"]
                    logger.info(
                        "generation attempt=%s accepted=%s validation_errors=%s responsive=%s",
                        attempt + 1,
                        validation["accepted"],
                        ",".join(validation_errors) or "none",
                        ",".join(validation.get("responsive", {}).get("errors", [])) or "ok",
                    )
                    if validation["accepted"]:
                        content = candidate
                        safety_report = validation["safety"]
                        report = validation["quality"]
                        frontend_report = validation["frontend"]
                        browser_report = validation["browser"]
                        break
                    if attempt < GENERATION_ATTEMPTS - 1:
                        request_payload["messages"][1]["content"] = (
                            prompt + "\n\nПредыдущий вариант не прошёл проверки: " + ", ".join(validation_errors)
                            + ". Исправь конкретно эти причины и верни полный HTML-документ. Особенно проверь ширину 320px: grid/flex должны перестраиваться, изображения не должны выходить за экран, меню и кнопки должны быть доступны пальцем. Не используй iframe/object/embed, внешние script-теги или сетевые запросы из JavaScript."
                        )
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt < GENERATION_ATTEMPTS - 1:
                    request_payload["messages"][1]["content"] = (
                        prompt + "\n\nСделай реализацию как цельный single-page HTML-портфолио с рабочей навигацией и frontend-интерактивностью; не описывай backend-код."
                    )
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in (429, 500, 502, 503, 504) or attempt == GENERATION_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(1.5 * (attempt + 1))
            except (ValueError, KeyError, TypeError) as exc:
                last_error = exc
                if attempt < GENERATION_ATTEMPTS - 1:
                    request_payload["messages"][1]["content"] = prompt + "\n\nПредыдущий ответ оказался некорректным. Верни только полный самодостаточный HTML-документ."
        if content is None and last_error:
            raise last_error or RuntimeError("LLM did not return content")
        if content is None:
            raise RuntimeError("Generated content failed validation: " + ", ".join(validation_errors))

        content = set_document_title(content, site_name)
        await progress(status, stages, 3)

        logger.info(
            "site quality score=%s frontend_score=%s browser=%s",
            report["score"], frontend_report["score"], browser_report["passed"]
        )
        await progress(status, stages, 4)
        db = load_db()
        site_id = unique_site_slug(brief, db.get("sites", {}).keys())
        folder = SITES_DIR / site_id
        while folder.exists():
            site_id = unique_site_slug(brief, [*db.get("sites", {}).keys(), site_id])
            folder = SITES_DIR / site_id
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "index.html").write_text(content, encoding="utf-8")

        site_record = {
            "owner": message.from_user.id,
            "title": site_name,
            "brief": brief,
            "skills": skill_names,
            "design_system": design["id"],
            "version": 1,
            "versions": [{"version": 1, "path": str(folder), "summary": "Исходная генерация"}],
            "quality": {"static": frontend_report, "browser": browser_report},
            "created": __import__("datetime").datetime.utcnow().isoformat(),
            "path": str(folder),
        }
        update_db(lambda db: db["sites"].__setitem__(site_id, site_record))

        url = f"{PUBLIC_BASE}/s/{site_id}"
        result_text = (
            f"🎉 <b>{html.escape(site_name)} — сайт опубликован!</b>\n\n"
            f"🌐 <b>Адрес:</b> {url}\n"
            f"🎨 <b>Дизайн:</b> <code>{design['id']}</code>\n"
            f"✨ <b>Стиль:</b> <code>{' · '.join(skill_names)}</code>\n\n"
            f"<i>Вы можете открыть сайт прямо в Telegram или внести правки через ИИ:</i>"
        )
        try:
            await status.edit_text(result_text, parse_mode="HTML", reply_markup=site_keyboard(site_id))
        except Exception:
            await message.answer(result_text, parse_mode="HTML", reply_markup=site_keyboard(site_id))
    except asyncio.CancelledError:
        logger.info("site generation cancelled")
        return
    except Exception as exc:
        logger.exception("site generation failed: %s", type(exc).__name__)
        try:
            await status.edit_text(
                f"⚠️ <b>Не удалось создать сайт</b>\n\n{html.escape(generation_error_text(exc))}\n\nМожете изменить описание и попробовать снова.",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )
        except Exception:
            logger.warning("could not show generation failure status", exc_info=True)


@router.message(Command("sites", "list", "panel"))
@router.callback_query(F.data == "list")
async def list_sites(event: Message | CallbackQuery):
    await _cancel_background_task(event.from_user.id)
    is_callback = isinstance(event, CallbackQuery)
    if is_callback:
        await event.answer()
        user_id = event.from_user.id
        msg = event.message
    else:
        user_id = event.from_user.id
        msg = event

    db = load_db()
    owned = [(sid, item) for sid, item in db.get("sites", {}).items() if item.get("owner") == user_id]
    if not owned:
        text = (
            "📁 <b>Ваши сайты</b>\n\n"
            "У вас пока нет созданных сайтов.\n"
            "Нажмите кнопку ниже, чтобы запустить генерацию первого проекта!"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✨ Создать сайт", callback_data="create")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
        ])
        if is_callback:
            await msg.edit_text(text, parse_mode="HTML", reply_markup=kb)
        else:
            await msg.answer(text, parse_mode="HTML", reply_markup=kb)
        return

    owned.sort(key=lambda pair: pair[1].get("created", ""), reverse=True)

    site_lines = []
    buttons = []
    for idx, (sid, item) in enumerate(owned[:8], 1):
        v = item.get("version", 1)
        brief_short = html.escape((item.get("brief", "") or sid)[:36])
        title = html.escape(item.get("title") or site_title(item.get("brief", "")) or sid)
        site_lines.append(f"<b>{idx}.</b> <b>{title}</b> [v{v}]\n   <i>{brief_short}...</i>")
        k = site_key(sid)
        buttons.append([
            InlineKeyboardButton(text=f"🌐 {idx}. {(item.get('title') or site_title(item.get('brief', '')) or sid)[:28]}", callback_data=f"view:{k}")
        ])

    buttons.append([
        InlineKeyboardButton(text="✨ Создать сайт", callback_data="create"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"),
    ])

    text = (
        f"📁 <b>Ваши опубликованные сайты ({len(owned)}):</b>\n\n"
        + "\n\n".join(site_lines)
        + "\n\n<i>Выберите сайт из списка для управления и предпросмотра:</i>"
    )

    if is_callback:
        await msg.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await msg.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("view:"))
async def view_site_card(callback: CallbackQuery):
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    db = load_db()
    site_id = next((sid for sid in db.get("sites", {}) if site_key(sid) == key), None)
    site = db.get("sites", {}).get(site_id) if site_id else None
    if not site or site.get("owner") != callback.from_user.id:
        await callback.message.answer("Сайт не найден.")
        return

    v = site.get("version", 1)
    skills = " · ".join(site.get("skills", [])) or "авто"
    brief = html.escape(site.get("brief", "—"))
    url = f"{PUBLIC_BASE}/s/{site_id}"

    text = (
        f"🌐 <b>Сайт:</b> {html.escape(site.get('title') or site_title(site.get('brief', '')) or site_id)}\n"
        f"📊 <b>Версия:</b> v{v}\n"
        f"🎨 <b>Дизайн:</b> <code>{html.escape(site.get('design_system', 'modern'))}</code>\n"
        f"✨ <b>Skills:</b> <code>{html.escape(skills)}</code>\n"
        f"🔗 <b>Ссылка:</b> {url}\n\n"
        f"📝 <b>Исходный бриф:</b>\n<i>{brief[:200]}</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=site_keyboard(site_id))


@router.callback_query(F.data.startswith("edit:"))
async def edit_site_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    db = load_db()
    site_id = next((sid for sid in db.get("sites", {}) if site_key(sid) == key), None)
    site = db.get("sites", {}).get(site_id) if site_id else None
    if not site or site.get("owner") != callback.from_user.id:
        await callback.message.answer("Сайт не найден.")
        return
    await state.update_data(edit_site_id=site_id)
    text = (
        f"✏️ <b>Управление и редактирование сайта</b>\n\n"
        f"Идентификатор: <code>{html.escape(site_id)}</code>\n"
        f"Текущая версия: <b>v{site.get('version', 1)}</b>\n\n"
        f"Выберите следующее действие:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=edit_keyboard(site_id))


@router.callback_query(F.data.startswith("ai_edit:"))
async def ai_edit_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    db = load_db()
    site_id = next((sid for sid in db.get("sites", {}) if site_key(sid) == key), None)
    site = db.get("sites", {}).get(site_id) if site_id else None
    if not site or site.get("owner") != callback.from_user.id:
        await callback.message.answer("Сайт не найден.")
        return
    await state.set_state(CreateSite.edit_brief)
    await state.update_data(edit_site_id=site_id)
    text = (
        "✨ <b>Опишите правки для ИИ-редактора:</b>\n\n"
        "Например:\n"
        "• <i>«Сделай первый экран светлее и спокойнее»</i>\n"
        "• <i>«Добавь ещё один кейс в раздел проектов»</i>\n"
        "• <i>«Сделай блок услуг более понятным и компактным»</i>\n"
        "• <i>«Замени контакты и добавь ссылку на Telegram»</i>\n\n"
        "Опишите одну-две правки за раз. Для отмены нажмите кнопку ниже или отправьте /cancel."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=input_cancel_keyboard())


@router.message(CreateSite.edit_brief)
async def receive_edit_brief(message: Message, state: FSMContext):
    delta = (message.text or "").strip()
    if len(delta) < 5 or len(delta) > 4000:
        await message.answer("Опишите изменение в пределах 5–4000 символов.")
        return
    data = await state.get_data()
    site_id = data.get("edit_site_id")
    db = load_db()
    site = db.get("sites", {}).get(site_id)
    if not site or site.get("owner") != message.from_user.id:
        await state.clear()
        await message.answer("Сайт не найден.", reply_markup=main_keyboard())
        return
    await state.clear()
    try:
        status = await message.answer(
            "⏳ <b>Обновляю сайт...</b>\n\n"
            "1. Анализ изменений\n2. Обновление верстки\n3. Проверка качества\n4. Публикация",
            reply_markup=input_cancel_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        logger.warning("could not send edit status")
        return
    _start_background_task(message.from_user.id, edit_site(message, status, site_id, delta))


async def edit_site(message: Message, status: Message, site_id: str, delta: str):
    try:
        db = load_db()
        site = db["sites"].get(site_id)
        if not site or site.get("owner") != message.from_user.id:
            raise RuntimeError("ownership")
        path = safe_site_path(site.get("path"), site_id)
        if not path:
            raise RuntimeError("site artifact not found")
        current = path.read_text(encoding="utf-8")
        prompt = (
            f"Ты senior frontend developer и технический лид Saytli AI. Обнови существующий HTML-портфолио по задаче пользователя. "
            f"Сохрани все рабочие функции, контент и ссылки, добавь изменение цельно, не удаляй рабочие разделы. "
            f"Не добавляй магазины, корзины, оплату, авторизацию, каталог товаров или выдуманные факты. "
            f"Удали любые служебные баннеры и подписи о режиме работы из видимого интерфейса. Верни только полный HTML.\n\n"
            f"МОБИЛЬНАЯ АДАПТАЦИЯ ОБЯЗАТЕЛЬНА: сохрани и улучши mobile-first верстку для ширины 320–390px. Проверь viewport, box-sizing, отсутствие горизонтального overflow, перенос сеток в одну колонку, размеры кнопок от 44px, читаемый текст от 16px и доступное мобильное меню. Не принимай решение только добавлением body padding; в @media (max-width: 700px) реально меняй grid/flex, навигацию и отступы. Не используй основную раскладку на фиксированных ширинах, min-width или абсолютном позиционировании.\n\n"
            f"ПРАВИЛА ДЛЯ КАРТ И КОНТАКТОВ: если пользователь просит карту или маршрут, не используй iframe, object, embed, внешние script-теги, fetch, XMLHttpRequest или WebSocket. "
            f"Сделай аккуратный блок адреса с обычной HTML-кнопкой/ссылкой на https://yandex.ru/maps/ для построения маршрута. "
            f"Если адрес уже есть в текущем HTML — используй его; если адрес не указан, добавь поле ввода адреса и frontend-кнопку, которая открывает ссылку Яндекс.Карт с URL-кодированным адресом. "
            f"Если пользователь просит кнопку Telegram для @tsuloew, используй ровно ссылку https://t.me/tsuloew. "
            f"Все новые функции должны работать без backend и без сетевых запросов из JavaScript.\n\n"
            f"Текущий HTML:\n{current}\n\nЗадача изменения:\n{delta}"
        )
        request_payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Ты senior frontend developer. Верни только полный самодостаточный HTML-документ без markdown-ограждений."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.55,
            "max_tokens": 18000
        }

        # A map is commonly returned as an iframe, but generated HTML is published
        # with a deliberately strict CSP/safety policy. Give the model one focused
        # repair attempt instead of immediately discarding an otherwise useful edit.
        content = None
        validation_errors = []
        for attempt in range(GENERATION_ATTEMPTS):
            async with httpx.AsyncClient(timeout=httpx.Timeout(GENERATION_TIMEOUT_SECONDS, connect=20.0)) as client:
                response = await client.post(
                    f"{LLM_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {LLM_KEY}"},
                    json=request_payload
                )
                response.raise_for_status()
                candidate = response.json()["choices"][0]["message"].get("content")

            validation = validate_candidate(candidate)
            candidate = validation["candidate"]
            validation_errors = list(validation["errors"])
            logger.info(
                "edit attempt=%s accepted=%s validation_errors=%s responsive=%s",
                attempt + 1,
                validation["accepted"],
                ",".join(validation_errors) or "none",
                ",".join(validation.get("responsive", {}).get("errors", [])) or "ok",
            )
            safety_report = validation.get("safety", {"passed": False})
            report = validation.get("quality", {"score": 0})
            frontend_report = validation.get("frontend", {"score": 0})
            browser_report = validation.get("browser", {"passed": False})
            requested_feature_errors = []
            request_text = delta.casefold()
            if re.search(r"карта|маршрут|яндекс\s*карт|yandex\s*map|maps", request_text) and not re.search(r"yandex\.ru/maps", candidate, re.I):
                requested_feature_errors.append("missing_yandex_route")
            if re.search(r"телеграм|telegram|@tsuloew|t\.me", request_text) and "https://t.me/tsuloew" not in candidate:
                requested_feature_errors.append("missing_telegram_link")
            validation_errors.extend(requested_feature_errors)
            if report["score"] < .75:
                validation_errors.append(f"quality_score={report['score']}")
            if frontend_report["score"] < .75:
                validation_errors.append(f"frontend_score={frontend_report['score']}")
            if not requested_feature_errors and validation["accepted"]:
                content = candidate
                break

            if attempt < GENERATION_ATTEMPTS - 1:
                request_payload["messages"][1]["content"] = (
                    prompt
                    + "\n\nПРЕДЫДУЩИЙ ВАРИАНТ ОТКЛОНЁН ПРОВЕРКОЙ. "
                    + f"Причины: {', '.join(validation_errors)}. "
                    + "Верни полный HTML заново. Не используй iframe/object/embed, внешние script-теги, fetch, XMLHttpRequest, WebSocket или inline on* handlers. "
                    + "Карту реализуй только как ссылку/кнопку на Яндекс.Карты или локальную форму адреса, открывающую маршрут через обычный window.open. "
                    + "Telegram для @tsuloew должен вести на https://t.me/tsuloew."
                )

        if content is None:
            # Contact/map requests have a safe local implementation. This
            # prevents a model choosing a forbidden iframe from turning a
            # valid user request into a failed edit.
            fallback = build_safe_contact_actions_fallback(current, delta)
            if fallback:
                fallback = ensure_initial_render(fallback)
                fallback_safety = publication_safety_report(fallback)
                fallback_report = quality_report(fallback)
                fallback_frontend = static_review(fallback)
                fallback_browser = browser_smoke(fallback)
                if (
                    fallback_safety["passed"]
                    and fallback_report["score"] >= .75
                    and fallback_frontend["score"] >= .75
                    and fallback_browser["passed"]
                    and not needs_fallback(fallback)
                ):
                    content = fallback
            if content is None:
                raise RuntimeError("quality: " + ", ".join(validation_errors))

        version = max((int(item.get("version", 0)) for item in site.get("versions", [])), default=int(site.get("version", 1))) + 1
        version_dir = SITES_DIR / f"{site_id}--v{version}"
        version_dir.mkdir(parents=True, exist_ok=False)
        (version_dir / "index.html").write_text(content, encoding="utf-8")

        history = site.setdefault("versions", [{"version": int(site.get("version", 1)), "path": site.get("path"), "summary": "Исходная версия"}])
        history.append({"version": version, "path": str(version_dir), "summary": delta[:200]})
        site["path"] = str(version_dir)
        site["version"] = version
        site["last_edit"] = delta[:200]
        site["skills"] = site.get("skills", [])
        def save_edit(current_db):
            latest = current_db["sites"].get(site_id)
            if not latest or latest.get("owner") != message.from_user.id:
                raise RuntimeError("ownership changed")
            if int(latest.get("version", 1)) >= version:
                raise RuntimeError("site changed during edit")
            current_db["sites"][site_id] = site
        update_db(save_edit)

        url = f"{PUBLIC_BASE}/s/{site_id}"
        await status.edit_text(
            f"✅ <b>Версия v{version} успешно опубликована!</b>\n\n"
            f"Изменено по задаче: <i>{html.escape(delta[:220])}</i>\n\n"
            f"🌐 <b>Адрес:</b> {url}",
            parse_mode="HTML",
            reply_markup=site_keyboard(site_id)
        )
        await message.answer(
            f"🤖 <b>Отчёт AI-редактора</b>\n\n"
            f"• Версия: <b>v{version}</b>\n"
            f"• Старая версия сохранена (доступен откат в 1 клик)\n"
            f"• Задача: {html.escape(delta[:300])}",
            parse_mode="HTML",
            reply_markup=site_keyboard(site_id)
        )
    except asyncio.CancelledError:
        logger.info("site edit cancelled")
        return
    except Exception as exc:
        logger.exception("site edit failed: %s", type(exc).__name__)
        try:
            await status.edit_text(
                "⚠️ <b>Правка не применена</b>\n\n"
                "Текущая версия сайта не затронута. Попробуйте описать одно изменение за раз — например: «добавь кнопку Telegram в блок контактов».",
                parse_mode="HTML",
                reply_markup=edit_keyboard(site_id),
            )
        except Exception:
            logger.warning("could not show edit failure status", exc_info=True)


@router.callback_query(F.data.startswith("rollback:"))
async def rollback_site(callback: CallbackQuery):
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    db = load_db()
    site_id = next((sid for sid in db.get("sites", {}) if site_key(sid) == key), None)
    site = db.get("sites", {}).get(site_id) if site_id else None
    if not site or site.get("owner") != callback.from_user.id:
        await callback.message.answer("Сайт не найден.")
        return

    versions = site.get("versions", [])
    if len(versions) <= 1:
        await callback.answer("У этого сайта пока только одна версия. Откат не требуется.", show_alert=True)
        return

    current_version = int(site.get("version", 1))
    current_index = next((index for index, item in enumerate(versions) if int(item.get("version", 0)) == current_version), len(versions) - 1)
    if current_index <= 0:
        await callback.answer("Сайт уже находится на самой ранней версии.", show_alert=True)
        return
    current_ver = versions[current_index]
    prev_ver = versions[current_index - 1]

    # Switch active path to previous version
    site["path"] = prev_ver["path"]
    site["version"] = prev_ver["version"]
    site["last_edit"] = f"Откат с v{current_ver.get('version')} к v{prev_ver.get('version')}"
    def save_rollback(current_db):
        latest = current_db["sites"].get(site_id)
        if not latest or latest.get("owner") != callback.from_user.id:
            raise RuntimeError("ownership changed")
        if int(latest.get("version", 1)) != current_version:
            raise RuntimeError("site changed during rollback")
        current_db["sites"][site_id] = site
    try:
        update_db(save_rollback)
    except RuntimeError:
        await callback.message.answer("Сайт изменился параллельно. Откройте его карточку и повторите действие.")
        return

    url = f"{PUBLIC_BASE}/s/{site_id}"
    await callback.message.edit_text(
        f"↩️ <b>Сайт возвращен к версии v{prev_ver['version']}</b>\n\n"
        f"🌐 <b>Адрес:</b> {url}\n"
        f"📝 <b>Версия:</b> {html.escape(prev_ver.get('summary', 'Предыдущая стабильная'))}",
        parse_mode="HTML",
        reply_markup=site_keyboard(site_id)
    )


@router.callback_query(F.data.startswith("delete:"))
async def delete_site_confirm(callback: CallbackQuery):
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    db = load_db()
    site_id = next((sid for sid in db.get("sites", {}) if site_key(sid) == key), None)
    site = db.get("sites", {}).get(site_id) if site_id else None
    if not site or site.get("owner") != callback.from_user.id:
        await callback.message.answer("Сайт не найден.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔴 Да, удалить навсегда", callback_data=f"confirm_del:{key}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"view:{key}"),
        ]
    ])
    text = (
        f"⚠️ <b>Подтверждение удаления</b>\n\n"
        f"Вы действительно хотите удалить сайт <code>{html.escape(site_id)}</code>?\n"
        f"Все файлы страницы и история версий будут стёрты без возможности восстановления."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("confirm_del:"))
async def delete_site_confirmed(callback: CallbackQuery):
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    db = load_db()
    site_id = next((sid for sid in db.get("sites", {}) if site_key(sid) == key), None)
    site = db.get("sites", {}).get(site_id) if site_id else None
    if not site or site.get("owner") != callback.from_user.id:
        await callback.message.answer("Сайт не найден.")
        return

    # Delete only recorded version directories, never arbitrary matching paths.
    recorded_paths = {item.get("path") for item in site.get("versions", []) if item.get("path")}
    recorded_paths.add(site.get("path"))
    for raw_path in recorded_paths:
        try:
            folder = Path(raw_path).resolve()
            if folder.is_dir() and folder.is_relative_to(SITES_DIR.resolve()):
                for child in folder.iterdir():
                    if child.is_file() or child.is_symlink():
                        child.unlink(missing_ok=True)
                folder.rmdir()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("error removing site folder: %s", type(exc).__name__)

    def remove_site(current_db):
        latest = current_db["sites"].get(site_id)
        if not latest or latest.get("owner") != callback.from_user.id:
            raise RuntimeError("ownership changed")
        current_db["sites"].pop(site_id, None)
    try:
        update_db(remove_site)
    except RuntimeError:
        await callback.message.answer("Сайт уже изменился или был удалён. Обновите список сайтов.")
        return
    await callback.message.edit_text("🗑 <b>Сайт и все его версии успешно удалены.</b>", parse_mode="HTML", reply_markup=main_keyboard())


app = FastAPI(title="Saytli AI")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/preview/{site_id}", response_class=HTMLResponse)
def preview_site(site_id: str):
    if not re.fullmatch(r"[\w-]{1,128}", site_id, re.UNICODE):
        raise HTTPException(status_code=404)
    db = load_db()
    site = db.get("sites", {}).get(site_id)
    if not site:
        raise HTTPException(status_code=404)
    target_file = safe_site_path(site.get("path"), site_id)
    if not target_file:
        raise HTTPException(status_code=404)
    return FileResponse(
        target_file,
        media_type="text/html",
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self' https: data: 'unsafe-inline'; script-src 'self' https: 'unsafe-inline'; object-src 'none'; frame-ancestors *",
            "X-Content-Type-Options": "nosniff"
        }
    )


@app.get("/s/{site_id}", response_class=HTMLResponse)
def public_site(site_id: str):
    if not re.fullmatch(r"[\w-]{1,128}", site_id, re.UNICODE):
        raise HTTPException(status_code=404)
    db = load_db()
    site = db.get("sites", {}).get(site_id)
    if not site:
        raise HTTPException(status_code=404)
    # Resolve from active site path, supporting versioned directories
    target_file = safe_site_path(site.get("path"), site_id)
    if not target_file:
        raise HTTPException(status_code=404)
    return FileResponse(
        target_file,
        media_type="text/html",
        headers={
            "Content-Security-Policy": (
                "default-src 'self' https: data: 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline' https:; "
                "script-src 'self' 'unsafe-inline' https:; "
                "img-src 'self' data: https:; "
                "font-src 'self' data: https:; "
                "connect-src 'self' https:; "
                "object-src 'none'; "
                "frame-ancestors *"
            ),
            "X-Content-Type-Options": "nosniff"
        }
    )


async def setup_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="🚀 Главное меню"),
        BotCommand(command="create", description="✨ Создать новый сайт"),
        BotCommand(command="sites", description="📁 Мои сайты"),
        BotCommand(command="chat", description="💬 Чат с AI-консультантом"),
        BotCommand(command="help", description="ℹ️ Помощь и возможности"),
        BotCommand(command="cancel", description="❌ Отменить текущее действие"),
    ]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        logger.info("Bot commands successfully updated in Telegram menu")
    except Exception as exc:
        logger.warning("Failed to register bot commands: %s", exc)


async def bot_main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    proxy_url = os.environ.get("TELEGRAM_PROXY", "").strip()
    api_base = os.environ.get("TELEGRAM_API_BASE", "").strip().rstrip("/")
    session = AiohttpSession(proxy=proxy_url or None)
    if api_base:
        session.api = TelegramAPIServer.from_base(api_base)
    bot = Bot(BOT_TOKEN, session=session)
    dp = Dispatcher()
    dp.include_router(router)

    # Automatically synchronize active commands to remove legacy/dead buttons
    await setup_bot_commands(bot)

    while True:
        try:
            await dp.start_polling(bot)
        except (Exception,) as exc:
            logger.error("polling loop error: %s", type(exc).__name__)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(bot_main())
