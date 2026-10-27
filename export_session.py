#!/usr/bin/env python3
"""Export StringSession from existing extrape_userbot.session file.
Use this string in your cloud deployment (Render, Railway, Heroku, VPS).
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
import config

async def export():
    print("=" * 60)
    print("Exporting Telethon StringSession...")
    print("=" * 60)

    client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        print("Error: Local session is not authorized. Please run forwarder.py locally first.")
        await client.disconnect()
        return

    me = await client.get_me()
    session_string = StringSession.save(client.session)
    await client.disconnect()

    print(f"Logged in as: {me.first_name} (Phone: {me.phone})")
    print("\nCopy the following StringSession and paste it into Render Environment Variables:")
    print("Key:   TELEGRAM_STRING_SESSION")
    print(f"Value: {session_string}\n")
    print("=" * 60)

    # Offer to save into local .env if not present
    env_path = ".env"
    with open(env_path, "r", encoding="utf-8") as f:
        env_content = f.read()

    if "TELEGRAM_STRING_SESSION=" not in env_content:
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\n# Cloud deployment StringSession\nTELEGRAM_STRING_SESSION={session_string}\n")
        print("✓ Automatically appended TELEGRAM_STRING_SESSION to your local .env file.")
    else:
        print("Note: TELEGRAM_STRING_SESSION is already defined in your local .env file.")

if __name__ == "__main__":
    asyncio.run(export())
