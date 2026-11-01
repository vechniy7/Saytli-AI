import json, os, re, secrets
from datetime import datetime, timezone
from pathlib import Path
import httpx

brief = '''Создай красивый, современный премиальный персональный сайт-портфолио Цулоева Али — Senior-разработчика и IT-предпринимателя. Тёмный минималистичный стиль в духе iOS и Apple: чёрный и графитовый фон, glassmorphism-карточки, матовое стекло, фиолетовые свечения, градиенты, мягкие тени, качественная типографика и плавные CSS-анимации. Первый экран: Цулоев Али, Senior Developer · IT Entrepreneur, текст «Создаю цифровые продукты, автоматизирую процессы и превращаю идеи в работающие сервисы», кнопки связи и проектов. Блоки: обо мне; проекты с акцентом на TsuloVPN; большая карточка TsuloVPN, цена 69 ₽/месяц, преимущества, поддержка подключения при ограничениях мобильного интернета и белых списках без обещаний гарантированного доступа, кнопка https://t.me/TsuloVPN_bot; навыки Backend, Python, Telegram-боты, AI-интеграции, автоматизация, веб-разработка; подход к разработке; контакты Telegram; адаптивность, мобильное меню, scroll reveal на CSS, микроанимации, футер. Не выдумывай отзывы, клиентов, достижения и цифры. Верни только полноценный HTML без markdown, без script, iframe, form и внешних ресурсов.'''
api = os.environ['LLM_ROUTER_BASE_URL'].rstrip('/') + '/chat/completions'
headers = {'Authorization': 'Bearer ' + os.environ['LLM_ROUTER_API_KEY'], 'Content-Type': 'application/json'}
prompt = 'Ты профессиональный frontend-разработчик. ' + brief
with httpx.Client(timeout=httpx.Timeout(300.0, connect=20.0)) as c:
    r = c.post(api, headers=headers, json={'model': os.environ.get('LLM_MODEL','gpt-6-luna'), 'messages':[{'role':'system','content':'Создай один безопасный статический HTML-документ.'},{'role':'user','content':prompt}], 'temperature':0.7, 'max_tokens':12000})
    r.raise_for_status(); html = r.json()['choices'][0]['message']['content']
html = re.sub(r'^```(?:html)?\s*|\s*```$', '', html.strip(), flags=re.I)
if not re.search(r'<!doctype html|<html[\s>]', html, re.I): raise RuntimeError('no html')
# Remove any prohibited model-added active elements before publication.
html = re.sub(r'<script[^>]*>.*?</script\s*>', '', html, flags=re.I|re.S)
html = re.sub(r'<(?:iframe|form)[^>]*>.*?</(?:iframe|form)\s*>', '', html, flags=re.I|re.S)
html = re.sub(r'\s+on[a-z]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', '', html, flags=re.I)
html = re.sub(r'(?i)(href|src)\s*=\s*["\']\s*javascript:[^"\']*["\']', '', html)
html = re.sub(r'(?i)javascript\s*:', '#', html)
html = re.sub(r'(?i)<script[^>]*>.*?</script\s*>', '', html, flags=re.S)
html = re.sub(r'(?i)<(?:iframe|form)[^>]*>.*?</(?:iframe|form)\s*>', '', html, flags=re.S)
html = re.sub(r'(?i)\s+on[a-z]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', '', html)
# Final sanitizer pass is intentionally non-fatal after removing active tags/handlers.
slug = 'tsuloev-ali-portfolio-' + secrets.token_hex(3)
base = Path('/app/data'); folder = base/'sites'/slug; folder.mkdir(parents=True)
(folder/'index.html').write_text(html, encoding='utf-8')
dbfile=base/'sites.json'
db=json.loads(dbfile.read_text(encoding='utf-8')) if dbfile.exists() else {'sites':{}}
db['sites'][slug]={'owner':8485394504,'brief':brief,'created':datetime.now(timezone.utc).isoformat(),'path':str(folder)}
dbfile.write_text(json.dumps(db,ensure_ascii=False,indent=2),encoding='utf-8')
url=os.environ['PUBLIC_BASE_URL'].rstrip('/')+'/s/'+slug
relay='https://saytli-telegram-relay.lalaboda06.workers.dev/bot'+os.environ['TELEGRAM_BOT_TOKEN']+'/sendMessage'
with httpx.Client(timeout=30) as c:
    t=c.post(relay,json={'chat_id':8485394504,'text':f'✅ Сайт опубликован!\n\n{url}','disable_web_page_preview':False}); t.raise_for_status(); print(url, t.text)
