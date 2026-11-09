"""
notify.py - instant owner alerts through a free Telegram bot (and browser push, see push.py).

Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (see docs/TELEGRAM_GUIDE.md).
If they are not set, alerts are silently skipped and attendance still works.
Messages are sent in a background thread so check-in is never slowed down.
"""
import os
import threading
import requests


def _send(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        if r.status_code != 200:
            print("Telegram error:", r.status_code, r.text)
        return r.status_code == 200
    except Exception as e:  # never let an alert break a check-in
        print("Telegram failed:", e)
        return False


def is_configured():
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


_push_hook = None


def set_push_hook(fn):
    """push.py registers itself here so every owner alert also goes out as a browser notification."""
    global _push_hook
    _push_hook = fn


def notify_owner(text):
    """Fire-and-forget alert to the owner (Telegram + browser push)."""
    threading.Thread(target=_send, args=(text,), daemon=True).start()
    if _push_hook:
        try:
            _push_hook(text)
        except Exception as e:  # an alert must never break the real action
            print("Push hook failed:", e)


def notify_owner_now(text):
    """Blocking version (used by the admin 'send test alert' button)."""
    return _send(text)
