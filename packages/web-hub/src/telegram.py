import sys
import aiohttp
from typing import Optional
from src.config import config


def safe_print(text: str, flush: bool = True):
    try:
        print(text, flush=flush)
    except UnicodeEncodeError:
        try:
            encoding = sys.stdout.encoding or 'utf-8'
            encoded = text.encode(encoding, errors='replace').decode(encoding)
            print(encoded, flush=flush)
        except Exception:
            print(text.encode('ascii', errors='replace').decode('ascii'), flush=flush)


async def send_telegram(message: str, token: Optional[str] = None, chat_id: Optional[str] = None, parse_mode: Optional[str] = None) -> bool:
    """
    Sends a Telegram message.
    If token or chat_id are not provided, they default to configuration settings.
    Returns True if successfully sent, False otherwise.
    """
    # Use provided values or fall back to configuration
    tg_token = token or config.telegram_token
    tg_chat_id = chat_id or config.telegram_chat_id

    if not tg_token or not tg_chat_id:
        safe_print(f"[TELEGRAM] Not configured - local log only: {message}")
        return False

    url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    payload = {
        "chat_id": tg_chat_id,
        "text": message
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=5) as resp:
                body = await resp.text()
                if resp.status == 200:
                    safe_print(f"[TELEGRAM] Sent: {message[:80]}...")
                    return True
                else:
                    safe_print(f"[TELEGRAM] ❌ Error {resp.status}: {body[:200]}")
                    return False
    except Exception as e:
        safe_print(f"[TELEGRAM] ❌ Connection error: {e}")
        return False
