import logging
import urllib.request
from urllib.parse import quote

log = logging.getLogger(__name__)


def notify(url: str, topic: str, token: str, title: str, message: str) -> None:
    if not url or not topic:
        return
    request = urllib.request.Request(
        f"{url}/{topic}?title={quote(title)}&tags=warning",
        data=message.encode("utf-8"),
        method="POST",
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except OSError as e:
        log.warning("failed to notify ntfy: %s", e)
