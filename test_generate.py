import os, re, httpx, sys
from pathlib import Path
from skills import build_skill_prompt
from quality import ensure_initial_render, quality_report
brief = sys.argv[1] if len(sys.argv)>1 else 'Создай современное портфолио специалиста по ремонту телефонов: услуги, примеры работ, процесс и контакты в премиальном тёмном стиле.'
names, prompt = build_skill_prompt(brief)
print('SKILLS', names, flush=True)
with httpx.Client(timeout=httpx.Timeout(600, connect=20)) as c:
    r=c.post(os.environ['LLM_ROUTER_BASE_URL'].rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+os.environ['LLM_ROUTER_API_KEY']},json={'model':os.environ.get('LLM_MODEL','gpt-6-luna'),'messages':[{'role':'system','content':'Ты lead product designer и senior frontend engineer. Верни только полный HTML.'},{'role':'user','content':prompt}],'temperature':0.75,'max_tokens':16000})
    print('HTTP',r.status_code, flush=True); r.raise_for_status(); html=r.json()['choices'][0]['message']['content']
html=re.sub(r'^```(?:html)?\s*|\s*```$','',html.strip(),flags=re.I); html=ensure_initial_render(html)
print('QUALITY',quality_report(html), 'BYTES',len(html), flush=True)
out=Path('/app/data/test-quality-site.html'); out.write_text(html,encoding='utf-8'); print('OUT',out,flush=True)
