import json, os, re, secrets, httpx
from datetime import datetime, timezone
from pathlib import Path
from skills import build_skill_prompt
from quality import ensure_initial_render, quality_report, needs_fallback

PROMPTS = {
  'restaurant': '''Создай полноценный современный ресторанный веб-сайт уровня premium production demo. Это должен быть цельный визуально насыщенный проект, а не пустой макет: главная с атмосферным hero и CTA, полноценное меню с категориями/поиском/фильтрами, карточки блюд с качественными фотографиями, корзина с количеством и суммой, checkout с доставкой/самовывозом, бронирование стола с датой/временем/гостями, контакты, о ресторане, регистрация, вход, личный кабинет, история заказов, 404 и защищённая демонстрационная админ-панель. Добавь реальные интерактивные состояния на JavaScript, localStorage для demo persistence, seed-меню из 8-10 блюд с названиями/описаниями/ценами, управление блюдами/категориями/заказами/бронями в админке. Пароль admin/admin обозначь только как локальное демо. Сделай премиальный ресторанный арт-дирекшен: бордовый/угольный/кремовый, выразительная типографика, фотографии блюд Unsplash, сетка, hover, focus, mobile menu, toast, модальные окна. Никаких пустых app-контейнеров: initial render обязателен. Поскольку реального backend нет, честно обозначь локальный demo режим.''',
  'fashion': '''Создай полноценный современный fashion e-commerce сайт уровня premium production demo для бренда одежды NOIR ATELIER. Не пустой макет: hero/lookbook с качественными фотографиями одежды, каталог с категориями (new, outerwear, tops, accessories), поиск, сортировка, фильтры, карточки с фото/ценой/размерами/цветами, product detail modal, wishlist, корзина с quantity/суммой, checkout demo, аккаунт/регистрация/вход, история заказов, контакты, 404 и демонстрационная админ-панель для товаров/категорий/заказов. Используй localStorage и seed из 10-12 разных товаров с реалистичными описаниями и ценами, но без ложных отзывов и фактов. Сделай дорогой editorial fashion art direction: молочный/чёрный/кобальтовый акцент, крупная типографика, асимметричная сетка, lookbook imagery через Unsplash, плавные hover/scroll animations, mobile menu, filter drawer, toast, keyboard-friendly controls. Все кнопки должны работать в demo. Никаких пустых app-контейнеров: initial render обязателен. Честно обозначь локальный demo режим.'''
}

def gen(kind, brief):
    names,prompt=build_skill_prompt(brief)
    print(kind,'skills',names,flush=True)
    with httpx.Client(timeout=httpx.Timeout(600,connect=30)) as c:
      r=c.post(os.environ['LLM_ROUTER_BASE_URL'].rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+os.environ['LLM_ROUTER_API_KEY']},json={'model':os.environ.get('LLM_MODEL','gpt-6-luna'),'messages':[{'role':'system','content':'Ты lead product designer и senior frontend engineer. Верни только полный HTML-документ.'},{'role':'user','content':prompt+'\n\n'+brief}],'temperature':0.8,'max_tokens':18000})
      r.raise_for_status(); html=r.json()['choices'][0]['message']['content']
    html=re.sub(r'^```(?:html)?\s*|\s*```$','',html.strip(),flags=re.I); html=ensure_initial_render(html)
    rep=quality_report(html); print(kind,'quality',rep,'bytes',len(html),flush=True)
    if rep['score']<.75 or needs_fallback(html): raise RuntimeError(kind+' failed quality')
    slug=kind+'-showcase-'+secrets.token_hex(4); root=Path('/app/data'); folder=root/'sites'/slug; folder.mkdir(parents=True); (folder/'index.html').write_text(html,encoding='utf-8')
    dbf=root/'sites.json'; db=json.loads(dbf.read_text()) if dbf.exists() else {'sites':{}}
    db['sites'][slug]={'owner':8485394504,'brief':brief,'skills':names,'created':datetime.now(timezone.utc).isoformat(),'path':str(folder)}; dbf.write_text(json.dumps(db,ensure_ascii=False,indent=2))
    return slug,names

out=[]
for k,b in PROMPTS.items(): out.append((k,*gen(k,b)))
print('RESULT',out,flush=True)
relay='https://saytli-telegram-relay.lalaboda06.workers.dev/bot'+os.environ['TELEGRAM_BOT_TOKEN']+'/sendMessage'
text='✅ Тестовые сайты готовы и добавлены в «Мои сайты»:\n\n'+'\n'.join(f'{k}: {os.environ["PUBLIC_BASE_URL"].rstrip("/")}/s/{slug}\nSkills: {", ".join(names)}' for k,slug,names in out)
with httpx.Client(timeout=60) as c: print(c.post(relay,json={'chat_id':8485394504,'text':text,'disable_web_page_preview':False}).text)
