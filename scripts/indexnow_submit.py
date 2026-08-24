"""IndexNow batch submit for FolioSpace.

IndexNow is a Bing/Yandex protocol that pings search engines about changed
URLs. FolioSpace pushes both the static marketing pages and the public
folio slugs so Bing Copilot and Bing Webmaster pick them up faster.

Usage:
    INDEXNOW_API_KEY=<32-char-hex> python -m scripts.indexnow_submit

    # Or submit only specific URLs:
    INDEXNOW_API_KEY=<32-char-hex> python -m scripts.indexnow_submit \
        --urls https://foliospace.in/stats https://foliospace.in/founder

API key: https://www.bing.com/indexnow (one key per host, free, no account
required). Set INDEXNOW_API_KEY in Render env to enable the /admin/indexnow
button and the manual cron submit.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from urllib.parse import urlparse
from urllib.request import Request as URLRequest
from urllib.request import urlopen

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("indexnow")

HOST = (os.getenv("PUBLIC_BASE_URL") or "https://foliospace.in").rstrip("/")
KEY = os.getenv("INDEXNOW_API_KEY", "").strip()
KEY_LOCATION = (os.getenv("INDEXNOW_KEY_LOCATION") or f"{HOST}/{KEY}.txt").strip() if KEY else ""
SUBMIT_URL = "https://api.indexnow.org/indexnow"
BATCH_LIMIT = 10_000


def _collect_static_urls() -> list[str]:
    return [
        f"{HOST}/",
        f"{HOST}/pricing",
        f"{HOST}/security",
        f"{HOST}/features",
        f"{HOST}/privacy",
        f"{HOST}/terms",
        f"{HOST}/space-community",
        f"{HOST}/portfolio-builder",
        f"{HOST}/student-portfolio",
        f"{HOST}/developer-portfolio",
        f"{HOST}/designer-portfolio",
        f"{HOST}/chef-portfolio",
        f"{HOST}/consultant-portfolio",
        f"{HOST}/freelancer-portfolio",
        f"{HOST}/small-business-website",
        f"{HOST}/stats",
        f"{HOST}/founder",
        f"{HOST}/research",
        f"{HOST}/vs/carrd",
        f"{HOST}/vs/linkedin",
        f"{HOST}/vs/about-me",
        f"{HOST}/vs/notion",
        f"{HOST}/vs/wordpress",
        f"{HOST}/vs/github-pages",
    ]


def _collect_folio_urls() -> list[str]:
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        return []
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT slug FROM users
                     WHERE is_public = TRUE AND deleted_at IS NULL
                       AND slug IS NOT NULL AND slug <> ''
                    """
                )
                rows = cur.fetchall() or []
            conn.commit()
        return [f"{HOST}/{r['slug']}" for r in rows if r.get("slug")]
    except Exception as e:
        logger.exception("folio url collect failed: %s", e)
        return []


def submit(urls: list[str], key: str = KEY, host: str = HOST, key_location: str = KEY_LOCATION) -> dict:
    if not key:
        return {"ok": False, "error": "INDEXNOW_API_KEY missing", "submitted": 0}
    if not urls:
        return {"ok": False, "error": "no urls", "submitted": 0}
    if len(urls) > BATCH_LIMIT:
        return {"ok": False, "error": f"too many urls ({len(urls)} > {BATCH_LIMIT})", "submitted": 0}
    parsed_host = urlparse(host).netloc
    payload = {
        "host": parsed_host,
        "key": key,
        "keyLocation": key_location or f"{host}/{key}.txt",
        "urlList": urls,
    }
    data = json.dumps(payload).encode("utf-8")
    req = URLRequest(
        SUBMIT_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urlopen(req, timeout=30) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.exception("submit failed: %s", e)
        return {"ok": False, "error": str(e), "submitted": 0}
    return {
        "ok": 200 <= status < 300,
        "http_status": status,
        "submitted": len(urls),
        "response": body[:500],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", nargs="*", help="Explicit URLs to submit; otherwise auto-collect")
    parser.add_argument("--static-only", action="store_true", help="Skip folio slugs")
    args = parser.parse_args()

    if args.urls:
        urls = list(args.urls)
    else:
        urls = _collect_static_urls()
        if not args.static_only:
            urls.extend(_collect_folio_urls())

    urls = [u.strip() for u in urls if u and u.strip()]
    urls = sorted(set(urls))
    logger.info("submitting %d urls to %s", len(urls), SUBMIT_URL)
    result = submit(urls)
    logger.info("result=%s", result)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
