"""Optional DuckDNS IP updater (call from cron or a small maintenance task)."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


async def update_duckdns(domain: str, token: str) -> tuple[bool, str]:
    """
    Tell DuckDNS your current public IP.

    Returns (ok, response_text). Empty domain/token -> no-op success.
    """
    if not domain or not token:
        return True, "skipped"
    url = f"https://www.duckdns.org/update?domains={domain}&token={token}&ip="
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(url)
        text = (r.text or "").strip()
        ok = r.status_code == 200 and text.startswith("OK")
        log.info("DuckDNS update: status=%s body=%s", r.status_code, text)
        return ok, text
