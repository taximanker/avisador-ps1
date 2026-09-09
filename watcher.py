import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


STATE_PATH = Path("state.json")
SEARCH_TERM = "juegos ps1"
SOURCES = {
    "Vinted": "https://www.vinted.es/catalog?search_text=juegos%20ps1&order=newest_first",
    "Wallapop": "https://es.wallapop.com/app/search?keywords=juegos%20ps1&order_by=newest",
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", value.lower()).strip()


def relevant(title: str) -> bool:
    text = normalize(title)
    ps1_terms = ("ps1", "playstation 1", "play station 1", "ps one", "psx")
    game_terms = ("juego", "juegos", "lote", "pack", "coleccion")
    return any(term in text for term in ps1_terms) and any(term in text for term in game_terms)


def title_from_url(url: str) -> str:
    slug = unquote(urlparse(url).path.rstrip("/").split("/")[-1])
    slug = re.sub(r"^\d+-", "", slug)
    slug = re.sub(r"-\d{6,}$", "", slug)
    return slug.replace("-", " ").strip().title() or "Anuncio de PS1"


def scrape_page(page, source: str, url: str) -> list[dict]:
    print(f"Consultando {source}...")
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(4_000)

    selector = 'a[href*="/items/"]' if source == "Vinted" else 'a[href*="/item/"]'
    raw = page.locator(selector).evaluate_all(
        r"""(links) => links.map(a => {
          let box = a;
          for (let i = 0; i < 6 && box; i++, box = box.parentElement) {
            const text = (box.innerText || '').trim();
            const img = box.querySelector('img');
            if (text.length > 3 || img) {
              const price = text.match(/(?:\d+[.,]?\d*)\s*€/);
              return {
                href: a.href,
                text,
                alt: img ? (img.alt || '') : '',
                image: img ? (img.currentSrc || img.src || '') : '',
                price: price ? price[0] : ''
              };
            }
          }
          return {href: a.href, text: '', alt: '', image: '', price: ''};
        })"""
    )

    results = {}
    pattern = r"/items/(\d+)-" if source == "Vinted" else r"/item/[^/?#]+-(\d+)(?:[/?#]|$)"
    for row in raw:
        match = re.search(pattern, row["href"])
        if not match:
            continue
        item_id = f"{source.lower()}:{match.group(1)}"
        text_lines = [line.strip() for line in row["text"].splitlines() if line.strip()]
        title = row["alt"].strip() or (text_lines[0] if text_lines else title_from_url(row["href"]))
        # The search itself is broad enough to catch useful variants. This extra
        # filter rejects unrelated promoted products when their title is available.
        if title and not relevant(title) and source == "Wallapop":
            continue
        results[item_id] = {
            "id": item_id,
            "source": source,
            "title": title[:180],
            "price": row["price"],
            "url": urljoin(url, row["href"]),
            "image": row["image"],
        }
    print(f"{source}: {len(results)} anuncios encontrados")
    return list(results.values())


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"initialized": False, "seen": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(initialized: bool, seen: set[str]) -> None:
    # Limit history so the repository state stays tiny.
    payload = {"initialized": initialized, "seen": sorted(seen)[-5000:]}
    STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def telegram(method: str, token: str, data: dict) -> dict:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=30
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", "Error desconocido de Telegram"))
    return payload


def discover_chat_id(token: str) -> str:
    configured = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if configured:
        return configured
    payload = telegram("getUpdates", token, {"timeout": 0})
    for update in reversed(payload.get("result", [])):
        message = update.get("message") or update.get("channel_post")
        if message and message.get("chat", {}).get("id"):
            return str(message["chat"]["id"])
    raise RuntimeError(
        "No encuentro tu chat. Abre el bot en Telegram, pulsa Iniciar, envía /start y vuelve a ejecutar la tarea."
    )


def notify(token: str, chat_id: str, item: dict) -> None:
    price = f" — {item['price']}" if item["price"] else ""
    text = (
        f"🎮 <b>Nuevo anuncio en {item['source']}</b>\n"
        f"{item['title']}{price}\n\n"
        f"<a href=\"{item['url']}\">Abrir anuncio</a>"
    )
    telegram(
        "sendMessage",
        token,
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "false"},
    )
    time.sleep(0.15)


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Falta el secreto TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return 2
    chat_id = discover_chat_id(token)
    state = load_state()
    seen = set(state.get("seen", []))

    items = []
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            locale="es-ES",
            timezone_id="Europe/Madrid",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
        )
        for source, url in SOURCES.items():
            page = context.new_page()
            try:
                items.extend(scrape_page(page, source, url))
            except Exception as exc:
                errors.append(f"{source}: {exc}")
                print(errors[-1], file=sys.stderr)
            finally:
                page.close()
        browser.close()

    current_ids = {item["id"] for item in items}
    if not state.get("initialized"):
        save_state(True, seen | current_ids)
        telegram(
            "sendMessage",
            token,
            {
                "chat_id": chat_id,
                "text": f"✅ Avisador de juegos PS1 activado. He registrado {len(current_ids)} anuncios actuales; desde ahora te avisaré solo de los nuevos.",
            },
        )
    else:
        new_items = [item for item in items if item["id"] not in seen]
        for item in reversed(new_items[:20]):
            notify(token, chat_id, item)
        save_state(True, seen | current_ids)
        print(f"Nuevos anuncios notificados: {len(new_items[:20])}")

    # A temporary failure in one shop should not discard successful results from
    # the other, but failing both makes the workflow visibly fail.
    if len(errors) == len(SOURCES):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
