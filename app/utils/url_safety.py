"""URL safety validators.

The OG-image override field lets a user paste any URL that downstream social
crawlers (Slack, WhatsApp, LinkedIn, Twitter) will fetch as part of link
unfurling. Without validation, a user could:
  - submit a `javascript:` or `data:` scheme (UI/crawler bugs);
  - submit a URL pointing at internal AWS/GCP metadata (169.254.169.254);
  - submit a URL with embedded credentials (`https://x:y@host/path`) which
    some crawlers pass to the host as Authorization;
  - submit a URL pointing at localhost/private IPs for internal probing.

These helpers enforce a strict allow-list: public http/https only, no
credentials, no private/loopback/link-local hosts. The host check uses
socket.getaddrinfo so a DNS name that resolves to 127.0.0.1 still fails.

Intentionally conservative — any failure mode means the URL is rejected.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Tuple
from urllib.parse import urlparse


ALLOWED_SCHEMES = ("http", "https")
MAX_URL_LENGTH = 2048

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _ip_is_private(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    return any(ip in net for net in _PRIVATE_NETWORKS)


def safe_public_url(url: str) -> Tuple[bool, str]:
    """Validate a URL is safe to hand to a third-party crawler.

    Returns (ok, reason). `reason` is "" on success, else a short, lower-case
    token suitable for surfacing as a flash error.
    """
    if not url:
        return True, ""
    if len(url) > MAX_URL_LENGTH:
        return False, "too-long"
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "invalid-url"
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, "bad-scheme"
    if not parsed.netloc:
        return False, "no-host"
    if "@" in parsed.netloc:
        return False, "credentials-not-allowed"
    host = parsed.hostname or ""
    if not host:
        return False, "no-host"
    # Strip IPv6 brackets if any.
    bare_host = host.strip("[]")
    # If it's a literal IP, check directly.
    try:
        ipaddress.ip_address(bare_host)
        if _ip_is_private(bare_host):
            return False, "private-host"
    except ValueError:
        pass
    # Otherwise resolve via DNS — a hostname pointing to a private IP still fails.
    try:
        infos = socket.getaddrinfo(bare_host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False, "unresolvable-host"
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        addr = sockaddr[0]
        try:
            if _ip_is_private(addr):
                return False, "private-host"
        except ValueError:
            return False, "unresolvable-host"
    # Reject obvious internal TLDs as a last cheap check.
    bad_suffixes = (".local", ".internal", ".localhost", ".test", ".example", ".invalid")
    if bare_host.lower().endswith(bad_suffixes):
        return False, "internal-host"
    return True, ""