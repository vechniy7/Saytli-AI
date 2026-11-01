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
from pathlib import Path
from typing import Optional

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from dotenv import load_dotenv
from skills import build_skill_prompt
from quality import ensure_initial_render, quality_report, needs_fallback
from pipeline import static_review
from design_systems import select_design_system
from browser_qa import browser_smoke

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("saytli")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
LLM_KEY = os.environ.get("LLM_ROUTER_API_KEY", "")
LLM_BASE = os.environ.get("LLM_ROUTER_BASE_URL", "https://llm-router.org/v1").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "gpt-6-luna")
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "https://saytli-ai.ru").rstrip("/")
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
SITES_DIR = DATA_DIR / "sites"
DB_FILE = DATA_DIR / "sites.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SITES_DIR.mkdir(parents=True, exist_ok=True)
_db_lock = threading.Lock()


def load_db() -> dict:
    with _db_lock:
        if not DB_FILE.exists():
            return {"sites": {}}
        try:
            return json.loads(DB_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"sites": {}}


def save_db(db: dict) -> None:
    tmp = DB_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DB_FILE)


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
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть сайт", url=f"{PUBLIC_BASE}/s/{site_id}")],
        [InlineKeyboardButton(text="👁 Предпросмотр", url=f"{PUBLIC_BASE}/preview/{site_id}")],
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit:{key}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{key}")],
    ])


def edit_keyboard(site_id: str) -> InlineKeyboardMarkup:
    key = site_key(site_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Изменить через ИИ", callback_data=f"ai_edit:{key}")],
        [InlineKeyboardButton(text="👁 Открыть сайт", url=f"{PUBLIC_BASE}/s/{site_id}")],
        [InlineKeyboardButton(text="↩️ Вернуть последнюю версию", callback_data=f"rollback:{key}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="list")],
    ])


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Создать сайт", callback_data="create")],
        [InlineKeyboardButton(text="💬 Поговорить с AI", callback_data="chat")],
        [InlineKeyboardButton(text="📁 Мои сайты", callback_data="list")],
    ])


class CreateSite(StatesGroup):
    brief = State()
    edit_brief = State()
    chat = State()


router = Router()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("<b>Saytli AI</b> — создайте и опубликуйте сайт через ИИ.\n\nОпишите идею, аудиторию и желаемый стиль.", reply_markup=main_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "create")
async def create_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(CreateSite.brief)
    await callback.message.answer("Опишите сайт одним сообщением: чем занимаетесь, какие блоки нужны и какой стиль предпочитаете.\n\nДля отмены: /cancel")


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Текущий режим остановлен. Выберите действие в меню.", reply_markup=main_keyboard())


@router.callback_query(F.data == "chat")
async def chat_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(CreateSite.chat)
    await state.update_data(chat_site_id=None)
    await callback.message.answer("💬 Напишите задачу или вопрос. Я помогу спроектировать сайт, контент, структуру и изменения.\n\n/cancel — выйти")


async def ask_ai(message: Message, user_text: str, site_context: str = ""):
    prompt = f"Ты AI-продуктовый дизайнер Saytli AI. Отвечай по-русски, практично и кратко. Помогай пользователю создавать сайты. Не утверждай, что статический HTML имеет настоящую серверную авторизацию или платежи. Если пользователь просит изменить сайт, предложи конкретный план. Контекст сайта: {site_context}\nСообщение пользователя: {user_text}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
        response = await client.post(f"{LLM_BASE}/chat/completions", headers={"Authorization": f"Bearer {LLM_KEY}"}, json={"model": MODEL, "messages":[{"role":"system","content":"Ты полезный AI-консультант Saytli AI."},{"role":"user","content":prompt}],"temperature":0.5,"max_tokens":1800})
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()


@router.message(CreateSite.chat)
async def chat_message(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text: return
    data = await state.get_data(); site_id = data.get("chat_site_id")
    context = ""
    if site_id:
        site = load_db().get("sites", {}).get(site_id, {})
        context = f"site_id={site_id}; brief={site.get('brief','')}; version={site.get('version',1)}"
    try:
        answer = await ask_ai(message, text, context)
        await message.answer(f"🤖 <b>Saytli AI</b>\n\n{html.escape(answer)}", parse_mode="HTML", reply_markup=main_keyboard())
    except Exception:
        await message.answer("Не удалось получить ответ от AI. Попробуйте ещё раз через несколько секунд.", reply_markup=main_keyboard())


@router.message(CreateSite.brief)
async def receive_brief(message: Message, state: FSMContext):
    brief = (message.text or "").strip()
    if len(brief) < 10:
        await message.answer("Опишите идею чуть подробнее (минимум 10 символов).")
        return
    if len(brief) > 5000:
        await message.answer("Описание слишком длинное. Укажите его в пределах 5000 символов.")
        return
    await state.clear()
    try:
        status = await message.answer("⏳ <b>Генерация сайта</b>\n\n1. Анализ идеи\n2. Создание дизайна\n3. Сборка страницы\n4. Публикация", parse_mode="HTML")
    except Exception:
        logger.warning("could not send generation status")
        return
    asyncio.create_task(generate_site(message, status, brief))


async def progress(status: Message, lines: list[str], current: int):
    text = "⏳ <b>Работаю над сайтом</b>\n\n" + "\n".join(("✅ " if i < current else ("🔄 " if i == current else "○ ")) + line for i, line in enumerate(lines)) + f"\n\n<b>{min(99, int((current / max(1, len(lines))) * 100))}%</b>"
    try: await status.edit_text(text, parse_mode="HTML")
    except Exception: pass


async def generate_site(message: Message, status: Message, brief: str):
    stages = ["Анализирую задачу", "Подбираю дизайн-систему", "Генерирую страницы и контент", "Проверяю HTML и интерактивность", "Публикую сайт"]
    try:
        await progress(status, stages, 0)
        # Keep the public slug and Telegram callback payload safely short (<=64 bytes).
        site_id = slugify(brief[:18])[:18] + "-" + secrets.token_hex(4)
        skill_names, prompt = build_skill_prompt(brief)
        design = select_design_system(skill_names)
        await progress(status, stages, 1)
        prompt += f"\n\nART DIRECTION SYSTEM (must follow): {json.dumps(design, ensure_ascii=False)}\nВыбери визуальную систему осознанно и не смешивай её с generic SaaS шаблонами.\n\nПУБЛИКАЦИЯ: не добавляй поверх сайта баннеры или надписи 'ДЕМО-РЕЖИМ', 'Demo mode', 'Local demo mode', 'no real payment'. Интерфейс должен выглядеть как законченный продукт. Не выдумывай факт реального backend: интерактивные функции реализуй в рамках frontend, а неподключённые операции оформляй нейтральными рабочими формами без вводящих в заблуждение обещаний."
        logger.info("site generation skills=%s design=%s", ",".join(skill_names), design['id'])
        if not LLM_KEY:
            raise RuntimeError("LLM_ROUTER_API_KEY is not configured")
        request_payload = {"model": MODEL, "messages": [{"role": "system", "content": "Ты профессиональный frontend-разработчик. Верни только HTML."}, {"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 12000}
        content = None
        last_error = None
        await progress(status, stages, 2)
        # Long full-stack briefs can exceed a gateway read window; retry once with
        # a compact fallback request while preserving the selected skills.
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=20.0)) as client:
                    response = await client.post(f"{LLM_BASE}/chat/completions", headers={"Authorization": f"Bearer {LLM_KEY}"}, json=request_payload)
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    break
            except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt == 0:
                    request_payload["messages"][1]["content"] = prompt + "\n\nСделай реализацию как цельный демонстрационный single-page HTML с имитацией основных экранов и функций через JS; не описывай backend-код."
        if content is None:
            raise last_error or RuntimeError("LLM did not return content")
        content = re.sub(r"^```(?:html)?\s*|\s*```$", "", content.strip(), flags=re.I)
        # The selected permissive mode publishes the complete model HTML so that
        # animations and interactive UI are preserved. Filesystem and route
        # isolation remain enforced by the publisher; no generated code is executed
        # on the server.
        if not re.search(r"<html[\s>]|<!doctype html", content, re.I):
            raise RuntimeError("Generated content is not HTML")
        content = ensure_initial_render(content)
        await progress(status, stages, 3)
        report = quality_report(content)
        frontend_report = static_review(content)
        browser_report = browser_smoke(content)
        logger.info("site quality score=%s frontend_score=%s browser=%s checks=%s", report["score"], frontend_report["score"], browser_report["passed"], report["checks"])
        # Route heuristics are advisory for model-generated hash routers; only
        # hard blank/HTML/interaction/mobile failures block publication.
        browser_hard = all(browser_report["checks"].get(k, False) for k in ("quality", "not_blank", "has_navigation", "has_interaction", "has_mobile_css"))
        if report["score"] < 0.75 or frontend_report["score"] < 0.75 or not browser_hard or needs_fallback(content):
            raise RuntimeError("Generated site quality score too low or empty")
        await progress(status, stages, 4)
        folder = SITES_DIR / site_id
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "index.html").write_text(content, encoding="utf-8")
        db = load_db()
        db["sites"][site_id] = {"owner": message.from_user.id, "brief": brief, "skills": skill_names, "design_system": design["id"], "quality": {"static": frontend_report, "browser": browser_report}, "created": __import__("datetime").datetime.utcnow().isoformat(), "path": str(folder)}
        save_db(db)
        result_text = f"✅ <b>Сайт опубликован!</b>\n\nСсылка: {PUBLIC_BASE}/s/{site_id}"
        try:
            await status.edit_text(result_text, parse_mode="HTML", reply_markup=site_keyboard(site_id))
        except Exception:
            # Publication already succeeded; never hide a working link behind a Telegram edit error.
            await message.answer(result_text, parse_mode="HTML", reply_markup=site_keyboard(site_id))
    except Exception as exc:
        logger.exception("site generation failed: %s", type(exc).__name__)
        await status.edit_text("Не удалось создать сайт. Попробуйте ещё раз позже.", reply_markup=main_keyboard())


@router.callback_query(F.data == "list")
async def list_sites(callback: CallbackQuery):
    await callback.answer()
    db = load_db()
    owned = [(sid, item) for sid, item in db["sites"].items() if item.get("owner") == callback.from_user.id]
    if not owned:
        await callback.message.answer("📁 У вас пока нет сайтов. Создайте первый — это займёт несколько минут.", reply_markup=main_keyboard())
        return
    owned.sort(key=lambda pair: pair[1].get("created", ""), reverse=True)
    for sid, item in owned:
        skills = " · ".join(item.get("skills", [])) or "без skills"
        await callback.message.answer(f"🌐 <b>{html.escape(sid)}</b>\nSkills: <code>{html.escape(skills)}</code>", parse_mode="HTML", reply_markup=site_keyboard(sid))


@router.callback_query(F.data.startswith("edit:"))
async def edit_site_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    db = load_db()
    site_id = next((sid for sid in db["sites"] if site_key(sid) == key), None)
    site = db["sites"].get(site_id) if site_id else None
    if not site or site.get("owner") != callback.from_user.id:
        await callback.message.answer("Сайт не найден.")
        return
    await state.update_data(edit_site_id=site_id)
    await callback.message.answer(f"✏️ <b>Редактирование сайта</b>\n\n{html.escape(site_id)}\nВыберите действие:", parse_mode="HTML", reply_markup=edit_keyboard(site_id))


@router.callback_query(F.data.startswith("ai_edit:"))
async def ai_edit_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    db = load_db()
    site_id = next((sid for sid in db["sites"] if site_key(sid) == key), None)
    site = db["sites"].get(site_id) if site_id else None
    if not site or site.get("owner") != callback.from_user.id:
        await callback.message.answer("Сайт не найден.")
        return
    await state.set_state(CreateSite.edit_brief)
    await state.update_data(edit_site_id=site_id)
    await callback.message.answer("✨ Опишите, что изменить через ИИ. Например:\n\n• Сделай первый экран светлее\n• Добавь блок тарифов\n• Замени текст кнопки\n• Добавь раздел FAQ\n\n/cancel — отмена")


@router.message(CreateSite.edit_brief)
async def receive_edit_brief(message: Message, state: FSMContext):
    delta = (message.text or "").strip()
    if len(delta) < 5 or len(delta) > 4000:
        await message.answer("Опишите изменение в пределах 5–4000 символов.")
        return
    data = await state.get_data(); site_id = data.get("edit_site_id")
    db = load_db(); site = db.get("sites", {}).get(site_id)
    if not site or site.get("owner") != message.from_user.id:
        await state.clear(); await message.answer("Сайт не найден.", reply_markup=main_keyboard()); return
    await state.clear()
    try:
        status = await message.answer("⏳ <b>Обновляю сайт</b>\n\n1. Анализ изменений\n2. Обновление дизайна\n3. Проверка страницы\n4. Публикация", parse_mode="HTML")
    except Exception:
        logger.warning("could not send edit status")
        return
    asyncio.create_task(edit_site(message, status, site_id, delta))


async def edit_site(message: Message, status: Message, site_id: str, delta: str):
    try:
        db = load_db(); site = db["sites"].get(site_id)
        if not site or site.get("owner") != message.from_user.id: raise RuntimeError("ownership")
        path = Path(site["path"]) / "index.html"
        current = path.read_text(encoding="utf-8")
        production_request = bool(re.search(r"production|продакшен|продакшн|реальн\w*\s+(?:аккаунт|авторизац|бэкенд|backend|база|заказ)|без\s+demo|убери\s+demo|убрать\s+demo", delta, re.I))
        production_note = ("ВАЖНО: пользователь просит production backend. Этот проект публикует только статический HTML и не может честно создать реальный серверный backend из одного файла. НЕ утверждай, что localStorage стал настоящей авторизацией. Сохрани рабочий demo-интерфейс, убери вводящие в заблуждение обещания, добавь в футер/аккаунт заметный статус 'Frontend demo — backend подключается отдельно', и верни в отчёте список production-компонентов, которые ещё нужны." if production_request else "Не меняй demo/production статус без явной просьбы; если это frontend demo, сохрани работающий локальный режим.")
        prompt = f"Ты senior frontend developer и честный technical lead. Обнови существующий HTML по задаче пользователя. Сохрани все рабочие функции, контент и ссылки, добавь изменение цельно, не удаляй рабочие разделы. Удали любые баннеры и подписи 'Demo mode', 'Local demo mode', 'ДЕМО-РЕЖИМ' из видимого интерфейса, если пользователь просит убрать demo. Верни только полный HTML.\n\n{production_note}\n\nТекущий HTML:\n{current}\n\nЗадача изменения:\n{delta}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=20.0)) as client:
            response = await client.post(f"{LLM_BASE}/chat/completions", headers={"Authorization": f"Bearer {LLM_KEY}"}, json={"model": MODEL, "messages":[{"role":"system","content":"Ты senior frontend developer."},{"role":"user","content":prompt}],"temperature":0.65,"max_tokens":18000})
            response.raise_for_status(); content=response.json()["choices"][0]["message"]["content"]
        content=re.sub(r"^```(?:html)?\s*|\s*```$", "", content.strip(), flags=re.I); content=ensure_initial_render(content)
        report=quality_report(content)
        if report["score"] < .75 or needs_fallback(content): raise RuntimeError("quality")
        version = int(site.get("version", 1)) + 1
        version_dir = SITES_DIR / f"{site_id}--v{version}"
        version_dir.mkdir(parents=True, exist_ok=False); (version_dir / "index.html").write_text(content, encoding="utf-8")
        # Preserve old files and atomically switch the active path in metadata.
        history = site.setdefault("versions", [{"version": int(site.get("version", 1)), "path": site.get("path"), "summary": "Исходная версия"}])
        history.append({"version": version, "path": str(version_dir), "summary": delta[:200]})
        site["path"] = str(version_dir); site["version"] = version; site["last_edit"] = delta[:200]; site["skills"] = site.get("skills", [])
        save_db(db)
        mode_note = "\n\n⚠️ Запрос затрагивает production backend: текущий генератор создаёт frontend/demo. Реальные аккаунты, серверная БД, авторизация и заказы требуют отдельного backend-сервиса." if production_request else ""
        await status.edit_text(f"✅ <b>Версия v{version} опубликована</b>\n\nИзменено по задаче: {html.escape(delta[:220])}\n\n{PUBLIC_BASE}/s/{site_id}{mode_note}", parse_mode="HTML", reply_markup=site_keyboard(site_id))
        await message.answer(f"🤖 <b>Отчёт AI-редактора</b>\n\nВерсия: v{version}\nСохранено: предыдущая версия\nЗадача выполнена: {html.escape(delta[:500])}{mode_note}", parse_mode="HTML", reply_markup=site_keyboard(site_id))
    except Exception as exc:
        logger.exception("site edit failed: %s", type(exc).__name__)
        await status.edit_text("Не удалось обновить сайт. Предыдущая версия сохранена.", reply_markup=main_keyboard())
        await message.answer("🤖 AI-редактор не смог безопасно применить изменение. Текущая версия сайта не затронута. Попробуйте сформулировать задачу короче или попросите изменить конкретный блок.", reply_markup=main_keyboard())


@router.callback_query(F.data.startswith("delete:"))
async def delete_site(callback: CallbackQuery):
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    db = load_db()
    site_id = next((sid for sid in db["sites"] if site_key(sid) == key), None)
    site = db["sites"].get(site_id) if site_id else None
    if not site or site.get("owner") != callback.from_user.id:
        await callback.message.answer("Сайт не найден.")
        return
    folder = Path(site.get("path", ""))
    if folder.is_relative_to(SITES_DIR) and folder.exists():
        for child in folder.iterdir():
            child.unlink()
        folder.rmdir()
    del db["sites"][site_id]
    save_db(db)
    await callback.message.edit_text("🗑 Сайт удалён.", reply_markup=main_keyboard())


app = FastAPI(title="Saytli AI")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/preview/{site_id}", response_class=HTMLResponse)
def preview_site(site_id: str):
    if not re.fullmatch(r"[a-z0-9а-яё-]{1,60}", site_id, re.I):
        raise HTTPException(status_code=404)
    db = load_db(); site = db["sites"].get(site_id)
    if not site: raise HTTPException(status_code=404)
    path = Path(site.get("path", "")).resolve()
    if not path.is_relative_to(SITES_DIR.resolve()) or not (path / "index.html").exists():
        raise HTTPException(status_code=404)
    return FileResponse(path / "index.html", media_type="text/html", headers={"Cache-Control":"no-store", "Content-Security-Policy":"default-src 'self' https: data: 'unsafe-inline'; script-src 'self' https: 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'"})


@app.get("/s/{site_id}", response_class=HTMLResponse)
def public_site(site_id: str):
    if not re.fullmatch(r"[a-z0-9а-яё-]{1,60}", site_id, re.I):
        raise HTTPException(status_code=404)
    db = load_db()
    site = db["sites"].get(site_id)
    if not site:
        raise HTTPException(status_code=404)
    path = (SITES_DIR / site_id / "index.html").resolve()
    if not path.is_relative_to(SITES_DIR.resolve()) or not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="text/html", headers={"Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline' https:; script-src 'self' 'unsafe-inline' https:; img-src 'self' data: https:; font-src 'self' data: https:; connect-src 'self' https:; object-src 'none'; frame-ancestors 'none'"})


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
    # Keep the process alive across transient relay outages; aiogram reconnects
    # internally, while this outer loop prevents a single startup timeout from
    # leaving Docker with an apparently running but dead service.
    while True:
        try:
            await dp.start_polling(bot)
        except (Exception,) as exc:
            logger.error("polling loop error: %s", type(exc).__name__)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(bot_main())
