import os
import re
import logging
import asyncio
import requests
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from flask import Flask

# ---------- Logging ----------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("signal_copier")

# ---------- Telegram API ----------
API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
TG_SESSION_ENV = os.getenv("TG_SESSION", "").strip()

if TG_SESSION_ENV and len(TG_SESSION_ENV) > 100:
    session_obj = StringSession(TG_SESSION_ENV)
else:
    session_obj = TG_SESSION_ENV or "session"

SOURCE_CHAT = os.getenv("SOURCE_CHAT")
TARGET_CHAT = os.getenv("TARGET_CHAT")

if not API_ID or not API_HASH:
    log.error("TG_API_ID and TG_API_HASH must be set.")
    raise SystemExit(1)

# ---------- Regex ----------
DIRECTION_RE = re.compile(r"\b(LONG|SHORT)\b", flags=re.I)
PAIR_RE = re.compile(r"([A-Z]{2,10}/USDT)", flags=re.I)
ENTRY_RE = re.compile(r"ENTRY.*?(?:PRICE|NOW)?[: ]*([0-9]*\.?[0-9]+)", flags=re.I)
LEVERAGE_RE = re.compile(r"(LEVERAGE|CROSS).*?(\d{1,3})\s*x?", flags=re.I)
TP_RE = re.compile(r"(TP\d*|TAKE PROFIT)\s*[:=]?\s*([0-9]+%|[0-9]*\.?[0-9]+)", flags=re.I)
SL_RE = re.compile(r"SL\s*[:=]?\s*([0-9]*\.?[0-9]+)", flags=re.I)

# ---------- Template ----------
CORNIX_TEMPLATE = (
    "{direction_upper} {pair}\n"
    "Leverage: {leverage}x\n"
    "Entry: {entry}\n"
    "{tps_block}"
    "SL: {sl}\n\n"
    "Forwarded by signal-copier"
)

# ---------- Flask keep-alive ----------
app = Flask("keepalive")

@app.route("/")
def home():
    return "OK - signal copier is running"

# ---------- Helper: Get live price ----------
def get_market_price(symbol: str) -> float:
    """
    Fetch current market price from Binance public API.
    """
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper().replace('/', '')}"
        response = requests.get(url, timeout=5)
        data = response.json()
        return float(data["price"])
    except Exception as e:
        log.error(f"Error fetching market price for {symbol}: {e}")
        return None

# ---------- Bot logic ----------
async def create_client_and_run():
    client = TelegramClient(session_obj, int(API_ID), API_HASH)
    await client.start()
    log.info("Telethon client started")

    async def resolve_name(name):
        if not name:
            return None
        if name.startswith("@"):
            return name
        if re.fullmatch(r"-?\d+", name):
            return int(name)
        return name

    resolved_source = await resolve_name(SOURCE_CHAT) if SOURCE_CHAT else None
    resolved_target = await resolve_name(TARGET_CHAT) if TARGET_CHAT else None

    @client.on(events.NewMessage(chats=resolved_source))
    async def handler(event):
        try:
            text = (event.message.message or "") + " " + (event.message.text or "")
            log.info("New message: %s", text[:200].replace("\n", " "))

            # Direction
            direction_m = DIRECTION_RE.search(text)
            direction = direction_m.group(1).upper() if direction_m else "LONG"

            # Pair
            pair_m = PAIR_RE.search(text)
            pair = pair_m.group(1).upper() if pair_m else "PAIR"
            if not pair.startswith("#"):
                pair = "#" + pair

            # Leverage
            leverage_m = LEVERAGE_RE.search(text)
            leverage = leverage_m.group(2) if leverage_m else "0"

            # Entry
            entry_price = None
            entry_m = ENTRY_RE.search(text)
            if entry_m:
                try:
                    entry_price = float(entry_m.group(1))
                except:
                    entry_price = None

            # If no entry → fetch live market price
            if not entry_price:
                symbol = pair.replace("#", "").replace("/", "")
                entry_price = get_market_price(symbol)

            entry_str = f"{entry_price:.5f}" if entry_price else "Market Price"

            # Take Profits
            tp_matches = [m[1] for m in TP_RE.findall(text)]
            tps_block = ""
            for i, tp in enumerate(tp_matches[:5], start=1):
                if entry_price:
                    if tp.strip() == "500%":
                        price = entry_price * 1.1
                        tps_block += f"TP{i}: {price:.5f}\n"
                    elif tp.strip() == "1000%":
                        price = entry_price * 2.2
                        tps_block += f"TP{i}: {price:.5f}\n"
                    else:
                        tps_block += f"TP{i}: {tp}\n"
                else:
                    tps_block += f"TP{i}: {tp}\n"

            # Stop loss
            sl_m = SL_RE.search(text)
            sl = sl_m.group(1) if sl_m else "N/A"

            # Build message
            body = CORNIX_TEMPLATE.format(
                direction_upper=direction,
                pair=pair,
                leverage=leverage,
                entry=entry_str,
                tps_block=tps_block,
                sl=sl
            )

            if resolved_target:
                await client.send_message(resolved_target, body)
                log.info("Sent to %s", resolved_target)
            else:
                log.warning("No TARGET_CHAT configured")

        except Exception as e:
            log.exception("Error handling message: %s", e)

    log.info("Listening... (source=%s -> target=%s)", resolved_source, resolved_target)
    await client.run_until_disconnected()

# ---------- Run ----------
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    from threading import Thread

    def run_flask():
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 3000)))

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    try:
        loop.run_until_complete(create_client_and_run())
    except KeyboardInterrupt:
        log.info("Stopping...")
