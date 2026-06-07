import os
import re
import time
import math
import asyncio
import sqlite3
import requests
from datetime import datetime
from flask import Flask
from threading import Thread
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestUsers,
    KeyboardButtonRequestChat,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

ADMIN_ID = 8300271033

NUMBER_API_URL = "https://ayush-multi-apiv2.onrender.com/num?q={number}"
NUMBER_API_URL2 = "https://divyansh.store/num-info?key=Sinc&number={number}"
AADHAR_API_URL = "https://ayush-multi-apiv2.onrender.com/adhar?q={aadhar}"
VEH_API_URL = "https://ayush-multi-apiv2.onrender.com/veh?q={veh}"
TG_LOOKUP_API = "https://api.subhxcosmo.in/api?key=RACKSUN&type=tg&term={term}"

CHANNEL_USERNAME = "@racksun19"
CHANNEL_LINK = "https://t.me/racksun19"
GROUP_USERNAME = "@racksungroup"
GROUP_LINK = "https://t.me/racksungroup"

COOLDOWN_SECONDS = 1

maintenance_mode = False
user_last_request = {}

DB_FILE = "bot.db"


FREE_NUM_LIMIT = 15
FREE_TG_LIMIT = 10
FREE_VEH_LIMIT = 5


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id           INTEGER PRIMARY KEY,
            first_name        TEXT,
            username          TEXT,
            join_date         TEXT,
            search_count      INTEGER DEFAULT 0,
            is_premium        INTEGER DEFAULT 0,
            premium_expiry    TEXT DEFAULT '',
            num_searches_today  INTEGER DEFAULT 0,
            tg_searches_today   INTEGER DEFAULT 0,
            last_search_date  TEXT DEFAULT ''
        )
    """)
    for col, default in [
        ("is_premium",            "0"),
        ("premium_expiry",        "''"),
        ("num_searches_today",    "0"),
        ("tg_searches_today",     "0"),
        ("aadhar_searches_today", "0"),
        ("veh_searches_today",    "0"),
        ("last_search_date",      "''"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT {default}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def track_user(user_id, first_name=None, username=None):
    if not user_id:
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        join_date = datetime.now().strftime("%d %b %Y")
        c.execute(
            "INSERT INTO users (user_id, first_name, username, join_date) VALUES (?,?,?,?)",
            (user_id, first_name or "", username or "", join_date),
        )
    else:
        c.execute(
            "UPDATE users SET first_name=?, username=? WHERE user_id=?",
            (first_name or "", username or "", user_id),
        )
    conn.commit()
    conn.close()


def increment_search(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET search_count = search_count + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_user_info_db(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id, first_name, username, join_date, search_count FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def get_stats_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT SUM(search_count) FROM users")
    searches = c.fetchone()[0] or 0
    today = datetime.now().strftime("%d %b %Y")
    c.execute("SELECT COUNT(*) FROM users WHERE join_date=?", (today,))
    today_joined = c.fetchone()[0]
    conn.close()
    return total, searches, today_joined


def get_all_user_ids_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


def is_admin(user_id):
    return user_id == ADMIN_ID


async def check_admin(update, context):
    user_id = update.effective_user.id
    chat = update.effective_chat
    if chat and chat.type in ("group", "supergroup"):
        try:
            member = await context.bot.get_chat_member(chat.id, user_id)
            if member.status in ("administrator", "creator"):
                return True
        except Exception:
            pass
    return is_admin(user_id)


def add_premium_db(user_id, days):
    from datetime import timedelta
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT premium_expiry FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    today = datetime.now()
    if row and row[0]:
        try:
            existing = datetime.strptime(row[0], "%d %b %Y")
            if existing > today:
                base = existing
            else:
                base = today
        except Exception:
            base = today
    else:
        base = today
    expiry = (base + timedelta(days=days)).strftime("%d %b %Y")
    c.execute(
        "UPDATE users SET is_premium=1, premium_expiry=? WHERE user_id=?",
        (expiry, user_id),
    )
    conn.commit()
    conn.close()
    return expiry


def remove_premium_db(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET is_premium=0, premium_expiry='' WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def is_premium_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT is_premium, premium_expiry FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row or not row[0]:
        return False
    if row[1]:
        try:
            expiry = datetime.strptime(row[1], "%d %b %Y")
            if datetime.now() > expiry:
                conn2 = sqlite3.connect(DB_FILE)
                c2 = conn2.cursor()
                c2.execute("UPDATE users SET is_premium=0, premium_expiry='' WHERE user_id=?", (user_id,))
                conn2.commit()
                conn2.close()
                return False
        except Exception:
            pass
    return True


def get_premium_expiry(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT premium_expiry FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else ""


def get_premium_list_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id, first_name, username, premium_expiry FROM users WHERE is_premium=1")
    rows = c.fetchall()
    conn.close()
    return rows


def get_premium_count_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE is_premium=1")
    count = c.fetchone()[0]
    conn.close()
    return count


def check_and_reset_daily(user_id):
    today = datetime.now().strftime("%d %b %Y")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT last_search_date FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row and row[0] != today:
        c.execute(
            "UPDATE users SET num_searches_today=0, tg_searches_today=0, aadhar_searches_today=0, veh_searches_today=0, last_search_date=? WHERE user_id=?",
            (today, user_id),
        )
        conn.commit()
    elif row and not row[0]:
        c.execute("UPDATE users SET last_search_date=? WHERE user_id=?", (today, user_id))
        conn.commit()
    conn.close()


def get_daily_counts(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT num_searches_today, tg_searches_today, aadhar_searches_today FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return (row[0] or 0, row[1] or 0, row[2] or 0) if row else (0, 0, 0)


def increment_num_daily(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET num_searches_today = num_searches_today + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def increment_tg_daily(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET tg_searches_today = tg_searches_today + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_daily_aadhar_count(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT aadhar_searches_today FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] or 0 if row else 0


def increment_aadhar_daily(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET aadhar_searches_today = aadhar_searches_today + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_daily_veh_count(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT veh_searches_today FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] or 0 if row else 0


def increment_veh_daily(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET veh_searches_today = veh_searches_today + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


async def resolve_target_id(update, context, args, with_reason=False):
    """
    Returns (target_id, reason, error_msg).
    Supports: reply to message, @username, numeric UID.
    If with_reason=True, remaining args after target are joined as reason.
    """
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id
        reason = " ".join(args) if (with_reason and args) else ""
        return target_id, reason, None

    if not args:
        return None, "", "no_args"

    first = args[0]

    if first.startswith("@"):
        try:
            chat = await context.bot.get_chat(first)
            target_id = chat.id
        except Exception:
            return None, "", "❌ *Username not found!*\n\n`" + first + "` — ye username galat hai ya private hai."
        reason = " ".join(args[1:]) if (with_reason and len(args) > 1) else ""
        return target_id, reason, None

    if first.lstrip("-").isdigit():
        target_id = int(first)
        reason = " ".join(args[1:]) if (with_reason and len(args) > 1) else ""
        return target_id, reason, None

    return None, "", "invalid"


def check_cooldown(user_id):
    now = time.time()
    if user_id in user_last_request:
        elapsed = now - user_last_request[user_id]
        if elapsed < COOLDOWN_SECONDS:
            remaining = math.ceil(COOLDOWN_SECONDS - elapsed)
            return False, max(1, remaining)
    user_last_request[user_id] = now
    return True, 0


async def fetch_json(url, timeout=8):
    loop = asyncio.get_event_loop()
    def _get():
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    return await loop.run_in_executor(None, _get)


def clean_address(addr):
    if not addr:
        return "None"
    if "!" in addr:
        parts = []
        for p in addr.split("!"):
            p = p.strip()
            if p and p != ".":
                parts.append(p)
        if parts:
            return ", ".join(parts)
        return "None"
    cleaned = " ".join(addr.split())
    return cleaned if cleaned else "None"


def val(v):
    if v is None or str(v).strip() == "":
        return "None"
    return str(v).strip()


async def delete_msg(context, chat_id, msg_id):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass


async def log_error_to_admin(context, error_info):
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text="🐛 *Bot Error:*\n\n`" + str(error_info) + "`",
            parse_mode="Markdown",
        )
    except Exception:
        pass


flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot is Alive!"


def run_flask():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()


async def is_member(user_id, context):
    allowed = ["member", "administrator", "creator"]
    not_allowed = ["left", "kicked"]
    try:
        ch = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if ch.status not in allowed:
            return False
    except Exception:
        return False
    try:
        gr = await context.bot.get_chat_member(chat_id=GROUP_USERNAME, user_id=user_id)
        if gr.status in not_allowed:
            return False
    except Exception:
        pass
    return True


async def send_join_message(update, context):
    user = update.message.from_user
    first_name = user.first_name or "User"
    join_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton("👥 Join Group", url=GROUP_LINK)],
        [InlineKeyboardButton("✅ I have Joined", callback_data="check_joined")],
    ])
    text = (
        "⚠️ *Hello " + first_name + "!*\n\n"
        "Join our channel and group to use this bot.\n\n"
        "1️⃣ Join Channel: @racksun19\n"
        "2️⃣ Join Group: @racksungroup\n\n"
        "After joining both, click *I have Joined* button."
    )
    sent = await update.message.reply_text(text, reply_markup=join_button, parse_mode="Markdown")
    context.user_data["join_msg_id"] = sent.message_id


async def delete_join_message(context, chat_id):
    msg_id = context.user_data.get("join_msg_id")
    if not msg_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass
    context.user_data.pop("join_msg_id", None)
    await context.bot.send_message(
        chat_id=chat_id,
        text="✅ *You have successfully joined our channel!*\n\nYou can now use the bot freely. Send /start to begin.",
        parse_mode="Markdown",
    )


async def check_joined_callback(update, context):
    query = update.callback_query
    user = query.from_user
    track_user(user.id, user.first_name, user.username)
    member_ok = await is_member(user.id, context)
    if not member_ok:
        await query.answer("❌ You have not joined yet! Please join first.", show_alert=True)
        return
    await query.message.delete()
    context.user_data.pop("join_msg_id", None)
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="✅ *You have successfully joined our channel!*\n\nYou can now use the bot freely. Send /start to begin.",
        parse_mode="Markdown",
    )


def main_menu_markup():
    btn_user = KeyboardButton(text="User", request_users=KeyboardButtonRequestUsers(request_id=1, max_quantity=1))
    btn_group = KeyboardButton(text="Group", request_chat=KeyboardButtonRequestChat(request_id=2, chat_is_channel=False))
    btn_channel = KeyboardButton(text="Channel", request_chat=KeyboardButtonRequestChat(request_id=3, chat_is_channel=True))
    return ReplyKeyboardMarkup([[btn_user, btn_group, btn_channel]], resize_keyboard=True)


async def show_main_menu(update, context, header=None):
    user_id = update.message.from_user.id
    parts = []
    if header:
        parts.append(header + "\n\n")
    parts.append("*Welcome To @racksunbot*\n\n")
    parts.append("*Your ID :* `" + str(user_id) + "`\n\n")
    parts.append("Send me a Telegram username or number to look up.\n")
    parts.append("Example: @username or 1234567890\n\n")
    parts.append("Or use the buttons below to get User/Group/Channel ID:")
    await update.message.reply_text("".join(parts), reply_markup=main_menu_markup(), parse_mode="Markdown")


async def guard(update, context):
    """
    Common guard: returns True if user can proceed, False otherwise.
    Checks: maintenance mode, ban, channel membership, rate limit.
    """
    global maintenance_mode
    user = update.message.from_user
    user_id = user.id

    if maintenance_mode and user_id != ADMIN_ID:
        await update.message.reply_text(
            "🔧 *Bot is under maintenance.*\n\nPlease try again after some time.",
            parse_mode="Markdown",
        )
        return False

    track_user(user_id, user.first_name, user.username)

    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return False

    await delete_join_message(context, update.message.chat_id)
    return True


async def guard_with_cooldown(update, context):
    """Guard + rate limit check."""
    ok = await guard(update, context)
    if not ok:
        return False
    allowed, remaining = check_cooldown(update.message.from_user.id)
    if not allowed:
        await update.message.reply_text(
            "⏳ *Too fast!* Please wait *" + str(remaining) + " second(s)* before next request.",
            parse_mode="Markdown",
        )
        return False
    return True


async def start(update, context):
    if not await guard(update, context):
        return
    context.user_data.clear()
    await show_main_menu(update, context)


async def back_command(update, context):
    if not await guard(update, context):
        return
    await show_main_menu(update, context, header="🔙 *Back to main menu.*")


async def cancel_command(update, context):
    if not await guard(update, context):
        return
    context.user_data.clear()
    await show_main_menu(update, context, header="❌ *Cancelled.*")


async def settings_command(update, context):
    if not await guard(update, context):
        return
    settings_text = (
        "⚙️ *Settings*\n\n"
        "*What this bot can do:*\n\n"
        "📱 *Username / UID Lookup*\n"
        "Send any @username or numeric ID to get details instantly\n\n"
        "📞 *Phone Number Lookup*\n"
        "Use `/num <number>` to fetch name, address, circle, email\n\n"
        "🪪 *Aadhar Lookup*\n"
        "Use `/aadhar <12-digit number>` to fetch linked mobile, address, email\n\n"
        "🚗 *Vehicle Lookup*\n"
        "Use `/veh <plate number>` to fetch vehicle owner info\n\n"
        "👤 *Your Info*\n"
        "Use `/info` to see your own stats and profile\n\n"
        "👥 *User / Group / Channel ID*\n"
        "Use the buttons below to get IDs easily\n\n"
        "📝 *Report Issue*\n"
        "Use `/report <message>` to report any bot issue to admin\n\n"
        "⚡ *Fast and Automatic*\n"
        "No extra commands needed for basic lookups\n\n"
        "❓ *Help Guide*\n"
        "Use /help to see full instructions\n\n"
        "—\n\n"
        "⭐ *Want Premium?*\n"
        "Contact @racksunn for unlimited searches!\n\n"
        "_Thanks for using this bot._"
    )
    await update.message.reply_text(settings_text, parse_mode="Markdown")



async def help_command(update, context):
    if not await guard(update, context):
        return
    help_text = (
        "🤖 *Welcome to @racksunbot Help*\n\n"
        "Here is how to use this bot:\n\n"
        "📱 *Telegram Username / UID Lookup*\n"
        "  Just send the username or UID directly in chat.\n"
        "  No command needed.\n\n"
        "  Examples:\n"
        "   • `@username`\n"
        "   • `1234567890`\n\n"
        "📞 *Phone Number Lookup*\n"
        "  Use the /num command followed by the number.\n\n"
        "  Example:\n"
        "   • `/num 9876543210`\n\n"
        "🪪 *Aadhar Lookup*\n"
        "  Use the /aadhar command followed by 12-digit Aadhar.\n\n"
        "  Example:\n"
        "   • `/aadhar 652507323571`\n\n"
        "🚗 *Vehicle Lookup*\n"
        "  Use the /veh command followed by vehicle plate number.\n\n"
        "  Example:\n"
        "   • `/veh HR36AD4511`\n\n"
        "👤 *Your Info*\n"
        "  Use /info to see your profile and stats.\n\n"
        "📝 *Report an Issue*\n"
        "  Use the /report command followed by your message.\n"
        "  Your report will be sent directly to the admin.\n\n"
        "  Example:\n"
        "   • `/report Bot is not responding properly`\n\n"
        "📋 *Available Commands*\n"
        "  /start       — Start the bot\n"
        "  /num         — Phone number lookup\n"
        "  /aadhar      — Aadhar lookup\n"
        "  /veh         — Vehicle lookup\n"
        "  /info        — Your profile and usage stats\n"
        "  /report      — Report an issue to admin\n"
        "  /settings    — Show bot features\n"
        "  /back        — Back to main menu\n"
        "  /cancel      — Cancel current action\n"
        "  /help        — Show this help message"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def grouphelp_command(update, context):
    if not await guard(update, context):
        return
    text = (
        "🛡 *@racksunbot — Group Admin Commands*\n\n"
        "These commands can be used by group admins.\n"
        "You can use them by replying to a message, or with @username or User ID.\n\n"

        "━━━━━━━━━━━━━━━\n"
        "⚠️ *WARN COMMANDS*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "2 warnings = *auto-ban*\n\n"
        "`/warn` — Give a warning to a user\n"
        "`/warns` — Check how many warnings a user has\n"
        "`/resetwarn` — Reset all warnings of a user\n\n"
        "*How to use /warn:*\n"
        "• Reply to their message → `/warn spamming`\n"
        "• By username → `/warn @john rules tod raha tha`\n"
        "• By User ID → `/warn 98877655 sending adult content`\n"
        "• Without reason → `/warn` _(reply to message)_\n\n"
        "*How to use /warns:*\n"
        "• Reply to their message → `/warns`\n"
        "• By username → `/warns @john`\n"
        "• By User ID → `/warns 98877655`\n\n"
        "*How to use /resetwarn:*\n"
        "• Reply to their message → `/resetwarn`\n"
        "• By username → `/resetwarn @john`\n"
        "• By User ID → `/resetwarn 98877655`\n\n"

        "━━━━━━━━━━━━━━━\n"
        "🚫 *BAN COMMANDS*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "`/ban` — Ban a user from using the bot\n"
        "`/unban` — Remove ban from a user\n"
        "`/banlist` — See all banned users\n\n"
        "*How to use /ban:*\n"
        "• Reply to their message → `/ban was spamming`\n"
        "• By username → `/ban @john sending scam links`\n"
        "• By User ID → `/ban 98877655 abusive behaviour`\n"
        "• Without reason → `/ban` _(reply to message)_\n\n"
        "*How to use /unban:*\n"
        "• Reply to their message → `/unban`\n"
        "• By username → `/unban @john`\n"
        "• By User ID → `/unban 98877655`\n\n"

        "━━━━━━━━━━━━━━━\n"
        "🔇 *MUTE COMMANDS*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "`/mute` — Mute a user _(they cannot use the bot)_\n"
        "`/unmute` — Remove mute from a user\n"
        "`/mutelist` — See all muted users\n\n"
        "*How to use /mute:*\n"
        "• Reply to their message → `/mute too much spam`\n"
        "• By username → `/mute @john disturbing others`\n"
        "• By User ID → `/mute 98877655 bad language`\n"
        "• Without reason → `/mute` _(reply to message)_\n\n"
        "*How to use /unmute:*\n"
        "• Reply to their message → `/unmute`\n"
        "• By username → `/unmute @john`\n"
        "• By User ID → `/unmute 98877655`\n\n"

        "━━━━━━━━━━━━━━━\n"
        "📋 *OTHER COMMANDS*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "`/info` — Check info of any user\n"
        "• Reply to their message → `/info`\n"
        "• By username → `/info @john`\n"
        "• By User ID → `/info 98877655`\n\n"
        "`/adminhelp` — Full admin command list\n\n"
        "━━━━━━━━━━━━━━━\n"
        "_Tip: Replying to a message is the easiest way — no need to type ID or username!_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")



async def info_command(update, context):
    """Any user: /info → own profile. Reply to msg → that person's info.
    Admin: /info <user_id> → any user's info."""
    if not await guard(update, context):
        return
    user_id = update.message.from_user.id
    target_id = user_id

    resolved_id, _, err = await resolve_target_id(update, context, context.args or [])
    if resolved_id:
        target_id = resolved_id
    elif context.args or update.message.reply_to_message:
        await update.message.reply_text(err or "❌ *Invalid input!*", parse_mode="Markdown")
        return

    row = get_user_info_db(target_id)
    if not row:
        await update.message.reply_text(
            "❌ *User not found in database.*\n\nThis user has never used the bot.",
            parse_mode="Markdown",
        )
        return

    uid, first_name, username, join_date, search_count, banned, ban_reason, muted, mute_reason = row
    uname_display = "@" + username if username else "N/A"

    if banned:
        status = "🚫 Banned"
        if ban_reason:
            status += "\n*Ban Reason:* `" + ban_reason + "`"
    elif muted:
        status = "🔇 Muted"
        if mute_reason:
            status += "\n*Mute Reason:* `" + mute_reason + "`"
    else:
        status = "✅ Active"

    premium = is_premium_user(uid)
    premium_expiry = get_premium_expiry(uid)
    premium_line = "\n*Plan:* ⭐ *Premium* _(expires " + premium_expiry + ")_" if premium else "\n*Plan:* 🆓 Free"

    num_count, tg_count, aadhar_count = get_daily_counts(uid)
    veh_count = get_daily_veh_count(uid)
    if not premium:
        usage_line = (
            "\n*Today's Usage:*\n"
            "  📞 Number: `" + str(num_count) + "/" + str(FREE_NUM_LIMIT) + "`\n"
            "  🪪 Aadhar: `" + str(aadhar_count) + "/" + str(FREE_NUM_LIMIT) + "`\n"
            "  🚗 Vehicle: `" + str(veh_count) + "/" + str(FREE_VEH_LIMIT) + "`\n"
            "  📱 TG Lookup: `" + str(tg_count) + "/" + str(FREE_TG_LIMIT) + "`"
        )
    else:
        usage_line = "\n*Today's Usage:* `Unlimited ♾️`"

    text = (
        "👤 *User Info*\n\n"
        "*Name:* `" + val(first_name) + "`\n"
        "*Username:* " + uname_display + "\n"
        "*User ID:* `" + str(uid) + "`\n"
        "*Joined:* `" + val(join_date) + "`\n"
        "*Total Searches:* `" + str(search_count) + "`\n"
        "*Status:* " + status +
        premium_line +
        usage_line
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def stats_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    total, searches, today_joined = get_stats_db()
    premium_count = get_premium_count_db()
    msg = (
        "📊 *Bot Stats*\n\n"
        "👥 *Total Users:* `" + str(total) + "`\n"
        "📅 *Joined Today:* `" + str(today_joined) + "`\n"
        "🔍 *Total Searches:* `" + str(searches) + "`\n"
        "⭐ *Premium Users:* `" + str(premium_count) + "`\n"
        "🔧 *Maintenance:* `" + ("ON" if maintenance_mode else "OFF") + "`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def adminhelp_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return
    text = (
        "🛡 *Admin Commands*\n\n"
        "━━━━━━━━━━━━━━━\n"
        "⭐ *PREMIUM SYSTEM*\n"
        "━━━━━━━━━━━━━━━\n"
        "`/premium <uid> <days>` — Give premium\n"
        "  Example: `/premium 123456789 30`\n\n"
        "`/removepremium <uid>` — Remove premium\n\n"
        "`/premiumlist` — All premium users\n\n"
        "🆓 *Free limits:* Number=15/day | Aadhar=15/day | Vehicle=5/day | TG=10/day\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *OTHER ADMIN*\n"
        "━━━━━━━━━━━━━━━\n"
        "`/stats` — Bot stats\n\n"
        "`/info` — User info _(reply or ID)_\n\n"
        "`/reply` — Send message to user\n\n"
        "`/broadcast` — Broadcast to all users\n\n"
        "`/maintenance on/off` — Enable/disable maintenance\n\n"
        "━━━━━━━━━━━━━━━\n"
        "_Tip: Reply to a message and use command — no need to remember IDs!_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def maintenance_command(update, context):
    global maintenance_mode
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    if not context.args:
        current = "ON" if maintenance_mode else "OFF"
        await update.message.reply_text(
            "🔧 *Maintenance Mode*\n\nCurrent: *" + current + "*\n\nUsage: `/maintenance on` or `/maintenance off`",
            parse_mode="Markdown",
        )
        return
    arg = context.args[0].lower()
    if arg == "on":
        maintenance_mode = True
        await update.message.reply_text("🔧 *Maintenance mode ON.*\n\nUsers cannot use the bot now.", parse_mode="Markdown")
    elif arg == "off":
        maintenance_mode = False
        await update.message.reply_text("✅ *Maintenance mode OFF.*\n\nBot is live again.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ *Use:* `/maintenance on` or `/maintenance off`", parse_mode="Markdown")


async def report_command(update, context):
    if not await guard(update, context):
        return
    if not context.args:
        usage = (
            "📝 *Report an Issue*\n\n"
            "*Usage:* `/report <your message>`\n\n"
            "*Example:*\n"
            "`/report Bot is not responding to username lookup`\n\n"
            "_Your message will be sent directly to the admin._"
        )
        await update.message.reply_text(usage, parse_mode="Markdown")
        return
    user = update.message.from_user
    report_text = " ".join(context.args)
    username = "@" + user.username if user.username else "N/A"
    full_name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    full_name = full_name.strip() or "Unknown"
    admin_msg = (
        "🚨 *New Report Received*\n\n"
        "*From:* " + full_name + "\n"
        "*Username:* " + username + "\n"
        "*User ID:* `" + str(user.id) + "`\n\n"
        "*Message:*\n" + report_text
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
        await update.message.reply_text(
            "✅ *Report Sent Successfully!*\n\nYour message has been delivered to the admin. You will receive a response soon.",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text("❌ *Failed to send report.*\nPlease try again after some time.", parse_mode="Markdown")
        await log_error_to_admin(context, "report_command: " + str(e))


async def reply_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "*Usage:* `/reply <user_id> <your message>`\n\n"
            "*Example:*\n`/reply 1234567890 Thanks, we have fixed the issue!`",
            parse_mode="Markdown",
        )
        return
    target_id = context.args[0]
    if not target_id.isdigit():
        await update.message.reply_text("❌ *Invalid User ID!*", parse_mode="Markdown")
        return
    message = " ".join(context.args[1:])
    reply_text = "💬 *Reply from Admin*\n\n" + message
    try:
        await context.bot.send_message(chat_id=int(target_id), text=reply_text, parse_mode="Markdown")
        await update.message.reply_text(
            "✅ *Reply sent successfully!*\n\n"
            "*Sent to User ID:* `" + target_id + "`\n"
            "*Message:* " + message,
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ *Failed to send reply.*\n\nUser may have blocked the bot or ID is wrong.\n*Error:* " + str(e),
            parse_mode="Markdown",
        )


async def num_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text("*Usage:* `/num 9876543219`", parse_mode="Markdown")
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    if not is_premium_user(user_id) and user_id != ADMIN_ID:
        check_and_reset_daily(user_id)
        num_count, _, _ = get_daily_counts(user_id)
        if num_count >= FREE_NUM_LIMIT:
            await update.message.reply_text(
                "🚫 *Daily Limit Reached!*\n\n"
                "🆓 *Free users* can search *" + str(FREE_NUM_LIMIT) + " numbers/day*.\n"
                "You have used all your searches for today.\n\n"
                "⭐ *Upgrade to Premium* for unlimited searches!\n"
                "Contact @racksunn to get premium.",
                parse_mode="Markdown",
            )
            return

    number = context.args[0].replace("+", "").replace(" ", "").replace("-", "")
    searching = await update.message.reply_text("🔍 Searching...")

    entries = []

    try:
        url2 = NUMBER_API_URL2.format(number=number)
        data2 = await fetch_json(url2)
        raw2 = data2.get("data") if isinstance(data2, dict) else None
        if isinstance(raw2, list):
            for r in raw2:
                entries.append({
                    "name": r.get("NAME") or r.get("name"),
                    "father": r.get("fname"),
                    "mobile": r.get("MOBILE") or r.get("mobile"),
                    "alt": r.get("alt"),
                    "aadhar": r.get("id"),
                    "email": r.get("email"),
                    "circle": r.get("circle"),
                    "address": r.get("ADDRESS") or r.get("address"),
                })
    except Exception:
        pass

    if not entries:
        try:
            url = NUMBER_API_URL.format(number=number)
            data = await fetch_json(url)
            results = []
            if isinstance(data, dict):
                inner = data.get("data", {})
                if isinstance(inner, dict):
                    result_obj = inner.get("result", {})
                    if isinstance(result_obj, dict):
                        results = result_obj.get("data", [])
            if isinstance(results, list):
                for r in results:
                    entries.append({
                        "name": r.get("NAME") or r.get("name"),
                        "father": r.get("fname"),
                        "mobile": r.get("MOBILE") or r.get("mobile"),
                        "alt": r.get("alt"),
                        "aadhar": r.get("id"),
                        "email": r.get("email"),
                        "circle": r.get("circle"),
                        "address": r.get("ADDRESS") or r.get("address"),
                    })
        except Exception:
            pass

    await delete_msg(context, chat_id, searching.message_id)

    if not entries:
        not_found_msg = "*❌ Data Not Found!*\n\nNo information found for this number."
        if not is_premium_user(user_id) and user_id != ADMIN_ID:
            num_count, _, _ = get_daily_counts(user_id)
            not_found_msg += "\n\n✅ *Search credit refunded!* _(daily count not incremented)_\n📊 Used: `" + str(num_count) + "/" + str(FREE_NUM_LIMIT) + "` today"
        await update.message.reply_text(not_found_msg, parse_mode="Markdown")
        return

    increment_search(user_id)
    if not is_premium_user(user_id) and user_id != ADMIN_ID:
        increment_num_daily(user_id)
        num_count, _, _ = get_daily_counts(user_id)
        remaining = FREE_NUM_LIMIT - num_count
        if remaining <= 3:
            await update.message.reply_text(
                "⚠️ *Warning:* Only *" + str(max(0, remaining)) + " free searches* left for today!\n"
                "Upgrade to ⭐ *Premium* for unlimited searches.",
                parse_mode="Markdown",
            )

    for i, entry in enumerate(entries, 1):
        text = (
            "*Result " + str(i) + "/" + str(len(entries)) + "*\n\n"
            "*Number:* `" + number + "`\n"
            "*Name:* `" + str(entry.get("name") or "None") + "`\n"
            "*Father:* `" + str(entry.get("father") or "None") + "`\n"
            "*Mobile:* `" + str(entry.get("mobile") or "None") + "`\n"
            "*Alt Mobile:* `" + str(entry.get("alt") or "None") + "`\n"
            "*National ID:* `" + str(entry.get("aadhar") or "None") + "`\n"
            "*Email:* `" + str(entry.get("email") or "None") + "`\n"
            "*Circle:* `" + str(entry.get("circle") or "None") + "`\n"
            "*Address:* `" + clean_address(entry.get("address")) + "`"
        )
        await update.message.reply_text(text, parse_mode="Markdown")


async def aadhar_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text("*Usage:* `/aadhar 652507323571`", parse_mode="Markdown")
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    if not is_premium_user(user_id) and user_id != ADMIN_ID:
        check_and_reset_daily(user_id)
        aadhar_count = get_daily_aadhar_count(user_id)
        if aadhar_count >= FREE_NUM_LIMIT:
            await update.message.reply_text(
                "🚫 *Daily Limit Reached!*\n\n"
                "🆓 *Free users* can search *" + str(FREE_NUM_LIMIT) + " Aadhar/day*.\n"
                "You have used all your searches for today.\n\n"
                "⭐ *Upgrade to Premium* for unlimited searches!\n"
                "Contact @racksunn to get premium.",
                parse_mode="Markdown",
            )
            return

    aadhar = context.args[0].replace(" ", "").replace("-", "")
    searching = await update.message.reply_text("🔍 Searching...")
    try:
        url = AADHAR_API_URL.format(aadhar=aadhar)
        data = await fetch_json(url)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "aadhar_lookup: " + str(e))
        return

    entries = []
    if isinstance(data, dict):
        inner = data.get("data", {})
        if isinstance(inner, dict):
            raw = inner.get("result", [])
            if isinstance(raw, list):
                for r in raw:
                    entries.append({
                        "name": r.get("NAME") or r.get("name"),
                        "father": r.get("fname"),
                        "mobile": r.get("MOBILE") or r.get("mobile"),
                        "alt": r.get("alt"),
                        "aadhar": r.get("id"),
                        "email": r.get("email"),
                        "circle": r.get("circle"),
                        "address": r.get("ADDRESS") or r.get("address"),
                    })

    await delete_msg(context, chat_id, searching.message_id)

    if not entries:
        not_found_msg = "*❌ Data Not Found!*\n\nNo information found for this Aadhar."
        if not is_premium_user(user_id) and user_id != ADMIN_ID:
            aadhar_count = get_daily_aadhar_count(user_id)
            not_found_msg += "\n\n✅ *Search credit refunded!* _(daily count not incremented)_\n📊 Used: `" + str(aadhar_count) + "/" + str(FREE_NUM_LIMIT) + "` today"
        await update.message.reply_text(not_found_msg, parse_mode="Markdown")
        return

    increment_search(user_id)
    if not is_premium_user(user_id) and user_id != ADMIN_ID:
        increment_aadhar_daily(user_id)
        aadhar_count = get_daily_aadhar_count(user_id)
        remaining = FREE_NUM_LIMIT - aadhar_count
        if remaining <= 3:
            await update.message.reply_text(
                "⚠️ *Warning:* Only *" + str(max(0, remaining)) + " free Aadhar searches* left for today!\n"
                "Upgrade to ⭐ *Premium* for unlimited searches.",
                parse_mode="Markdown",
            )

    for i, entry in enumerate(entries, 1):
        text = (
            "*Result " + str(i) + "/" + str(len(entries)) + "*\n\n"
            "*Aadhar:* `" + aadhar + "`\n"
            "*Name:* `" + str(entry.get("name") or "None") + "`\n"
            "*Father:* `" + str(entry.get("father") or "None") + "`\n"
            "*Mobile:* `" + str(entry.get("mobile") or "None") + "`\n"
            "*Alt Mobile:* `" + str(entry.get("alt") or "None") + "`\n"
            "*National ID:* `" + str(entry.get("aadhar") or "None") + "`\n"
            "*Email:* `" + str(entry.get("email") or "None") + "`\n"
            "*Circle:* `" + str(entry.get("circle") or "None") + "`\n"
            "*Address:* `" + clean_address(entry.get("address")) + "`"
        )
        await update.message.reply_text(text, parse_mode="Markdown")




async def veh_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/veh HR36AD4511`\n\n_Enter the vehicle plate number._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    if not is_premium_user(user_id) and user_id != ADMIN_ID:
        check_and_reset_daily(user_id)
        veh_count = get_daily_veh_count(user_id)
        if veh_count >= FREE_VEH_LIMIT:
            await update.message.reply_text(
                "🚫 *Daily Limit Reached!*\n\n"
                "🆓 *Free users* can search *" + str(FREE_VEH_LIMIT) + " vehicles/day*.\n"
                "You have used all your searches for today.\n\n"
                "⭐ *Upgrade to Premium* for unlimited searches!\n"
                "Contact @racksunn to get premium.",
                parse_mode="Markdown",
            )
            return

    plate = context.args[0].strip().upper().replace(" ", "")
    searching = await update.message.reply_text("🔍 Searching...")
    try:
        url = VEH_API_URL.format(veh=plate)
        data = await fetch_json(url)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "veh_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not data or (isinstance(data, dict) and not data.get("data") and not data.get("success") and not data.get("result")):
        not_found_msg = "*❌ Data Not Found!*\n\nNo information found for this vehicle number."
        if not is_premium_user(user_id) and user_id != ADMIN_ID:
            veh_count = get_daily_veh_count(user_id)
            not_found_msg += "\n\n✅ *Search credit refunded!* _(daily count not incremented)_\n📊 Used: `" + str(veh_count) + "/" + str(FREE_VEH_LIMIT) + "` today"
        await update.message.reply_text(not_found_msg, parse_mode="Markdown")
        return

    increment_search(user_id)
    if not is_premium_user(user_id) and user_id != ADMIN_ID:
        increment_veh_daily(user_id)
        veh_count = get_daily_veh_count(user_id)
        remaining = FREE_VEH_LIMIT - veh_count
        if remaining <= 1:
            await update.message.reply_text(
                "⚠️ *Warning:* Only *" + str(max(0, remaining)) + " free vehicle searches* left for today!\n"
                "Upgrade to ⭐ *Premium* for unlimited searches.",
                parse_mode="Markdown",
            )

    SKIP_KEYS = {"status", "message", "msg", "error", "success", "code", "key"}
    LABEL_MAP = {
        "rc_regn_no": "Plate No", "reg_no": "Plate No",
        "rc_owner_name": "Owner Name", "owner": "Owner Name",
        "rc_father_name": "Father Name",
        "rc_present_address": "Address", "address": "Address",
        "rc_mobile_no": "Mobile",
        "rc_veh_class_desc": "Vehicle Class", "class": "Vehicle Class",
        "rc_maker_desc": "Maker", "maker": "Maker",
        "rc_model": "Model", "model": "Model",
        "rc_color": "Color", "color": "Color",
        "rc_fuel_desc": "Fuel Type", "fuel": "Fuel Type",
        "rc_regn_dt": "Reg Date", "reg_date": "Reg Date",
        "rc_fit_upto": "Fitness Upto",
        "rc_insurance_comp": "Insurance Co",
        "rc_insurance_upto": "Insurance Upto",
        "rc_financer": "Financer",
        "rc_status": "RC Status",
        "rc_pucc_upto": "PUC Upto",
        "rc_state": "State",
    }

    def flatten_veh(obj, prefix=""):
        items = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                items.update(flatten_veh(v, k))
        elif isinstance(obj, list) and len(obj) > 0:
            items.update(flatten_veh(obj[0], prefix))
        else:
            if prefix and str(obj).strip() and str(obj).lower() not in ("none", "null", "n/a", "", "0"):
                items[prefix.lower()] = str(obj).strip()
        return items

    flat = flatten_veh(data)
    lines = ["🚗 *Vehicle Info*\n\n*Plate:* `" + plate + "`"]
    for k, v in flat.items():
        if k in SKIP_KEYS:
            continue
        label = LABEL_MAP.get(k, k.replace("_", " ").title())
        lines.append("*" + label + ":* `" + v + "`")

    if len(lines) <= 1:
        not_found_msg = "*❌ Data Not Found!*\n\nNo information found for this vehicle number."
        if not is_premium_user(user_id) and user_id != ADMIN_ID:
            veh_count = get_daily_veh_count(user_id)
            not_found_msg += "\n\n✅ *Search credit refunded!* _(daily count not incremented)_\n📊 Used: `" + str(veh_count) + "/" + str(FREE_VEH_LIMIT) + "` today"
        await update.message.reply_text(not_found_msg, parse_mode="Markdown")
        return

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_users_shared(update, context):
    if not await guard(update, context):
        return
    if update.message.users_shared:
        for user in update.message.users_shared.users:
            await update.message.reply_text("*User ID:* `" + str(user.user_id) + "`", parse_mode="Markdown")


async def handle_chat_shared(update, context):
    if not await guard(update, context):
        return
    if update.message.chat_shared:
        await update.message.reply_text("*Chat ID:* `" + str(update.message.chat_shared.chat_id) + "`", parse_mode="Markdown")


async def lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return

    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    user_input = update.message.text.strip()

    if not is_premium_user(user_id) and user_id != ADMIN_ID:
        check_and_reset_daily(user_id)
        _, tg_count, _ = get_daily_counts(user_id)
        if tg_count >= FREE_TG_LIMIT:
            await update.message.reply_text(
                "🚫 *Daily Limit Reached!*\n\n"
                "🆓 *Free users* can do *" + str(FREE_TG_LIMIT) + " TG lookups/day*.\n"
                "You have used all your lookups for today.\n\n"
                "⭐ *Upgrade to Premium* for unlimited lookups!\n"
                "Contact @racksunn to get premium.",
                parse_mode="Markdown",
            )
            return
    chat_type = update.message.chat.type
    bot_username = (await context.bot.get_me()).username

    if chat_type in ["group", "supergroup"]:
        if "@" + bot_username.lower() in user_input.lower():
            user_input = re.sub(re.escape("@" + bot_username), "", user_input, flags=re.IGNORECASE).strip()
            if not user_input:
                return

    is_username = user_input.startswith("@") and len(user_input) > 1
    digits_only = user_input.lstrip("+")
    is_number = digits_only.isdigit() and len(digits_only) >= 7

    if not is_username and not is_number:
        return

    searching = await update.message.reply_text("🔍 Searching...")

    term = user_input if is_username else digits_only

    try:
        api_url = TG_LOOKUP_API.format(term=term)
        data = await fetch_json(api_url)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nCould not reach the lookup server. Try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    def tg_not_found_msg(uid):
        base = "*❌ Data Not Found!*\n\nNo data linked to this Telegram account."
        if not is_premium_user(uid) and uid != ADMIN_ID:
            _, tg_count, _ = get_daily_counts(uid)
            base += "\n\n✅ *Search credit refunded!* _(daily count not incremented)_\n📊 Used: `" + str(tg_count) + "/" + str(FREE_TG_LIMIT) + "` today"
        return base

    # Check for error / not found
    if isinstance(data, dict):
        status = str(data.get("status", "")).lower()
        msg = str(data.get("message", "") or data.get("msg", "") or data.get("error", "")).lower()
        if status in ("false", "0", "error", "fail", "failed") or "not found" in msg or "invalid" in msg or "no data" in msg:
            await update.message.reply_text(tg_not_found_msg(user_id), parse_mode="Markdown")
            return
        if not data or (isinstance(data.get("data"), (list, dict)) and not data.get("data")):
            await update.message.reply_text(tg_not_found_msg(user_id), parse_mode="Markdown")
            return

    increment_search(user_id)
    if not is_premium_user(user_id) and user_id != ADMIN_ID:
        increment_tg_daily(user_id)
        _, tg_count, _ = get_daily_counts(user_id)
        remaining = FREE_TG_LIMIT - tg_count
        if remaining <= 2:
            await update.message.reply_text(
                "⚠️ *Warning:* Only *" + str(max(0, remaining)) + " free TG lookups* left for today!\n"
                "Upgrade to ⭐ *Premium* for unlimited lookups.",
                parse_mode="Markdown",
            )

    # Build result from whatever the API returns
    SKIP_KEYS = {"status", "message", "msg", "error", "success", "code", "key", "type", "owner", "cached", "attempt"}
    LABEL_MAP = {
        "number": "Number", "phone": "Number", "mobile": "Number",
        "id": "TG ID", "user_id": "TG ID", "tg_id": "TG ID", "userid": "TG ID",
        "name": "Name", "first_name": "First Name", "last_name": "Last Name",
        "username": "Username",
        "country": "Country", "country_code": "Country Code",
        "email": "Email", "dob": "DOB", "gender": "Gender",
        "operator": "Operator", "circle": "Circle", "state": "State",
    }

    def flatten(obj, prefix=""):
        items = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                items.update(flatten(v, k))
        elif isinstance(obj, list) and len(obj) > 0:
            items.update(flatten(obj[0], prefix))
        else:
            if prefix and str(obj).strip() and str(obj).lower() not in ("none", "null", "n/a", ""):
                items[prefix.lower()] = str(obj).strip()
        return items

    flat = flatten(data)
    lines = ["*Result:*\n"]
    for k, v in flat.items():
        if k in SKIP_KEYS:
            continue
        label = LABEL_MAP.get(k, k.replace("_", " ").title())
        lines.append("*" + label + ":* `" + v + "`")

    if len(lines) <= 1:
        await update.message.reply_text(tg_not_found_msg(user_id), parse_mode="Markdown")
        return

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def broadcast_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "📢 *Broadcast Usage:*\n\n`/broadcast Aapka message yahan`",
            parse_mode="Markdown",
        )
        return
    message = " ".join(context.args)
    user_ids = get_all_user_ids_db()
    if not user_ids:
        await update.message.reply_text("❌ *No users found!*", parse_mode="Markdown")
        return
    status_msg = await update.message.reply_text("📤 *Broadcasting...*", parse_mode="Markdown")
    sent = 0
    failed = 0
    broadcast_text = "📢 *Message from Admin:*\n\n" + message
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=broadcast_text, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await status_msg.edit_text(
        "✅ *Broadcast Complete!*\n\n"
        "*Total Users:* `" + str(len(user_ids)) + "`\n"
        "*Sent:* `" + str(sent) + "`\n"
        "*Failed:* `" + str(failed) + "`",
        parse_mode="Markdown",
    )


async def premium_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    args = context.args or []
    if len(args) < 2 or not args[0].lstrip("-").isdigit() or not args[1].isdigit():
        await update.message.reply_text(
            "⭐ *Premium Command Usage:*\n\n"
            "`/premium <user_id> <days>`\n\n"
            "*Example:*\n`/premium 123456789 30`\n\n"
            "_This gives the user premium access for 30 days._",
            parse_mode="Markdown",
        )
        return
    target_id = int(args[0])
    days = int(args[1])
    row = get_user_info_db(target_id)
    if not row:
        await update.message.reply_text(
            "❌ *User not found in database.*\n\nUser ne pehle bot use nahi kiya.",
            parse_mode="Markdown",
        )
        return
    expiry = add_premium_db(target_id, days)
    target_name = val(row[1]) if row else str(target_id)
    await update.message.reply_text(
        "⭐ *Premium Activated!*\n\n"
        "*User:* `" + target_name + "`\n"
        "*User ID:* `" + str(target_id) + "`\n"
        "*Duration:* `" + str(days) + " days`\n"
        "*Expires:* `" + expiry + "`",
        parse_mode="Markdown",
    )
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "🎉 *Congratulations! You have been upgraded to Premium!*\n\n"
                "⭐ *Plan:* Premium\n"
                "📅 *Expires:* `" + expiry + "`\n\n"
                "✅ You now have *unlimited searches* on this bot!\n\n"
                "📞 Number Lookup: ♾️ Unlimited\n"
                "📱 TG Lookup: ♾️ Unlimited\n\n"
                "_Enjoy premium access!_"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def removepremium_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    args = context.args or []
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            "*Usage:* `/removepremium <user_id>`\n\n"
            "*Example:* `/removepremium 123456789`",
            parse_mode="Markdown",
        )
        return
    target_id = int(args[0])
    row = get_user_info_db(target_id)
    if not row:
        await update.message.reply_text("❌ *User not found in database.*", parse_mode="Markdown")
        return
    remove_premium_db(target_id)
    target_name = val(row[1]) if row else str(target_id)
    await update.message.reply_text(
        "✅ *Premium Removed!*\n\n"
        "*User:* `" + target_name + "`\n"
        "*User ID:* `" + str(target_id) + "`\n\n"
        "_User is now on Free plan._",
        parse_mode="Markdown",
    )
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "ℹ️ *Your Premium access has ended.*\n\n"
                "You are now on the *Free plan*.\n\n"
                "🆓 Free limits:\n"
                "📞 Number Lookup: `" + str(FREE_NUM_LIMIT) + "/day`\n"
                "🪪 Aadhar Lookup: `" + str(FREE_NUM_LIMIT) + "/day`\n"
                "🚗 Vehicle Lookup: `" + str(FREE_VEH_LIMIT) + "/day`\n"
                "📱 TG Lookup: `" + str(FREE_TG_LIMIT) + "/day`"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def premiumlist_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    rows = get_premium_list_db()
    if not rows:
        await update.message.reply_text("⭐ *No premium users.*", parse_mode="Markdown")
        return
    lines = ["⭐ *Premium Users List*\n"]
    for i, (uid, fname, uname, expiry) in enumerate(rows, 1):
        uname_display = "@" + uname if uname else "N/A"
        line = (
            str(i) + ". `" + str(uid) + "` — " + val(fname) + " (" + uname_display + ")\n"
            "    📅 Expires: `" + (expiry or "N/A") + "`"
        )
        lines.append(line)
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def mypremium_command(update, context):
    if not await guard(update, context):
        return
    user_id = update.message.from_user.id
    premium = is_premium_user(user_id)
    expiry = get_premium_expiry(user_id)
    check_and_reset_daily(user_id)
    num_count, tg_count, aadhar_count = get_daily_counts(user_id)

    if premium:
        text = (
            "⭐ *Your Premium Status*\n\n"
            "*Plan:* ⭐ Premium\n"
            "*Expires:* `" + expiry + "`\n\n"
            "*Today's Usage:* ♾️ Unlimited\n"
            "📞 Number searches used: `" + str(num_count) + "`\n"
            "🪪 Aadhar searches used: `" + str(aadhar_count) + "`\n"
            "📱 TG lookups used: `" + str(tg_count) + "`"
        )
    else:
        text = (
            "🆓 *Your Plan: Free*\n\n"
            "*Today's Usage:*\n"
            "📞 Number: `" + str(num_count) + "/" + str(FREE_NUM_LIMIT) + "`\n"
            "🪪 Aadhar: `" + str(aadhar_count) + "/" + str(FREE_NUM_LIMIT) + "`\n"
            "📱 TG Lookup: `" + str(tg_count) + "/" + str(FREE_TG_LIMIT) + "`\n\n"
            "⭐ *Upgrade to Premium* for unlimited searches!\n"
            "Contact @racksunn to get premium."
        )
    await update.message.reply_text(text, parse_mode="Markdown")


if __name__ == "__main__":
    init_db()
    keep_alive()
    print("Flask Server Started!")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("num", num_lookup))
    app.add_handler(CommandHandler("aadhar", aadhar_lookup))
    app.add_handler(CommandHandler("veh", veh_lookup))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("grouphelp", grouphelp_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("back", back_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("reply", reply_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("removepremium", removepremium_command))
    app.add_handler(CommandHandler("premiumlist", premiumlist_command))
    app.add_handler(CommandHandler("mypremium", mypremium_command))
    app.add_handler(CommandHandler("adminhelp", adminhelp_command))
    app.add_handler(CommandHandler("maintenance", maintenance_command))
    app.add_handler(CallbackQueryHandler(check_joined_callback, pattern="check_joined"))
    app.add_handler(MessageHandler(filters.StatusUpdate.USERS_SHARED, handle_users_shared))
    app.add_handler(MessageHandler(filters.StatusUpdate.CHAT_SHARED, handle_chat_shared))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lookup))
    print("Bot is Online!")
    app.run_polling()
