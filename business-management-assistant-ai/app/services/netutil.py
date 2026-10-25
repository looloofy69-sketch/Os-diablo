"""Small network-policy helpers shared by model endpoints and connectors."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


def is_private_host(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def check_outbound_url(url: str, allow_insecure_remote: bool = False) -> str:
    """Validate an explicitly configured outbound HTTP(S) URL.

    Credentials, ambiguous whitespace/control characters, malformed ports, query
    strings, and fragments are rejected to reduce accidental secret leakage and
    configuration ambiguity. This validates URL syntax; it is not a complete
    DNS-rebinding or network-egress firewall.
    """
    if not isinstance(url, str) or not url or url != url.strip():
        raise ValueError("URL must be a non-empty string without surrounding whitespace")
    if any(character.isspace() or ord(character) < 33 for character in url):
        raise ValueError("URL must not contain whitespace or control characters")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must be http(s) with a host")
    if parsed.username or parsed.password:
        raise ValueError("URL must not embed credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL has an invalid port") from exc
    if parsed.netloc.endswith(":"):
        raise ValueError("URL has an empty port")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("URL port must be between 1 and 65535")
    if "?" in url or "#" in url:
        raise ValueError("URL must not contain a query or fragment")
    if parsed.scheme == "http" and not allow_insecure_remote and not is_private_host(url):
        raise ValueError("remote URLs must use https")
    return url
