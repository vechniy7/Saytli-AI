"""Manual prompt smoke helper for the production v1 scenarios.

This file intentionally does not publish anything or mutate ``data``.  Use the
Telegram flow for real generation so ownership, versioning and publication
checks are applied consistently.
"""
from skills import build_skill_prompt


BRIEFS = {
    "portfolio": "Личное портфолио специалиста: кто я, специализация, навыки, избранные проекты, процесс работы и контакты.",
    "services": "Страница услуг мастера по ремонту телефонов: кому помогаю, услуги, этапы работы, примеры и способ связи.",
    "project": "Презентация собственного цифрового проекта: проблема, решение, ключевые возможности, сценарий использования и контакты.",
}


for scenario, brief in BRIEFS.items():
    names, prompt = build_skill_prompt(brief)
    print(f"{scenario}: {', '.join(names)}")
    print(f"prompt_chars={len(prompt)}")
