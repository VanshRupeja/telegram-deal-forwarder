#!/usr/bin/env python3
"""Production-Ready Telegram Deal Forwarder for ExtraPe Bot (@Extrape_bot)

and Direct Amazon Affiliate Channel Routing.

Monitors Telegram deal channels in real-time:
1. Amazon deals: Converts Amazon links to user's affiliate tag and posts directly
   to the user's private/public Telegram channel with full text and media.
2. Non-Amazon deals (Flipkart, Myntra, Ajio, etc.): Forwards to ExtraPe Bot for conversion.
3. Automatically filters out Amazon links from ExtraPe to prevent ineligible affiliate errors.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import random
import sys
from typing import List, Optional

import aiohttp
from telethon import TelegramClient, events
from telethon.errors.rpcerrorlist import FloodWaitError
from telethon.tl.types import User

import config
from amazon import is_amazon_url, prepare_amazon_message
from extractor import extract_deal_urls

# ==============================================================================
# Logging Configuration
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("forwarder.log", mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger("DealForwarder")

# Suppress overly verbose Telethon internal debug logs
logging.getLogger("telethon").setLevel(logging.WARNING)

# ==============================================================================
# Telegram Client Initialization
# ==============================================================================
from telethon.sessions import StringSession

if config.STRING_SESSION:
    session_target = StringSession(config.STRING_SESSION)
    logger.info("Using Telethon StringSession for cloud deployment.")
else:
    session_target = config.SESSION_NAME

client = TelegramClient(
    session_target,
    config.API_ID,
    config.API_HASH,
)

# Async message queue to guarantee sequential dispatch and rate limiting
message_queue: asyncio.Queue = asyncio.Queue()

# Resolved entities cached on startup
target_bot_entity = None
my_channel_entity = None
current_user = None
aiohttp_session: Optional[aiohttp.ClientSession] = None
stats = {
    "status": "Starting",
    "telegram_connected": False,
    "user": None,
    "amazon_deals": 0,
    "extrape_deals": 0,
    "last_deal_at": None,
    "last_deal_title": None,
    "error": None,
    "uptime_start": None,
    "source_channels": [],
    "target_channel": str(config.MY_TELEGRAM_CHANNEL or "Not configured"),
    "target_bot": str(config.TARGET_BOT or "Not configured"),
}


# ==============================================================================
# Message Dispatchers with FloodWait Protection
# ==============================================================================
async def send_amazon_deal_with_retry(job: dict):
    """Converts Amazon links and posts the deal to user's Telegram channel."""
    global my_channel_entity, aiohttp_session

    if not my_channel_entity:
        logger.warning("Amazon deal skipped: MY_TELEGRAM_CHANNEL is not configured.")
        return

    event = job["event"]
    amazon_urls = job["amazon_urls"]
    channel_name = job.get("channel_name", "Unknown")

    logger.info("Converting %d Amazon URL(s) for your channel...", len(amazon_urls))

    try:
        converted_text, updated_entities, url_map = await prepare_amazon_message(
            event.message,
            amazon_urls,
            config.AMAZON_AFFILIATE_TAG,
            session=aiohttp_session,
        )
    except Exception as conv_err:
        logger.error("Failed to convert Amazon URLs: %s", conv_err)
        converted_text = event.message.text or event.message.message or ""
        updated_entities = event.message.entities or []

    for orig, conv in url_map.items():
        logger.info("  ↳ %s  =>  %s", orig, conv)

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            logger.info("Posting converted Amazon deal to [%s]...", config.MY_TELEGRAM_CHANNEL)

            # Option A: Send full message with media if present
            if config.FORWARD_FULL_MESSAGE:
                if event.message.media:
                    # Telegram photo/media caption limit is 1024 characters
                    if len(converted_text) <= 1024:
                        try:
                            await client.send_message(
                                my_channel_entity,
                                converted_text,
                                file=event.message.media,
                                formatting_entities=updated_entities,
                            )
                        except Exception as caption_err:
                            err_str = str(caption_err).lower()
                            if "caption is too long" in err_str:
                                logger.warning("Caption exceeded limit on Telegram server. Splitting into media + text message...")
                                await client.send_message(my_channel_entity, file=event.message.media)
                                await client.send_message(
                                    my_channel_entity,
                                    converted_text,
                                    formatting_entities=updated_entities,
                                    link_preview=False,
                                )
                            elif "file reference has expired" in err_str or "filereference" in err_str:
                                logger.warning("Media file reference expired. Posting converted deal text without media...")
                                await client.send_message(
                                    my_channel_entity,
                                    converted_text,
                                    formatting_entities=updated_entities,
                                    link_preview=True,
                                )
                            else:
                                raise caption_err
                    else:
                        # Caption is > 1024 chars: send media first, then full text (up to 4096 chars)
                        logger.info(
                            "Message length (%d chars) exceeds 1024-char media caption limit. Sending media first, then text...",
                            len(converted_text),
                        )
                        try:
                            await client.send_message(my_channel_entity, file=event.message.media)
                        except Exception as m_err:
                            if "file reference has expired" in str(m_err).lower():
                                logger.warning("Media file reference expired. Skipping media attachment.")
                        await client.send_message(
                            my_channel_entity,
                            converted_text,
                            formatting_entities=updated_entities,
                            link_preview=False,
                        )
                else:
                    await client.send_message(
                        my_channel_entity,
                        converted_text,
                        formatting_entities=updated_entities,
                        link_preview=True,
                    )
            # Option B: Send only the converted clean links
            else:
                links_text = "\n".join(url_map.values())
                await client.send_message(
                    my_channel_entity,
                    links_text,
                    link_preview=True,
                )

            logger.info("✓ Successfully posted Amazon deal to your channel!")
            stats["amazon_deals"] += 1
            stats["last_deal_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            stats["last_deal_title"] = f"Amazon deal from [{channel_name}]"
            return

        except FloodWaitError as flood_err:
            wait_time = flood_err.seconds + 2
            logger.warning(
                "Telegram FloodWaitError encountered! Sleeping for %d seconds...",
                wait_time,
            )
            await asyncio.sleep(wait_time)

        except Exception as send_err:
            logger.error(
                "Attempt %d/%d failed while sending Amazon deal to channel: %s",
                attempt,
                max_retries,
                send_err,
            )
            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)
            else:
                logger.error("Max retries reached. Dropping Amazon message.")


async def send_extrape_deal_with_retry(job: dict):
    """Sends non-Amazon deal links to ExtraPe Bot for affiliate conversion."""
    global target_bot_entity
    event = job["event"]
    deal_urls = job.get("deal_urls", [])
    channel_name = job.get("channel_name", "Unknown")

    if config.FORWARD_FULL_MESSAGE:
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                logger.info("Sending full message + media to ExtraPe (%s)...", config.TARGET_BOT)
                await client.send_message(target_bot_entity, event.message)
                logger.info("✓ Successfully sent deal to ExtraPe (%s).", config.TARGET_BOT)
                stats["extrape_deals"] += 1
                stats["last_deal_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                stats["last_deal_title"] = f"Deal from [{channel_name}]"
                return

            except FloodWaitError as flood_err:
                wait_time = flood_err.seconds + 2
                logger.warning("Telegram FloodWaitError: sleeping %d seconds...", wait_time)
                await asyncio.sleep(wait_time)

            except Exception as send_err:
                err_str = str(send_err).lower()
                logger.error("Attempt %d/%d failed sending to ExtraPe: %s", attempt, max_retries, send_err)
                if "file reference has expired" in err_str or "filereference" in err_str:
                    logger.warning("Media file reference expired. Falling back to sending message text/clean links...")
                    try:
                        text_to_send = event.message.text or ""
                        if not text_to_send and deal_urls:
                            text_to_send = "\n".join(deal_urls)
                        if text_to_send:
                            await client.send_message(target_bot_entity, text_to_send, link_preview=False)
                            logger.info("✓ Successfully sent deal text to ExtraPe (media skipped).")
                            stats["extrape_deals"] += 1
                            stats["last_deal_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                            stats["last_deal_title"] = f"Deal from [{channel_name}] (text fallback)"
                            return
                    except Exception as fallback_err:
                        logger.error("Fallback text send to ExtraPe also failed: %s", fallback_err)

                if attempt < max_retries:
                    await asyncio.sleep(2 * attempt)
                else:
                    logger.error("Max retries reached for ExtraPe message.")
    else:
        # Send clean individual links
        for url in deal_urls:
            max_retries = 3
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info("Sending link to ExtraPe: %s", url)
                    await client.send_message(
                        target_bot_entity,
                        url,
                        link_preview=False,
                    )
                    logger.info("✓ Delivered link to ExtraPe: %s", url)
                    stats["extrape_deals"] += 1
                    stats["last_deal_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                    stats["last_deal_title"] = f"Deal link from [{channel_name}]"
                    break
                except FloodWaitError as flood_err:
                    wait_time = flood_err.seconds + 2
                    logger.warning("FloodWait: sleeping %d seconds...", wait_time)
                    await asyncio.sleep(wait_time)
                except Exception as send_err:
                    logger.error("Attempt %d/%d failed sending URL to ExtraPe: %s", attempt, max_retries, send_err)
                    if attempt < max_retries:
                        await asyncio.sleep(2 * attempt)

            if len(deal_urls) > 1:
                await asyncio.sleep(random.uniform(1.0, 2.0))


# ==============================================================================
# Queue Worker for Rate Limiting & Safe Delivery
# ==============================================================================
async def queue_worker():
    """Worker task that processes incoming jobs sequentially.

    Ensures safe random delays, handles FloodWaitError, and prevents race
    conditions when multiple channels post deals simultaneously.
    """
    logger.info("Message processing worker started.")

    while True:
        job = await message_queue.get()
        try:
            job_type = job.get("type")
            channel_name = job.get("channel_name", "Unknown")

            if job_type == "AMAZON_CHANNEL":
                logger.info("--- Dispatching Amazon Deal from [%s] to your channel ---", channel_name)
                await send_amazon_deal_with_retry(job)

            elif job_type == "EXTRAPE_BOT":
                logger.info("--- Dispatching Non-Amazon Deal from [%s] to ExtraPe ---", channel_name)
                await send_extrape_deal_with_retry(job)

            # Randomized delay between dispatches to emulate human pacing and evade spam flags
            pacing_delay = random.uniform(config.MIN_DELAY, config.MAX_DELAY)
            logger.info("Pacing delay: waiting %.2f seconds before next dispatch...\n", pacing_delay)
            await asyncio.sleep(pacing_delay)

        except asyncio.CancelledError:
            logger.info("Queue worker received cancellation.")
            break
        except Exception as exc:
            logger.error("Unexpected error in queue worker: %s", exc, exc_info=True)
        finally:
            message_queue.task_done()


# ==============================================================================
# Real-Time Event Listener
# ==============================================================================
@client.on(events.NewMessage(chats=config.SOURCE_CHANNELS))
async def handle_new_deal(event: events.NewMessage.Event):
    """Event handler triggered on every incoming message in the monitored channels."""
    global current_user

    # 1. Ignore outgoing messages sent by the userbot account itself
    if event.out:
        return

    # 2. Ignore messages sent by other bots (if present in groups/supergroups)
    sender = await event.get_sender()
    if isinstance(sender, User) and sender.bot:
        logger.debug("Skipping message from bot: @%s", sender.username or sender.id)
        return

    # 3. Guard against empty messages
    if not event.text and not event.message.media:
        return

    chat = await event.get_chat()
    chat_title = getattr(chat, "title", None) or getattr(chat, "username", None) or str(event.chat_id)

    # 4. Extract URLs to identify Amazon deals
    raw_urls = extract_deal_urls(event.message, filter_domains=False)
    amazon_urls = [u for u in raw_urls if is_amazon_url(u)]

    # Route A: Amazon Deals -> Convert to your tag & post to your channel (@trendiloots)
    if amazon_urls:
        logger.info("Detected %d Amazon link(s) in [%s]. Routing to your channel (%s).", len(amazon_urls), chat_title, config.MY_TELEGRAM_CHANNEL)
        if config.MY_TELEGRAM_CHANNEL:
            await message_queue.put(
                {
                    "type": "AMAZON_CHANNEL",
                    "event": event,
                    "amazon_urls": amazon_urls,
                    "channel_name": chat_title,
                }
            )
        else:
            logger.warning(
                "Amazon deal found in [%s], but MY_TELEGRAM_CHANNEL is not set in .env! "
                "Set MY_TELEGRAM_CHANNEL to receive converted Amazon deals.",
                chat_title,
            )

        # Do not send Amazon deals to ExtraPe (as Amazon is not eligible on ExtraPe)
        logger.info("Filtered out Amazon deal from ExtraPe bot.")

    # Route B: Rest all messages (Non-Amazon deals: Flipkart, Myntra, Ajio, etc.) -> Forward to ExtraPe
    else:
        logger.info("Non-Amazon message from [%s]. Forwarding to ExtraPe bot (%s).", chat_title, config.TARGET_BOT)
        await message_queue.put(
            {
                "type": "EXTRAPE_BOT",
                "event": event,
                "deal_urls": raw_urls,
                "channel_name": chat_title,
            }
        )


# ==============================================================================
# Startup Verification & Entity Resolution
# ==============================================================================
async def initialize():
    """Initializes and verifies Telegram session, channels, and bot entities."""
    global target_bot_entity, my_channel_entity, current_user, aiohttp_session

    logger.info("=" * 60)
    logger.info("Initializing Telegram Deal Forwarder...")
    logger.info("=" * 60)

    # Validate environment configuration
    if not config.validate_config():
        sys.exit(1)

    # Shared aiohttp session for redirect resolution
    connector = aiohttp.TCPConnector(ssl=False)
    aiohttp_session = aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=10),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )

    # Connect client
    await client.connect()

    # Authenticate if session not saved
    if not await client.is_user_authorized():
        if os.getenv("PORT") or os.getenv("RENDER"):
            err_msg = (
                "CRITICAL: Telegram client is not authorized on Render! "
                "Cloud containers cannot prompt for SMS/login codes interactively. "
                "You must set the TELEGRAM_STRING_SESSION environment variable in your Render Dashboard. "
                "Run 'python3 export_session.py' on your local Mac to copy your StringSession."
            )
            logger.fatal(err_msg)
            stats["status"] = "Unauthorized (Missing TELEGRAM_STRING_SESSION)"
            stats["error"] = err_msg
            return False

        logger.info("Client is not authorized. Starting interactive authentication...")
        phone = config.PHONE_NUMBER or input("Enter your Telegram phone number (international format): ").strip()
        await client.start(phone=phone)

    current_user = await client.get_me()
    stats["telegram_connected"] = True
    stats["status"] = "Online (Active 24/7)"
    user_display = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip()
    stats["user"] = f"{user_display} (@{current_user.username or 'N/A'} | ID: {current_user.id})"
    logger.info(
        "Logged in as: %s %s (@%s | ID: %d)",
        current_user.first_name or "",
        current_user.last_name or "",
        current_user.username or "N/A",
        current_user.id,
    )

    # Resolve ExtraPe Bot
    logger.info("Resolving ExtraPe bot entity: %s", config.TARGET_BOT)
    try:
        target_bot_entity = await client.get_input_entity(config.TARGET_BOT)
        bot_user = await client.get_entity(target_bot_entity)
        logger.info(
            "  ✓ ExtraPe Bot resolved: %s (@%s | ID: %d)",
            bot_user.first_name,
            bot_user.username,
            bot_user.id,
        )
    except Exception as exc:
        logger.error("Failed to resolve target bot '%s': %s", config.TARGET_BOT, exc)
        stats["error"] = f"Failed to resolve target bot '{config.TARGET_BOT}': {exc}"
        return False

    # Resolve User's Amazon Telegram Channel (if configured)
    if config.MY_TELEGRAM_CHANNEL:
        logger.info("Resolving your Telegram channel: %s", config.MY_TELEGRAM_CHANNEL)
        try:
            my_channel_entity = await client.get_input_entity(config.MY_TELEGRAM_CHANNEL)
            my_chan_obj = await client.get_entity(my_channel_entity)
            chan_title = getattr(my_chan_obj, "title", None) or getattr(my_chan_obj, "username", None) or str(my_chan_obj.id)
            logger.info("  ✓ Your channel resolved: %s (ID: %s)", chan_title, my_chan_obj.id)
        except Exception as exc:
            logger.error(
                "Failed to resolve MY_TELEGRAM_CHANNEL '%s'. Ensure the username or ID is correct and your account is an admin/member: %s",
                config.MY_TELEGRAM_CHANNEL,
                exc,
            )
            logger.warning("Amazon deals will NOT be posted to your channel until this is resolved.")
            my_channel_entity = None
    else:
        logger.info("MY_TELEGRAM_CHANNEL is not set. Converted Amazon deals will not be posted.")

    # Verify and summarize Source Channels
    logger.info("Resolving %d configured source channel(s)...", len(config.SOURCE_CHANNELS))
    resolved_channels = []
    for ch in config.SOURCE_CHANNELS:
        try:
            entity = await client.get_entity(ch)
            title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(entity.id)
            resolved_channels.append(title)
            logger.info("  ✓ Active source channel: %s (ID: %s)", title, entity.id)
        except Exception as exc:
            logger.warning("  ✗ Warning: Could not resolve channel '%s': %s", ch, exc)

    stats["source_channels"] = resolved_channels

    logger.info("Configuration Summary:")
    logger.info("  - Forward Full Message: %s", config.FORWARD_FULL_MESSAGE)
    logger.info("  - Amazon Affiliate Tag: %s", config.AMAZON_AFFILIATE_TAG or "[NOT CONFIGURED]")
    logger.info("  - My Channel Destination: %s", config.MY_TELEGRAM_CHANNEL or "[NOT CONFIGURED]")
    logger.info("  - Send Amazon to ExtraPe: %s (Filtered out by default)", config.SEND_AMAZON_TO_EXTRAPE)
    logger.info("  - ExtraPe Bot Destination: %s", config.TARGET_BOT)
    logger.info("  - Dispatch Pacing: %.1f - %.1f seconds", config.MIN_DELAY, config.MAX_DELAY)
    logger.info("  - Monitored Source Channels: %s", resolved_channels)
    logger.info("=" * 60)
    logger.info("Listening for deals... Press Ctrl+C to stop.")
    return True


from aiohttp import web

async def start_health_check_server():
    """Starts a lightweight HTTP server on $PORT for cloud health checks (Render) and uptime monitoring."""
    port_str = os.getenv("PORT")
    if not port_str:
        return None  # Running locally on Mac, no HTTP server needed

    port = int(port_str)
    app = web.Application()

    async def handle_ping(request):
        # JSON format if explicitly requested
        if request.headers.get("Accept") == "application/json" or request.query.get("format") == "json":
            return web.json_response({"status": "ok", "stats": stats})

        # Modern HTML status dashboard
        is_online = stats["status"].startswith("Online")
        status_color = "#10b981" if is_online else ("#f59e0b" if stats["status"] == "Starting" else "#ef4444")
        status_badge = "ACTIVE 24/7" if is_online else ("STARTING" if stats["status"] == "Starting" else "ATTENTION REQUIRED")

        channel_list = stats.get("source_channels") or config.SOURCE_CHANNELS
        channels_html = "".join(f"<span class='tag'>{ch}</span>" for ch in channel_list) if channel_list else "<span style='color:#94a3b8;'>None</span>"

        error_box = f"<div class='alert'><strong>Action Required:</strong> {stats['error']}</div>" if stats.get("error") else ""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram Deal Forwarder - Status</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
        body {{ background: #0f172a; color: #f8fafc; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 16px; padding: 32px; max-width: 640px; width: 100%; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); }}
        .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #334155; }}
        .title {{ font-size: 20px; font-weight: 700; color: #38bdf8; display: flex; align-items: center; gap: 10px; }}
        .badge {{ background: {status_color}22; color: {status_color}; border: 1px solid {status_color}; padding: 4px 12px; border-radius: 9999px; font-size: 12px; font-weight: 700; letter-spacing: 0.5px; display: inline-flex; align-items: center; gap: 6px; }}
        .badge::before {{ content: ''; width: 8px; height: 8px; background: {status_color}; border-radius: 50%; box-shadow: 0 0 8px {status_color}; }}
        .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin-bottom: 24px; }}
        .stat-box {{ background: #0f172a; border: 1px solid #334155; border-radius: 12px; padding: 16px; }}
        .stat-label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; font-weight: 600; margin-bottom: 6px; }}
        .stat-val {{ font-size: 24px; font-weight: 700; color: #f1f5f9; }}
        .info-row {{ margin-bottom: 14px; font-size: 14px; color: #cbd5e1; display: flex; justify-content: space-between; gap: 12px; }}
        .info-label {{ color: #94a3b8; font-weight: 500; flex-shrink: 0; }}
        .tag {{ background: #0284c7; color: #fff; padding: 3px 10px; border-radius: 6px; font-size: 12px; margin-right: 6px; margin-top: 6px; display: inline-block; }}
        .alert {{ background: #ef444422; border: 1px solid #ef4444; border-radius: 10px; padding: 14px; margin-bottom: 20px; color: #fca5a5; font-size: 13px; line-height: 1.5; }}
        .footer {{ text-align: center; font-size: 12px; color: #64748b; margin-top: 24px; border-top: 1px solid #334155; padding-top: 16px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <div class="title">⚡ Telegram Deal Forwarder</div>
            <span class="badge">{status_badge}</span>
        </div>
        {error_box}
        <div class="grid">
            <div class="stat-box">
                <div class="stat-label">Amazon Deals Sent</div>
                <div class="stat-val">{stats['amazon_deals']}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">ExtraPe Deals Sent</div>
                <div class="stat-val">{stats['extrape_deals']}</div>
            </div>
        </div>
        <div class="info-row">
            <span class="info-label">Telegram Account:</span>
            <span>{stats.get('user') or 'Connecting...'}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Target Channel (Amazon):</span>
            <span style="color: #38bdf8; font-weight: 600;">{stats['target_channel']}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Target Bot (ExtraPe):</span>
            <span style="color: #a78bfa; font-weight: 600;">{stats['target_bot']}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Last Deal Processed:</span>
            <span>{stats.get('last_deal_at') or 'Waiting for new deals...'}</span>
        </div>
        <div style="margin-top: 14px;">
            <div class="info-label" style="margin-bottom: 6px;">Monitored Source Channels:</div>
            <div>{channels_html}</div>
        </div>
        <div class="footer">
            UptimeRobot Keep-Alive: OK (HTTP 200) • Powered by Telethon & Render
        </div>
    </div>
</body>
</html>"""
        return web.Response(text=html, content_type="text/html", status=200)

    async def handle_health(request):
        status_code = 200 if stats["status"].startswith("Online") or stats["status"] == "Starting" else 503
        return web.json_response({"status": stats["status"], "stats": stats}, status=status_code)

    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/status", handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health-check web server running on port %d for Render & UptimeRobot.", port)
    return runner


# ==============================================================================
# Main Lifecycle Runner
# ==============================================================================
async def main():
    stats["uptime_start"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 1. Start health-check server FIRST so Render immediately detects port binding on $PORT
    #    and UptimeRobot gets 200 OK without waiting on Telegram resolution.
    web_runner = await start_health_check_server()

    # 2. Start the rate-limited dispatch worker in the background
    worker_task = asyncio.create_task(queue_worker())

    is_initialized = False
    try:
        # 3. Connect and initialize Telegram
        is_initialized = await initialize()
        if is_initialized:
            logger.info("Forwarder successfully initialized. Listening for deals 24/7...")
            # Keep client listening until disconnected
            await client.run_until_disconnected()
        else:
            logger.error("Telegram initialization failed. Web server will stay alive for diagnostics.")
            # Keep web server active so Render does not crash-loop, allowing the user to view diagnostics
            while True:
                await asyncio.sleep(3600)
    finally:
        logger.info("Shutting down worker task...")
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
        if web_runner:
            await web_runner.cleanup()
        if aiohttp_session and not aiohttp_session.closed:
            await aiohttp_session.close()
        if is_initialized:
            await client.disconnect()
        logger.info("Telegram client disconnected cleanly.")


if __name__ == "__main__":
    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Forwarder stopped by user (KeyboardInterrupt).")
    except Exception as e:
        logger.fatal("Fatal runtime error: %s", e, exc_info=True)

