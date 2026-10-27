"""Amazon Affiliate link conversion module.
Handles domain detection, redirect resolution (for amzn.to, amzn-to.co, amzn.in, a.co, etc.),
ASIN extraction, and affiliate tag injection.
"""

import asyncio
import logging
import re
from typing import List, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import aiohttp

logger = logging.getLogger("AmazonAffiliate")

# Standard ASIN pattern (10 alphanumeric characters)
ASIN_PATTERN = re.compile(r"/(?:dp|gp/product|d)/([A-Z0-9]{10})(?:[/?#]|$)", re.IGNORECASE)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def is_amazon_url(url: str) -> bool:
    """Checks whether a URL points to Amazon or any Amazon redirect shortener.

    Matches:
      - Any hostname with 'amazon.' (amazon.in, amazon.com, etc.)
      - Any hostname containing 'amzn' (amzn.to, amzn-to.co, amznto.co, amzn.in, amzn.urlgeni.us, etc.)
      - a.co / *.a.co
    """
    if not url:
        return False
    try:
        hostname = (urlparse(url).hostname or "").lower()
        if not hostname:
            return False
        if "amazon." in hostname:
            return True
        if "amzn" in hostname:
            return True
        if hostname == "a.co" or hostname.endswith(".a.co"):
            return True
        return False
    except Exception:
        return False


def extract_asin(url: str) -> Optional[str]:
    """Extracts the 10-character Amazon Standard Identification Number (ASIN) if present."""
    match = ASIN_PATTERN.search(url)
    if match:
        return match.group(1).upper()
    return None


async def resolve_redirect(url: str, session: Optional[aiohttp.ClientSession] = None) -> str:
    """Resolves short redirect links (amzn.to, amzn-to.co, amzn.in, a.co) to the final destination URL."""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    # If it's already a full amazon.in or amazon.com product URL with ASIN, no need to resolve
    if ("amazon.in" in hostname or "amazon.com" in hostname) and extract_asin(url):
        return url

    close_session_on_exit = False
    if session is None:
        connector = aiohttp.TCPConnector(ssl=False)
        session = aiohttp.ClientSession(
            connector=connector,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=10),
        )
        close_session_on_exit = True

    try:
        # Use GET with allow_redirects=True to follow multi-hop shortener chains (e.g. amzn-to.co -> urlgeni.us -> amazon.in)
        async with session.get(url, allow_redirects=True, max_redirects=10) as resp:
            final_url = str(resp.url)
            if is_amazon_url(final_url):
                return final_url
    except Exception as exc:
        logger.warning("Could not resolve redirect for %s: %s", url, exc)
    finally:
        if close_session_on_exit and not session.closed:
            await session.close()

    return url


def inject_affiliate_tag(url: str, tag: str) -> str:
    """Injects or replaces the affiliate tag in an Amazon URL.

    If an ASIN is found, produces a clean high-converting product link:
    https://www.amazon.in/dp/{ASIN}?tag={tag}
    Otherwise, preserves the path/search queries and sets/replaces the 'tag' parameter.
    """
    if not tag:
        return url

    asin = extract_asin(url)
    if asin:
        # Preserve base domain if possible (default to amazon.in)
        parsed = urlparse(url)
        netloc = parsed.netloc if "amazon." in parsed.netloc else "www.amazon.in"
        return f"https://{netloc}/dp/{asin}?tag={tag}"

    # General page (deal/category/search/store): update query params
    try:
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)

        # Set or replace the affiliate tag
        query_params["tag"] = [tag]

        # Clean competitor referral / tracking parameters
        tracking_params = (
            "ascsubtag", "linkCode", "camp", "creative", "ref_", "ref",
            "sid", "src", "btn_ref", "btn_type", "ds", "qid", "srs",
            "pf_rd_i", "pf_rd_m", "pf_rd_p", "pf_rd_r", "pf_rd_s", "pf_rd_t"
        )
        for stale_param in tracking_params:
            query_params.pop(stale_param, None)

        new_query = urlencode(query_params, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        # Fallback query append
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}tag={tag}"


async def convert_amazon_url(
    url: str,
    affiliate_tag: str,
    session: Optional[aiohttp.ClientSession] = None,
) -> str:
    """End-to-end converter: resolves short URLs if needed and injects user affiliate tag."""
    if not affiliate_tag:
        return url

    # Resolve redirects if URL is a short link (e.g. amzn.to, amzn-to.co, amzn.in, a.co)
    destination_url = await resolve_redirect(url, session=session)
    return inject_affiliate_tag(destination_url, affiliate_tag)


async def replace_amazon_urls_in_text(
    text: str,
    amazon_urls: List[str],
    affiliate_tag: str,
    session: Optional[aiohttp.ClientSession] = None,
) -> tuple[str, dict[str, str]]:
    """Replaces all original Amazon URLs in text with their converted affiliate counterparts in parallel.

    Returns the updated text and a mapping of {original_url: converted_url}.
    """
    if not text or not amazon_urls or not affiliate_tag:
        return text, {}

    # Resolve all URLs in parallel using asyncio.gather
    tasks = [convert_amazon_url(u, affiliate_tag, session=session) for u in amazon_urls]
    converted_list = await asyncio.gather(*tasks, return_exceptions=True)

    url_map: dict[str, str] = {}
    for orig, conv in zip(amazon_urls, converted_list):
        if isinstance(conv, Exception):
            logger.warning("Error converting URL %s: %s", orig, conv)
            url_map[orig] = orig
        else:
            url_map[orig] = conv

    # Replace in text, sorting by length descending to avoid partial prefix collisions
    updated_text = text
    for orig, conv in sorted(url_map.items(), key=lambda x: len(x[0]), reverse=True):
        updated_text = updated_text.replace(orig, conv)

    return updated_text, url_map


async def prepare_amazon_message(
    message,
    amazon_urls: List[str],
    affiliate_tag: str,
    session: Optional[aiohttp.ClientSession] = None,
) -> tuple[str, list, dict[str, str]]:
    """Prepares text and entities with Amazon URLs converted to user's affiliate tag.

    Converts URLs embedded inside MessageEntityTextUrl entities as well as
    standard URLs in raw message text / caption. All URLs resolved concurrently.
    """
    from telethon.tl.types import MessageEntityTextUrl

    raw_text = message.text or message.message or ""
    entities = list(message.entities) if message.entities else []

    # 1. Resolve all Amazon URLs in parallel
    tasks = [convert_amazon_url(u, affiliate_tag, session=session) for u in amazon_urls]
    converted_list = await asyncio.gather(*tasks, return_exceptions=True)

    url_map: dict[str, str] = {}
    for orig, conv in zip(amazon_urls, converted_list):
        if isinstance(conv, Exception):
            logger.warning("Error converting URL %s: %s", orig, conv)
            url_map[orig] = orig
        else:
            url_map[orig] = conv

    # 2. Convert embedded hyperlink entities
    new_entities = []
    for ent in entities:
        if isinstance(ent, MessageEntityTextUrl) and is_amazon_url(ent.url):
            converted = url_map.get(ent.url)
            if not converted:
                try:
                    converted = await convert_amazon_url(ent.url, affiliate_tag, session=session)
                    url_map[ent.url] = converted
                except Exception:
                    converted = ent.url
            ent.url = converted
        new_entities.append(ent)

    # 3. Convert occurrences in raw message text
    updated_text = raw_text
    for orig, conv in sorted(url_map.items(), key=lambda x: len(x[0]), reverse=True):
        if orig in updated_text:
            updated_text = updated_text.replace(orig, conv)

    return updated_text, new_entities, url_map
