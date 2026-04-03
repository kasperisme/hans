#!/usr/bin/env python3
"""
Hans Telegram Bot - Home Automation Assistant

Listens for commands from whitelisted users and triggers Claude Code
to orchestrate home automation tasks.
"""

import os
import subprocess
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from logging_config import setup_logging

load_dotenv()

log = setup_logging("hans.bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = [
    int(uid.strip())
    for uid in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
]


def is_authorized(user_id: int) -> bool:
    """Check if user is in the whitelist."""
    return user_id in ALLOWED_USER_IDS


def get_user_info(update: Update) -> str:
    """Get formatted user info for logging."""
    user = update.effective_user
    return f"{user.username or user.first_name}({user.id})"


async def run_claude_code(prompt: str) -> str:
    """Run Claude Code in non-interactive mode and return output."""
    log.debug("Executing Claude Code with prompt: %s...", prompt[:100])

    try:
        process = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            log.error("Claude Code failed: %s", stderr.decode())
            return f"Error: {stderr.decode()}"

        output = stdout.decode()
        log.debug("Claude Code output: %s chars", len(output))
        return output
    except Exception as e:
        log.exception("Failed to run Claude Code")
        return f"Failed to run Claude Code: {e}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user_info = get_user_info(update)

    if not is_authorized(update.effective_user.id):
        log.warning("Unauthorized /start from %s", user_info)
        await update.message.reply_text("Unauthorized.")
        return

    log.info("User %s started bot", user_info)
    await update.message.reply_text(
        "Hej! Jeg er Hans, din hjemmeautomatiserings-assistent.\n\n"
        "Kommandoer:\n"
        "/order - Bestil varer fra indkøbslisten\n"
        "/list - Vis indkøbslisten\n"
        "/status - Tjek systemstatus"
    )


async def order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /order command - trigger grocery ordering."""
    user_info = get_user_info(update)

    if not is_authorized(update.effective_user.id):
        log.warning("Unauthorized /order from %s", user_info)
        await update.message.reply_text("Unauthorized.")
        return

    log.info("User %s triggered /order", user_info)
    await update.message.reply_text("Starter bestilling... Dette kan tage et par minutter.")

    prompt = """
    Execute the grocery ordering workflow:
    1. Run `python skills/read_todoist.py` to get items from the "Indkøb" list
    2. Pipe that JSON into `python skills/order_nemlig.py` (stdin) to search nemlig.com and add each line to the basket via the web API
    3. Pipe the JSON from step 2 into `python skills/confirm_order.py` to format the result

    Return a summary of what was added to the basket and the cart total, or any errors encountered.
    """

    result = await run_claude_code(prompt)
    log.info("Order completed for %s, result length: %d", user_info, len(result))

    # Truncate if too long for Telegram (max 4096 chars)
    if len(result) > 4000:
        result = result[:4000] + "\n... (truncated)"

    await update.message.reply_text(result)


async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /list command - show current shopping list."""
    user_info = get_user_info(update)

    if not is_authorized(update.effective_user.id):
        log.warning("Unauthorized /list from %s", user_info)
        await update.message.reply_text("Unauthorized.")
        return

    log.info("User %s requested /list", user_info)
    await update.message.reply_text("Henter indkøbsliste...")

    prompt = """
    Run `python skills/read_todoist.py` and format the output as a readable shopping list.
    Show each item with a checkbox emoji.
    """

    result = await run_claude_code(prompt)
    log.debug("List fetched for %s: %d chars", user_info, len(result))

    if len(result) > 4000:
        result = result[:4000] + "\n... (truncated)"

    await update.message.reply_text(result)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command - check system status."""
    user_info = get_user_info(update)

    if not is_authorized(update.effective_user.id):
        log.warning("Unauthorized /status from %s", user_info)
        await update.message.reply_text("Unauthorized.")
        return

    log.info("User %s requested /status", user_info)

    # Quick local status check
    checks = []

    # Check .env exists
    env_exists = os.path.exists(".env")
    checks.append(f"{'OK' if env_exists else 'FAIL'} .env file")

    # Check skills exist
    skills = ["read_todoist.py", "order_nemlig.py", "confirm_order.py"]
    nemlig_api = os.path.exists("nemlig_api/client.py")
    checks.append(f"{'OK' if nemlig_api else 'FAIL'} nemlig_api/client.py")
    for skill in skills:
        exists = os.path.exists(f"skills/{skill}")
        checks.append(f"{'OK' if exists else 'FAIL'} skills/{skill}")

    # Check claude CLI available
    try:
        result = subprocess.run(["which", "claude"], capture_output=True)
        claude_ok = result.returncode == 0
    except Exception:
        claude_ok = False
    checks.append(f"{'OK' if claude_ok else 'FAIL'} claude CLI")

    status_text = "System Status:\n" + "\n".join(checks)
    log.debug("Status check: %s", checks)
    await update.message.reply_text(status_text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any text message - pass to Claude Code."""
    user_info = get_user_info(update)

    if not is_authorized(update.effective_user.id):
        log.warning("Unauthorized message from %s", user_info)
        await update.message.reply_text("Unauthorized.")
        return

    message = update.message.text
    log.info("User %s sent message: %s", user_info, message[:50])

    result = await run_claude_code(message)

    if len(result) > 4000:
        result = result[:4000] + "\n... (truncated)"

    await update.message.reply_text(result)


def main() -> None:
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set in .env")
        return

    if not ALLOWED_USER_IDS:
        log.warning("No TELEGRAM_ALLOWED_USER_IDS configured - all users will be rejected")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("order", order))
    application.add_handler(CommandHandler("list", show_list))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Hans bot starting with %d authorized users", len(ALLOWED_USER_IDS))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
