"""Configuration module for Telegram Deal Forwarder.
Loads environment variables from .env and provides parsed, type-safe settings.
"""

import os
import sys
import logging
from typing import List, Union
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)


def _parse_bool(val: str, default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in ("true", "1", "yes", "y", "t")


def _parse_channel_identifier(identifier: str) -> Union[int, str]:
    """Normalizes channel username or numeric ID.

    If the string represents an integer (e.g., -100123456789), returns int.
    Otherwise returns cleaned string username.
    """
    clean_id = identifier.strip()
    try:
        return int(clean_id)
    except ValueError:
        # Return username (preserving or ensuring standard format)
        return clean_id


def _parse_channels(raw_channels: str) -> List[Union[int, str]]:
    if not raw_channels:
        return []
    channels: List[Union[int, str]] = []
    for item in raw_channels.split(","):
        cleaned = item.strip()
        if cleaned:
            channels.append(_parse_channel_identifier(cleaned))
    return channels


def _parse_list(raw_list: str) -> List[str]:
    if not raw_list:
        return []
    return [item.strip().lower() for item in raw_list.split(",") if item.strip()]


# Telegram API Credentials
API_ID_RAW = os.getenv("TELEGRAM_API_ID", "")
API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
PHONE_NUMBER = os.getenv("TELEGRAM_PHONE", "").strip()
SESSION_NAME = os.getenv("SESSION_NAME", "extrape_userbot").strip()
STRING_SESSION = os.getenv("TELEGRAM_STRING_SESSION", "").strip()

try:
    API_ID = int(API_ID_RAW) if API_ID_RAW else 0
except ValueError:
    API_ID = 0

# Routing
SOURCE_CHANNELS = _parse_channels(os.getenv("SOURCE_CHANNELS", ""))
TARGET_BOT = os.getenv("TARGET_BOT", "@Extrape_bot").strip()

# Amazon Affiliate & Direct Channel Routing
AMAZON_AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "").strip()
_raw_my_channel = os.getenv("MY_TELEGRAM_CHANNEL", "").strip()
MY_TELEGRAM_CHANNEL = _parse_channel_identifier(_raw_my_channel) if _raw_my_channel else None
# If False, Amazon deals will NOT be forwarded to ExtraPe (preventing ineligible bot errors)
SEND_AMAZON_TO_EXTRAPE = _parse_bool(os.getenv("SEND_AMAZON_TO_EXTRAPE", "False"), default=False)

# Message Extraction & Forwarding Mode
FORWARD_FULL_MESSAGE = _parse_bool(os.getenv("FORWARD_FULL_MESSAGE", "False"), default=False)
FILTER_DOMAINS = _parse_bool(os.getenv("FILTER_DOMAINS", "True"), default=True)
ALLOWED_DOMAINS = _parse_list(
    os.getenv(
        "ALLOWED_DOMAINS",
        "amazon,amzn,flipkart,fkrt,myntra,ajio,tatacliq,nykaa,croma,meesho,boat-lifestyle,reliancedigital",
    )
)

# Rate Limiting & Delays (in seconds)
try:
    MIN_DELAY = float(os.getenv("MIN_DELAY_SECONDS", "2.0"))
except ValueError:
    MIN_DELAY = 2.0

try:
    MAX_DELAY = float(os.getenv("MAX_DELAY_SECONDS", "4.0"))
except ValueError:
    MAX_DELAY = 4.0

if MIN_DELAY > MAX_DELAY:
    MIN_DELAY, MAX_DELAY = MAX_DELAY, MIN_DELAY


def validate_config() -> bool:
    """Validates that necessary configuration is provided."""
    missing = []
    if not API_ID:
        missing.append("TELEGRAM_API_ID (must be a valid integer)")
    if not API_HASH:
        missing.append("TELEGRAM_API_HASH")
    if not SOURCE_CHANNELS:
        missing.append("SOURCE_CHANNELS (at least one channel is required)")
    if not TARGET_BOT:
        missing.append("TARGET_BOT")

    if AMAZON_AFFILIATE_TAG and not MY_TELEGRAM_CHANNEL:
        logger.warning(
            "AMAZON_AFFILIATE_TAG is configured, but MY_TELEGRAM_CHANNEL is not set. "
            "Converted Amazon deals will have nowhere to be sent!"
        )
    if MY_TELEGRAM_CHANNEL and not AMAZON_AFFILIATE_TAG:
        logger.warning(
            "MY_TELEGRAM_CHANNEL is configured, but AMAZON_AFFILIATE_TAG is empty. "
            "Amazon links cannot be tagged with your affiliate ID!"
        )

    if missing:
        logger.error("Configuration validation failed! Missing required settings:")
        for item in missing:
            logger.error("  - %s", item)
        logger.error("Please configure these in your .env file (see .env.example).")
        return False
    return True
