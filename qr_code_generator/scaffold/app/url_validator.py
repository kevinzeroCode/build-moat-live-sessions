from urllib.parse import urlparse

MAX_URL_LENGTH = 2048

BLOCKED_DOMAINS = {
    "evil.com",
    "malware.example.com",
    "phishing.example.com",
}


def is_blocked_domain(hostname: str | None) -> bool:
    if hostname is None:
        return True
    return hostname.lower() in BLOCKED_DOMAINS


def validate_url(url: str) -> str:
    """Format check, normalization, and blocklist validation."""
    if len(url) > MAX_URL_LENGTH:
        raise ValueError(f"URL exceeds maximum length of {MAX_URL_LENGTH}")

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https scheme")

    if is_blocked_domain(parsed.hostname):
        raise ValueError(f"Domain is blocked: {parsed.hostname}")

    # Normalize: lowercase scheme+host, upgrade http→https, strip trailing slash
    normalized = parsed._replace(
        scheme="https",
        netloc=parsed.netloc.lower(),
    ).geturl()

    return normalized.rstrip("/")
