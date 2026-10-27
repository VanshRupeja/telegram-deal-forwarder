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
import logging
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
                            if "caption is too long" in str(caption_err).lower():
                                logger.warning("Caption exceeded limit on Telegram server. Splitting into media + text message...")
                                await client.send_message(my_channel_entity, file=event.message.media)
                                await client.send_message(
                                    my_channel_entity,
                                    converted_text,
                                    formatting_entities=updated_entities,
                                    link_preview=False,
                                )
                            else:
                                raise caption_err
                    else:
                        # Caption is > 1024 chars: send media first, then full text (up to 4096 chars)
                        logger.info(
                            "Message length (%d chars) exceeds 1024-char media caption limit. Sending media first, then text...",
                            len(converted_text),
                        )
                        await client.send_message(my_channel_entity, file=event.message.media)
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
    deal_urls = job["deal_urls"]

    if config.FORWARD_FULL_MESSAGE:
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                logger.info("Sending full message + media to ExtraPe (%s)...", config.TARGET_BOT)
                await client.send_message(target_bot_entity, event.message)
                logger.info("✓ Successfully sent deal to ExtraPe (%s).", config.TARGET_BOT)
                return

            except FloodWaitError as flood_err:
                wait_time = flood_err.seconds + 2
                logger.warning("Telegram FloodWaitError: sleeping %d seconds...", wait_time)
                await asyncio.sleep(wait_time)

            except Exception as send_err:
                logger.error("Attempt %d/%d failed sending to ExtraPe: %s", attempt, max_retries, send_err)
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
        logger.info("Client is not authorized. Starting interactive authentication...")
        phone = config.PHONE_NUMBER or input("Enter your Telegram phone number (international format): ").strip()
        await client.start(phone=phone)

    current_user = await client.get_me()
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
        sys.exit(1)

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


from aiohttp import web

async def start_health_check_server():
    """Starts a lightweight HTTP server on $PORT for cloud health checks (Render) and uptime monitoring."""
    port_str = os.getenv("PORT")
    if not port_str:
        return None  # Running locally on Mac, no HTTP server needed

    port = int(port_str)
    app = web.Application()

    async def handle_ping(request):
        return web.Response(text="Telegram Deal Forwarder is active and running 24/7!", status=200)

    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health-check web server running on port %d for Render.", port)
    return runner


# ==============================================================================
# Main Lifecycle Runner
# ==============================================================================
async def main():
    await initialize()

    # Start health-check server if deployed on cloud (Render sets $PORT)
    web_runner = await start_health_check_server()

    # Start the rate-limited dispatch worker in the background
    worker_task = asyncio.create_task(queue_worker())

    # Keep client listening until disconnected
    try:
        await client.run_until_disconnected()
    finally:
        logger.info("Shutting down worker task...")
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
        if web_runner:
            await web_runner.cleanup()
        if aiohttp_session and not aiohttp_session.closed:
            await aiohttp_session.close()
        await client.disconnect()
        logger.info("Telegram client disconnected cleanly.")


if __name__ == "__main__":
    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Forwarder stopped by user (KeyboardInterrupt).")
    except Exception as e:
        logger.fatal("Fatal runtime error: %s", e, exc_info=True)
