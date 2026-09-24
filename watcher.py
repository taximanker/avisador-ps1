import json
import os
import re
import sys
import time
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


STATE_PATH = Path("state.json")
SEARCH_TERM = "juegos ps1"
TARGET_GAME_PATTERNS = (
    r"\brival(?:s)?\s+schools?\b",
    r"\bfuture\s+cop(?:\s*:\s*|\s+)l\.?a\.?p\.?d\.?\b",
    r"\bbloody\s+roar\b",
    r"\bcarmageddon\b",
    r"\bcrash\s+bandicoot\b",
    r"\bcrash\s+bash\b",
    r"\bcrash\s+team\s+racing\b",
    r"\bdino\s+crisis\s*(?:2|ii)\b",
    r"\bfighting\s+force\b",
    r"\bfinal\s+fantasy\s*(?:6|vi)\b",
    r"\blemmings\b",
    r"\boddworld\b",
    r"\bresident\s+evil\b",
    r"\bsilent\s+hill\b",
    r"\btekken\s*3\b",
    r"\btheme\s+hospital\b",
    r"\bv[\s-]*rally\b",
    r"\bmarranos\s+en\s+guerra\b",
    r"\bworms\b",
)
SOURCES = {
    "Vinted": "https://www.vinted.es/catalog?search_text=juegos%20ps1&order=newest_first",
    "Wallapop": "https://es.wallapop.com/app/search?keywords=juegos%20ps1&order_by=newest",
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", value.lower()).strip()


def relevant(title: str) -> bool:
    """Accept only the PS1 games selected by the user."""
    text = normalize(title)
    return any(re.search(pattern, text) for pattern in TARGET_GAME_PATTERNS)


def acceptable_listing(text: str) -> bool:
    """Keep PS1 games while rejecting obvious foreign editions and accessories."""
    value = normalize(text)
    if not relevant(value):
        return False

    wrong_platform_patterns = (
        r"\bps\s*[2345]\b",
        r"\bplaystation\s*[2345]\b",
        r"\bxbox\b",
        r"\bgame\s*cube\b",
        r"\bdreamcast\b",
        r"\bnintendo\s*(?:ds|3ds|switch|wii)\b",
        r"\bpc\s*(?:cd-rom|dvd-rom|game|juego)\b",
    )
    if any(re.search(pattern, value) for pattern in wrong_platform_patterns):
        return False

    foreign_patterns = (
        r"\bfrancais(?:e)?\b",
        r"\bfrances(?:a)?\b",
        r"\bfrench\b",
        r"\bfrance\b",
        r"\bcomplet(?:e|es|s)?\b",
        r"\bbon(?:ne)?\s+etat\b",
        r"\btres\s+bon(?:ne)?\b",
        r"\bsans\b",
        r"\bavec\b",
        r"\bboite\b",
        r"\bnotice\b",
        r"\bdisque(?:s)?\b",
        r"\bpour\b",
        r"\bofficiel(?:le)?\b",
        r"\blot\s+de\b",
        r"\bfonctionne\b",
        r"\brayure(?:s)?\b",
        r"\bpal\s*fr\b",
        r"\bversion\s*fr\b",
        r"\bjeu(?:x)?\b",
        r"\bntsc(?:-j)?\b",
        r"\bjap\b",
        r"\bjapon(?:es|esa)?\b",
        r"\bjapan(?:ese)?\b",
        r"\bjapponese\b",
        r"\blotto\b",
        r"\bitalian(?:o|a)?\b",
        r"\bitalien\b",
        r"\bgioc(?:o|hi)\b",
        r"\boriginale\b",
        r"\bprima\s+stampa\b",
        r"\baleman(?:a)?\b",
        r"\ballemand\b",
        r"\bdeutsch\b",
        r"\bgerman\b",
        r"\bingles(?:a)?\b",
        r"\benglish\b",
        r"\bpal\s*uk\b",
        r"\bversion\s*uk\b",
        r"\bportugal\b",
        r"\bportugues(?:a)?\b",
        r"\bportuguese\b",
        r"\bjogo(?:s)?\b",
        r"\bvoor\b",
        r"\binclusief\b",
        r"\bnederlands\b",
    )
    if any(re.search(pattern, value) for pattern in foreign_patterns):
        return False

    game_terms = ("juego", "juegos", "lote", "pack", "coleccion", "titulo", "titulos")
    accessory_patterns = (
        r"\bconsola\b",
        r"\bmando(?:s)?\b",
        r"\bcable(?:s)?\b",
        r"\bmemory\s*card\b",
        r"\btarjeta\s+de\s+memoria\b",
        r"\bmanual\b",
        r"\bcaja\s+vacia\b",
        r"\bcaratula\b",
        r"\breproduccion\b",
        r"\brepro\b",
        r"\breplica\b",
        r"\bsoporte\b",
        r"\badaptador\b",
        r"\bpegatina(?:s)?\b",
        r"\bposter\b",
        r"\bfigura(?:s)?\b",
        r"\bguia\b",
    )
    is_accessory = any(re.search(pattern, value) for pattern in accessory_patterns)
    return not is_accessory or any(term in value for term in game_terms)


def clearly_spanish_listing(text: str) -> bool:
    """Require positive evidence that an ambiguous Vinted advert is Spanish."""
    value = normalize(text)
    strong_patterns = (
        r"\bespana\b",
        r"\bespanol(?:a|es|as)?\b",
        r"\bcastellano\b",
        r"\bpal\s*(?:es|esp)\b",
        r"\bversion\s*(?:es|esp|espanola)\b",
        r"\bedicion\s+espanola\b",
    )
    if any(re.search(pattern, value) for pattern in strong_patterns):
        return True

    # When the seller does not name the edition, accept only descriptions
    # containing several natural Spanish expressions. One isolated word is
    # not enough because it can also appear in Italian or Portuguese adverts.
    spanish_patterns = (
        r"\bvideojuego(?:s)?\b",
        r"\bjuego(?:s)?\b",
        r"\bvendo\b",
        r"\bfunciona(?:ndo)?\b",
        r"\bprobad[oa]\b",
        r"\bbuen\s+estado\b",
        r"\bmuy\s+buen\s+estado\b",
        r"\bincluye\b",
        r"\bcaja\b",
        r"\bcaratula(?:s)?\b",
        r"\bmanual(?:es)?\s+de\s+instrucciones\b",
        r"\bpara\s+playstation\b",
        r"\bsin\s+manual\b",
        r"\bcon\s+manual\b",
    )
    return sum(bool(re.search(pattern, value)) for pattern in spanish_patterns) >= 2


def filter_new_vinted_items(
    context, items: list[dict], seen: set[str]
) -> tuple[list[dict], set[str]]:
    """Inspect only unseen Vinted adverts and discard non-Spanish editions."""
    filtered = []
    rejected_ids = set()
    for item in items:
        if item["source"] != "Vinted" or item["id"] in seen:
            filtered.append(item)
            continue

        page = context.new_page()
        try:
            page.goto(item["url"], wait_until="domcontentloaded", timeout=45_000)
            description = page.locator('[itemprop="description"]').first
            description.wait_for(state="attached", timeout=12_000)
            detail_text = description.inner_text(timeout=5_000)
            searchable_text = f"{item['title']} {detail_text}"
            if acceptable_listing(searchable_text) and clearly_spanish_listing(searchable_text):
                filtered.append(item)
            else:
                rejected_ids.add(item["id"])
                print(f"Vinted descartado por idioma: {item['title']}")
        except Exception as exc:
            # Do not mark it as seen: a transient loading error will be retried
            # during the following scheduled execution.
            print(
                f"Vinted no pudo comprobar el idioma de {item['id']}: {exc}",
                file=sys.stderr,
            )
        finally:
            page.close()
    return filtered, rejected_ids


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
    selector = 'a[href*="/items/"]' if source == "Vinted" else 'article a[href*="/item/"]'
    try:
        page.locator(selector).first.wait_for(state="attached", timeout=30_000)
    except PlaywrightTimeoutError:
        # Wallapop sometimes leaves its loading skeleton visible on the first
        # request. A reload is enough when this is a transient response.
        if source == "Wallapop":
            print("Wallapop sigue cargando; reintentando una vez...")
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            page.locator(selector).first.wait_for(state="attached", timeout=30_000)
        else:
            raise
    page.wait_for_timeout(2_000)

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
        # Both shops mix unrelated promoted products into their search results.
        searchable_text = f"{title} {row['text']}"
        if title and not acceptable_listing(searchable_text):
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


def scrape_wallapop() -> list[dict]:
    """Use the same public search endpoint as Wallapop's current web client."""
    print("Consultando Wallapop...")
    device_id = str(uuid.uuid4())
    response = requests.get(
        "https://api.wallapop.com/api/v3/search/section",
        params={
            "keywords": SEARCH_TERM,
            "order_by": "newest",
            "section_type": "organic_search_results",
            "source": "search_box",
            "latitude": "40.4168",
            "longitude": "-3.7038",
        },
        headers={
            "Accept": "application/json",
            "Accept-Language": "es-ES,es;q=0.9",
            "Origin": "https://es.wallapop.com",
            "Referer": "https://es.wallapop.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36"
            ),
            "deviceos": "0",
            "x-deviceos": "0",
            "x-deviceid": device_id,
            "x-appversion": "827040",
        },
        timeout=40,
    )
    response.raise_for_status()
    rows = response.json().get("data", {}).get("section", {}).get("items", [])
    results = []
    for row in rows:
        title = str(row.get("title", "")).strip()
        searchable_text = f"{title} {row.get('description', '')}"
        if not acceptable_listing(searchable_text):
            continue
        price_data = row.get("price") or {}
        amount = price_data.get("amount")
        if isinstance(amount, (int, float)):
            formatted = f"{amount:g}".replace(".", ",") + " €"
        else:
            formatted = ""
        images = row.get("images") or []
        image = ""
        if images:
            image = (images[0].get("urls") or {}).get("small", "")
        slug = str(row.get("web_slug", "")).strip()
        item_id = str(row.get("id", "")).strip()
        if not item_id or not slug:
            continue
        results.append(
            {
                "id": f"wallapop:{item_id}",
                "source": "Wallapop",
                "title": title[:180],
                "price": formatted,
                "url": f"https://es.wallapop.com/item/{slug}",
                "image": image,
            }
        )
    print(f"Wallapop: {len(results)} anuncios de PS1 encontrados")
    return results


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
    if item.get("image"):
        try:
            telegram(
                "sendPhoto",
                token,
                {
                    "chat_id": chat_id,
                    "photo": item["image"],
                    "caption": text,
                    "parse_mode": "HTML",
                },
            )
            time.sleep(0.15)
            return
        except Exception as exc:
            print(f"No se pudo enviar la miniatura de {item['id']}: {exc}", file=sys.stderr)
    telegram(
        "sendMessage",
        token,
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        },
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
    rejected_ids = set()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="es-ES", timezone_id="Europe/Madrid")
        for source, url in SOURCES.items():
            if source == "Wallapop":
                try:
                    items.extend(scrape_wallapop())
                except Exception as exc:
                    errors.append(f"{source}: {exc}")
                    print(errors[-1], file=sys.stderr)
                continue
            page = context.new_page()
            try:
                items.extend(scrape_page(page, source, url))
            except Exception as exc:
                errors.append(f"{source}: {exc}")
                print(errors[-1], file=sys.stderr)
            finally:
                page.close()
        if state.get("initialized"):
            items, rejected_ids = filter_new_vinted_items(context, items, seen)
        browser.close()

    current_ids = {item["id"] for item in items} | rejected_ids
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
        active_sources = {item["source"].lower() for item in items}
        known_sources = {item_id.split(":", 1)[0] for item_id in seen}
        newly_activated = active_sources - known_sources
        new_items = [
            item
            for item in items
            if item["id"] not in seen and item["source"].lower() not in newly_activated
        ]
        notified = 0
        for source in SOURCES:
            source_items = [item for item in new_items if item["source"] == source]
            # Each shop gets its own quota, so a noisy Vinted run can never
            # prevent Wallapop alerts from reaching Telegram.
            for item in reversed(source_items[:15]):
                notify(token, chat_id, item)
                notified += 1
        for source in sorted(newly_activated):
            count = sum(item["source"].lower() == source for item in items)
            telegram(
                "sendMessage",
                token,
                {
                    "chat_id": chat_id,
                    "text": f"✅ {source.title()} activado. He registrado {count} anuncios actuales; te avisaré de los nuevos.",
                },
            )
        save_state(True, seen | current_ids)
        print(f"Nuevos anuncios notificados: {notified}")

    # Results from the working shop are still saved, but any failed source makes
    # the workflow visibly fail so a silent outage cannot go unnoticed again.
    if errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
