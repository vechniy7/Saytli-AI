"""Safe static HTML contact actions used as a deterministic edit fallback."""
import re


def build_contact_actions_fallback(current: str, delta: str) -> str | None:
    """Add route and/or Telegram actions without embeds or network JavaScript."""
    request = delta.casefold()
    wants_map = bool(re.search(r"карта|маршрут|яндекс\s*карт|yandex\s*map|maps", request))
    wants_telegram = bool(re.search(r"телеграм|telegram|@tsuloew|t\.me", request))
    if not wants_map and not wants_telegram:
        return None
    if not re.search(r"</body\s*>", current, re.I):
        return None

    parts = []
    if wants_map and 'id="saytli-route-actions"' not in current:
        parts.append(
            """<section id="saytli-route-actions" aria-label="Маршрут" style="margin:2rem 0;padding:1.25rem;border:1px solid rgba(127,127,127,.25);border-radius:1rem">
  <h2>Как нас найти</h2>
  <p>Введите адрес, чтобы построить маршрут от вашего местоположения.</p>
  <div style="display:flex;gap:.75rem;flex-wrap:wrap;align-items:center">
    <label for="saytli-route-address" style="position:absolute;width:1px;height:1px;overflow:hidden">Адрес</label>
    <input id="saytli-route-address" type="text" placeholder="Введите адрес" autocomplete="street-address" style="flex:1 1 16rem;min-height:2.75rem;padding:.65rem .8rem;border:1px solid currentColor;border-radius:.65rem">
    <button id="saytli-route-button" type="button" style="min-height:2.75rem;padding:.65rem 1rem;border:0;border-radius:.65rem;cursor:pointer">Построить маршрут</button>
  </div>
</section>
<script>
(function () {
  var input = document.getElementById("saytli-route-address");
  var button = document.getElementById("saytli-route-button");
  if (!input || !button) return;
  button.addEventListener("click", function () {
    var address = input.value.trim();
    if (!address) { input.focus(); return; }
    window.open("https://yandex.ru/maps/?rtext=~" + encodeURIComponent(address) + "&rtt=auto", "_blank", "noopener");
  });
}());
</script>"""
        )
    if wants_telegram and "https://t.me/tsuloew" not in current:
        parts.append(
            """<a href="https://t.me/tsuloew" target="_blank" rel="noopener noreferrer" aria-label="Связаться в Telegram" style="display:inline-flex;align-items:center;gap:.5rem">Написать в Telegram</a>"""
        )
    if not parts:
        return current

    addition = (
        '\n<div id="saytli-contact-actions" '
        'style="display:flex;gap:1rem;flex-wrap:wrap;align-items:center;margin:1.5rem 0">\n'
        + "\n".join(parts)
        + "\n</div>\n"
    )
    marker = re.search(r"</body\s*>", current, re.I)
    return current[:marker.start()] + addition + current[marker.start():]
