# Saytli AI

Telegram-бот для генерации и публикации статических сайтов.

## Быстрый запуск

1. Скопируйте `.env.example` в `.env` и заполните `TELEGRAM_BOT_TOKEN`, `LLM_ROUTER_API_KEY`, `ADMIN_ID`.
2. Запустите `docker compose up -d --build`.
3. Для публичного HTTPS установите Caddy на сервере и направьте `saytli-ai.ru` на VDS:

```bash
sudo caddy reverse-proxy --from saytli-ai.ru --to 127.0.0.1:8080
```

Бот работает через long polling, веб-сервер — на порту 8080. Сайты сохраняются в `data/sites`.

Если прямой доступ к Telegram API на VDS заблокирован, можно бесплатно использовать Cloudflare Worker как HTTPS-реле: загрузите `cloudflare-worker.js` в Cloudflare Workers, получите URL вида `https://имя.workers.dev`, затем укажите в `.env` `TELEGRAM_API_BASE=https://имя.workers.dev` и перезапустите контейнер бота.

## Возможности

- генерация сайта через OpenAI-compatible LLM Router;
- понятные этапы генерации в Telegram;
- публичная ссылка `/s/<site-id>`;
- список сайтов пользователя;
- удаление только собственных сайтов;
- CSP и ограничение генерируемого результата статическим HTML.
