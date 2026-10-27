"""URL extraction and filtering module for Telegram deal messages.
Extracts URLs from raw text, Markdown links, and Telegram Rich Entities (MessageEntityTextUrl).
"""

import re
from typing import List, Optional
from urllib.parse import urlparse
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

# Robust URL regex covering http/https with paths, queries, and fragments
URL_REGEX = re.compile(
    r"(?:https?://)"  # Scheme
    r"(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}"  # Domain
    r"(?::\d+)?"  # Port
    r"(?:/[^\s<>\"\'\)]*)?",  # Path/Query (exclude common trailing delimiters)
    re.IGNORECASE,
)


def _clean_url(url: str) -> str:
    """Strips trailing punctuation commonly caught by regex at the end of sentences."""
    return url.rstrip(".,;:!?)>\"'")


def _matches_domains(url: str, allowed_domains: Optional[List[str]]) -> bool:
    """Checks whether the URL belongs to allowed deal domains.

    Matches against hostname or path (e.g., amzn.to, fkrt.it, amazon.in).
    """
    if not allowed_domains:
        return True

    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        full_url = url.lower()

        for domain in allowed_domains:
            # Check domain keyword against hostname or full url
            if domain in hostname or f".{domain}." in hostname or f"{domain}/" in full_url:
                return True
        return False
    except Exception:
        return False


def extract_deal_urls(
    message,
    filter_domains: bool = True,
    allowed_domains: Optional[List[str]] = None,
) -> List[str]:
    """Extracts all unique deal URLs from a Telethon Message object.

    Inspects both message text (via regex) and Telegram Rich Entities (MessageEntityTextUrl).
    """
    found_urls: List[str] = []
    seen = set()

    def add_url(raw: str):
        cleaned = _clean_url(raw.strip())
        if not cleaned:
            return
        # Basic sanity check
        if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
            return

        if filter_domains and not _matches_domains(cleaned, allowed_domains):
            return

        if cleaned not in seen:
            seen.add(cleaned)
            found_urls.append(cleaned)

    # 1. Inspect Telethon Rich Entities (e.g., hyperlinks hidden under text)
    if message.entities:
        for entity in message.entities:
            if isinstance(entity, MessageEntityTextUrl):
                if entity.url:
                    add_url(entity.url)
            elif isinstance(entity, MessageEntityUrl):
                # Plain URL in text identified by Telegram
                try:
                    text = message.text or message.message or ""
                    extracted = text[entity.offset : entity.offset + entity.length]
                    add_url(extracted)
                except Exception:
                    pass

    # 2. Inspect raw message text and caption (for photos/media)
    text_content = message.text or message.message or ""
    if text_content:
        for match in URL_REGEX.finditer(text_content):
            add_url(match.group(0))

    return found_urls


def has_deal_urls(
    message,
    filter_domains: bool = True,
    allowed_domains: Optional[List[str]] = None,
) -> bool:
    """Returns True if message contains at least one relevant deal URL."""
    urls = extract_deal_urls(message, filter_domains=filter_domains, allowed_domains=allowed_domains)
    return len(urls) > 0
