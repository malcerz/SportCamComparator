"""Small, bounded-time ntfy publisher used only from daemon workers."""
from __future__ import annotations

import re
import threading
from email.header import Header
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


def send_notification(server: str, topic: str, title: str, message: str,
                      priority: int = 3, tags: str = "", timeout: float = 4.0) -> tuple[bool, str]:
    server = (server or "https://ntfy.sh").strip().rstrip("/")
    topic = (topic or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic):
        return False, "Nieprawidłowy temat ntfy."
    parsed = urlsplit(server)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or re.search(r"\s", server)):
        return False, "Nieprawidłowy adres serwera ntfy."
    url = f"{server}/{quote(topic, safe='-_')}"
    safe_title = title[:120]
    if not safe_title.isascii():
        safe_title = Header(safe_title, "utf-8").encode()
    headers = {
        "Title": safe_title,
        "Priority": str(max(1, min(5, int(priority)))),
        "Content-Type": "text/plain; charset=utf-8",
    }
    if tags:
        headers["Tags"] = tags[:120]
    request = Request(url, data=message[:1000].encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=max(1.0, min(float(timeout), 5.0))) as response:
            if 200 <= response.status < 300:
                return True, "HTTP " + str(response.status)
            return False, "HTTP " + str(response.status)
    except HTTPError as exc:
        return False, f"HTTP {exc.code} {exc.reason}"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return False, str(exc)[:240]


def send_notification_async(server: str, topic: str, title: str, message: str,
                            priority: int = 3, tags: str = "", callback=None):
    """Start a daemon worker; callback receives (success, short_detail)."""
    def worker():
        result = send_notification(server, topic, title, message, priority, tags, timeout=4.0)
        if callback:
            try:
                callback(*result)
            except Exception:
                pass
        if not result[0]:
            print(f"[ntfy] WARNING: powiadomienie niewysłane: {result[1]}")

    thread = threading.Thread(target=worker, name="ComparatorNtfy", daemon=True)
    thread.start()
    return thread
