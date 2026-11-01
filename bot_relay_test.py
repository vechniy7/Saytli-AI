import os
import httpx

relay = os.environ.get("TELEGRAM_RELAY_URL", "https://saytli-telegram-relay.lalaboda06.workers.dev")
token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

if not token:
    print("TELEGRAM_BOT_TOKEN environment variable is not set")
else:
    u = f"{relay.rstrip('/')}/bot{token}/getMe"
    print(httpx.get(u, timeout=20).status_code)
