import os
import re
import time
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
IFSC_API_URL = "https://ayush-multi-apiv2.onrender.com/ifsc?q={ifsc}"
TG_LOOKUP_API = "https://api.subhxcosmo.in/api?key=RACKSUN&type=tg&term={term}"

CHANNEL_USERNAME = "@racksun19"
CHANNEL_LINK = "https://t.me/racksun19"
GROUP_USERNAME = "@racksungroup"
GROUP_LINK = "https://t.me/racksungroup"

COOLDOWN_SECONDS = 5

maintenance_mode = False
user_last_request = {}

DB_FILE = "bot.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            first_name   TEXT,
            username     TEXT,
            join_date    TEXT,
            search_count INTEGER DEFAULT 0,
            is_banned    INTEGER DEFAULT 0,
            ban_reason   TEXT DEFAULT '',
            is_muted     INTEGER DEFAULT 0,
            mute_reason  TEXT DEFAULT '',
            warn_count   INTEGER DEFAULT 0
        )
    """)
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
    c.execute("SELECT user_id, first_name, username, join_date, search_count, is_banned, ban_reason, is_muted, mute_reason FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def get_stats_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE is_banned=1")
    banned = c.fetchone()[0]
    c.execute("SELECT SUM(search_count) FROM users")
    searches = c.fetchone()[0] or 0
    today = datetime.now().strftime("%d %b %Y")
    c.execute("SELECT COUNT(*) FROM users WHERE join_date=?", (today,))
    today_joined = c.fetchone()[0]
    conn.close()
    return total, banned, searches, today_joined


def ban_user_db(user_id, reason=""):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=1, ban_reason=? WHERE user_id=?", (reason, user_id))
    conn.commit()
    conn.close()


def unban_user_db(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=0, ban_reason='' WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def mute_user_db(user_id, reason=""):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET is_muted=1, mute_reason=? WHERE user_id=?", (reason, user_id))
    conn.commit()
    conn.close()


def unmute_user_db(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET is_muted=0, mute_reason='' WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_banned_list_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id, first_name, username, ban_reason FROM users WHERE is_banned=1")
    rows = c.fetchall()
    conn.close()
    return rows


def get_muted_list_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id, first_name, username, mute_reason FROM users WHERE is_muted=1")
    rows = c.fetchall()
    conn.close()
    return rows


def get_all_user_ids_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_banned=0")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


def is_user_banned(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row and row[0] == 1


def is_user_muted(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT is_muted FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row and row[0] == 1


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


def add_warn_db(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET warn_count = warn_count + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    c.execute("SELECT warn_count FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 1


def get_warn_count_db(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT warn_count FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def reset_warn_db(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET warn_count=0 WHERE user_id=?", (user_id,))
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
            return False, int(COOLDOWN_SECONDS - elapsed)
    user_last_request[user_id] = now
    return True, 0


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

    if is_user_banned(user_id):
        await update.message.reply_text(
            "🚫 *You have been banned from using this bot.*\n\nContact admin if you think this is a mistake.",
            parse_mode="Markdown",
        )
        return False

    if is_user_muted(user_id):
        await update.message.reply_text(
            "🔇 *Shhh... quiet now.*\n\nYou are muted and cannot use this bot right now.\nContact admin if you think this is a mistake.",
            parse_mode="Markdown",
        )
        return False

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
        "🏦 *IFSC / Bank Lookup*\n"
        "Use `/ifsc <code>` to fetch bank name, branch, address, UPI/NEFT/RTGS\n\n"
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
        "🏦 *IFSC / Bank Lookup*\n"
        "  Use the /ifsc command followed by IFSC code.\n\n"
        "  Example:\n"
        "   • `/ifsc SBIN0001234`\n\n"
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
        "  /ifsc        — Bank IFSC lookup\n"
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

    text = (
        "👤 *User Info*\n\n"
        "*Name:* `" + val(first_name) + "`\n"
        "*Username:* " + uname_display + "\n"
        "*User ID:* `" + str(uid) + "`\n"
        "*Joined:* `" + val(join_date) + "`\n"
        "*Total Searches:* `" + str(search_count) + "`\n"
        "*Status:* " + status
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def stats_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    total, banned, searches, today_joined = get_stats_db()
    msg = (
        "📊 *Bot Stats*\n\n"
        "👥 *Total Users:* `" + str(total) + "`\n"
        "📅 *Joined Today:* `" + str(today_joined) + "`\n"
        "🔍 *Total Searches:* `" + str(searches) + "`\n"
        "🚫 *Banned Users:* `" + str(banned) + "`\n"
        "🔧 *Maintenance:* `" + ("ON" if maintenance_mode else "OFF") + "`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def ban_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return

    target_id, reason, err = await resolve_target_id(update, context, context.args or [], with_reason=True)
    if not target_id:
        if err == "no_args":
            await update.message.reply_text(
                "*Usage:* `/ban <@username / user_id> [reason]`\n"
                "Or reply to a message: `/ban [reason]`\n\n"
                "Example: `/ban @drouv Spam karta tha` ya `/ban 98877655`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(err or "❌ *Invalid input!*", parse_mode="Markdown")
        return

    if target_id == ADMIN_ID:
        await update.message.reply_text("❌ *Cannot ban admin!*", parse_mode="Markdown")
        return

    ban_user_db(target_id, reason)
    reason_line = "\n*Reason:* `" + reason + "`" if reason else ""
    await update.message.reply_text(
        "✅ *User Banned!*\n\n*User ID:* `" + str(target_id) + "`" + reason_line + "\n\nThey can no longer use the bot.",
        parse_mode="Markdown",
    )
    try:
        notify = "🚫 *You have been banned from @racksunbot.*"
        if reason:
            notify += "\n*Reason:* `" + reason + "`"
        notify += "\n\nContact admin if you think this is a mistake."
        await context.bot.send_message(chat_id=target_id, text=notify, parse_mode="Markdown")
    except Exception:
        pass


async def unban_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return
    target_id, _, err = await resolve_target_id(update, context, context.args or [])
    if not target_id:
        if err == "no_args":
            await update.message.reply_text(
                "*Usage:* `/unban <@username / user_id>`\n"
                "Or reply to a message: `/unban`\n\n"
                "Example: `/unban @drouv` ya `/unban 98877655`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(err or "❌ *Invalid input!*", parse_mode="Markdown")
        return
    unban_user_db(target_id)
    await update.message.reply_text(
        "✅ *User Unbanned!*\n\n*User ID:* `" + str(target_id) + "`\n\nThey can now use the bot again.",
        parse_mode="Markdown",
    )
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="✅ *You have been unbanned from @racksunbot.*\n\nSend /start to use the bot.",
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def banlist_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return
    rows = get_banned_list_db()
    if not rows:
        await update.message.reply_text("✅ *No banned users.*", parse_mode="Markdown")
        return
    lines = ["🚫 *Banned Users List*\n"]
    for i, (uid, fname, uname, ban_reason) in enumerate(rows, 1):
        uname_display = "@" + uname if uname else "N/A"
        line = str(i) + ". `" + str(uid) + "` — " + val(fname) + " (" + uname_display + ")"
        if ban_reason:
            line += "\n    📌 Reason: " + ban_reason
        lines.append(line)
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def mute_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return

    target_id, reason, err = await resolve_target_id(update, context, context.args or [], with_reason=True)
    if not target_id:
        if err == "no_args":
            await update.message.reply_text(
                "*Usage:* `/mute <@username / user_id> [reason]`\n"
                "Or reply to a message: `/mute [reason]`\n\n"
                "Example: `/mute @drouv Spam kar raha tha` ya `/mute 98877655`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(err or "❌ *Invalid input!*", parse_mode="Markdown")
        return

    if target_id == ADMIN_ID:
        await update.message.reply_text("❌ *Cannot mute admin!*", parse_mode="Markdown")
        return

    row = get_user_info_db(target_id)
    target_name = val(row[1]) if row else str(target_id)

    mute_user_db(target_id, reason)
    reason_line = "\n*Reason:* `" + reason + "`" if reason else ""
    await update.message.reply_text(
        "🔇 *Muted " + target_name + ".*\n\n"
        "*User ID:* `" + str(target_id) + "`" + reason_line,
        parse_mode="Markdown",
    )
    try:
        notify = "🔇 *Shhh... quiet now.*\n\n*Muted " + target_name + ".*"
        if reason:
            notify += "\n*Reason:* `" + reason + "`"
        notify += "\n\nContact admin if you think this is a mistake."
        await context.bot.send_message(chat_id=target_id, text=notify, parse_mode="Markdown")
    except Exception:
        pass


async def unmute_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return

    target_id, _, err = await resolve_target_id(update, context, context.args or [])
    if not target_id:
        if err == "no_args":
            await update.message.reply_text(
                "*Usage:* `/unmute <@username / user_id>`\n"
                "Or reply to a message: `/unmute`\n\n"
                "Example: `/unmute @drouv` ya `/unmute 98877655`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(err or "❌ *Invalid input!*", parse_mode="Markdown")
        return

    unmute_user_db(target_id)
    await update.message.reply_text(
        "✅ *User Unmuted!*\n\n*User ID:* `" + str(target_id) + "`\n\nThey can now use the bot again.",
        parse_mode="Markdown",
    )
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="✅ *You have been unmuted from @racksunbot.*\n\nYou can use the bot again.",
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def mutelist_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return
    rows = get_muted_list_db()
    if not rows:
        await update.message.reply_text("✅ *No muted users.*", parse_mode="Markdown")
        return
    lines = ["🔇 *Muted Users List*\n"]
    for i, (uid, fname, uname, mute_reason) in enumerate(rows, 1):
        uname_display = "@" + uname if uname else "N/A"
        line = str(i) + ". `" + str(uid) + "` — " + val(fname) + " (" + uname_display + ")"
        if mute_reason:
            line += "\n    📌 Reason: " + mute_reason
        lines.append(line)
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def warn_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return

    target_id, reason, err = await resolve_target_id(update, context, context.args or [], with_reason=True)
    if not target_id:
        if err == "no_args":
            await update.message.reply_text(
                "*Usage:* `/warn <@username / user_id> [reason]`\n"
                "Or reply to a message: `/warn [reason]`\n\n"
                "Example: `/warn @drouv Rules tod raha tha` ya `/warn 98877655`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(err or "❌ *Invalid input!*", parse_mode="Markdown")
        return

    if target_id == ADMIN_ID:
        await update.message.reply_text("❌ *Cannot warn admin!*", parse_mode="Markdown")
        return

    row = get_user_info_db(target_id)
    if not row:
        await update.message.reply_text(
            "❌ *User not found.*\n\nIs user ne pehle bot use nahi kiya.",
            parse_mode="Markdown",
        )
        return

    target_name = val(row[1]) if row else str(target_id)
    warn_count = add_warn_db(target_id)
    MAX_WARNS = 2
    reason_line = "\n*Reason:* `" + reason + "`" if reason else ""

    if warn_count >= MAX_WARNS:
        ban_user_db(target_id, "Auto-banned after 2 warnings")
        reset_warn_db(target_id)
        await update.message.reply_text(
            "🚫 *" + target_name + " has been auto-banned!*\n\n"
            "*User ID:* `" + str(target_id) + "`\n"
            "*Warnings:* `2/2`\n"
            "*Reason:* `Auto-banned after 2 warnings`",
            parse_mode="Markdown",
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🚫 *You have been banned from @racksunbot.*\n\n"
                     "*Reason:* `Auto-banned after 2 warnings`\n\n"
                     "Contact the admin if you think this is a mistake.",
                parse_mode="Markdown",
            )
        except Exception:
            pass
    else:
        remaining = MAX_WARNS - warn_count
        warn_bar = "⚠️ " * warn_count + "⬜ " * remaining
        await update.message.reply_text(
            "⚠️ *Warning issued to " + target_name + "!*\n\n"
            "*User ID:* `" + str(target_id) + "`" + reason_line + "\n"
            "*Warnings:* `" + str(warn_count) + "/" + str(MAX_WARNS) + "`\n"
            "*Progress:* " + warn_bar + "\n\n"
            "_" + str(remaining) + " more warning(s) will result in auto-ban._",
            parse_mode="Markdown",
        )
        try:
            notify = (
                "⚠️ *You have received a warning!*\n\n"
                "*Bot:* @racksunbot" + reason_line + "\n"
                "*Warnings:* `" + str(warn_count) + "/" + str(MAX_WARNS) + "`\n"
                "*Progress:* " + warn_bar + "\n\n"
                "_" + str(remaining) + " more warning(s) will result in auto-ban._"
            )
            await context.bot.send_message(chat_id=target_id, text=notify, parse_mode="Markdown")
        except Exception:
            pass


async def warns_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return

    target_id, _, err = await resolve_target_id(update, context, context.args or [])
    if not target_id:
        if err == "no_args":
            await update.message.reply_text(
                "*Usage:* `/warns <@username / user_id>`\n"
                "Or reply to a message: `/warns`\n\n"
                "Example: `/warns @drouv` ya `/warns 98877655`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(err or "❌ *Invalid input!*", parse_mode="Markdown")
        return

    row = get_user_info_db(target_id)
    target_name = val(row[1]) if row else str(target_id)
    warn_count = get_warn_count_db(target_id)
    MAX_WARNS = 2
    warn_bar = "⚠️ " * warn_count + "⬜ " * (MAX_WARNS - warn_count)

    await update.message.reply_text(
        "⚠️ *Warnings for " + target_name + "*\n\n"
        "*User ID:* `" + str(target_id) + "`\n"
        "*Warnings:* `" + str(warn_count) + "/" + str(MAX_WARNS) + "`\n"
        "*Progress:* " + warn_bar,
        parse_mode="Markdown",
    )


async def resetwarn_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return

    target_id, _, err = await resolve_target_id(update, context, context.args or [])
    if not target_id:
        if err == "no_args":
            await update.message.reply_text(
                "*Usage:* `/resetwarn <@username / user_id>`\n"
                "Or reply to a message: `/resetwarn`\n\n"
                "Example: `/resetwarn @drouv` ya `/resetwarn 98877655`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(err or "❌ *Invalid input!*", parse_mode="Markdown")
        return

    row = get_user_info_db(target_id)
    target_name = val(row[1]) if row else str(target_id)
    reset_warn_db(target_id)
    await update.message.reply_text(
        "✅ *Warnings reset for " + target_name + "!*\n\n"
        "*User ID:* `" + str(target_id) + "`\n"
        "*Warnings:* `0/2`",
        parse_mode="Markdown",
    )


async def adminhelp_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return
    text = (
        "🛡 *Admin Commands*\n\n"
        "━━━━━━━━━━━━━━━\n"
        "⚠️ *WARN SYSTEM*\n"
        "━━━━━━━━━━━━━━━\n"
        "`/warn` — Warning do _(reply ya ID, reason optional)_\n"
        "  3 warnings = auto ban ⚠️⚠️⚠️\n\n"
        "`/warns` — Kisi ki warnings dekho _(reply ya ID)_\n\n"
        "`/resetwarn` — Warnings reset karo _(reply ya ID)_\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🚫 *BAN SYSTEM*\n"
        "━━━━━━━━━━━━━━━\n"
        "`/ban` — Ban karo _(reply ya ID, reason optional)_\n\n"
        "`/unban` — Unban karo _(reply ya ID)_\n\n"
        "`/banlist` — Saare banned users\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🔇 *MUTE SYSTEM*\n"
        "━━━━━━━━━━━━━━━\n"
        "`/mute` — Mute karo _(reply ya ID, reason optional)_\n\n"
        "`/unmute` — Unmute karo _(reply ya ID)_\n\n"
        "`/mutelist` — Saare muted users\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *OTHER ADMIN*\n"
        "━━━━━━━━━━━━━━━\n"
        "`/stats` — Bot stats\n\n"
        "`/info` — Kisi ki info _(reply ya ID)_\n\n"
        "`/reply` — User ko message bhejo\n\n"
        "`/broadcast` — Sab ko message\n\n"
        "`/maintenance on/off` — Bot band/chalu\n\n"
        "━━━━━━━━━━━━━━━\n"
        "_Tip: Reply karke command use karo — ID yaad nahi rakhna padega!_"
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
    number = context.args[0].replace("+", "").replace(" ", "").replace("-", "")
    searching = await update.message.reply_text("🔍 Searching...")

    entries = []

    try:
        url2 = NUMBER_API_URL2.format(number=number)
        res2 = await asyncio.to_thread(requests.get, url2, timeout=15)
        data2 = res2.json()
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
            res = await asyncio.to_thread(requests.get, url, timeout=15)
            data = res.json()
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
        await update.message.reply_text("*Data Not Found!*\n\nNo information found for this number.", parse_mode="Markdown")
        return

    increment_search(user_id)

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
    aadhar = context.args[0].replace(" ", "").replace("-", "")
    searching = await update.message.reply_text("🔍 Searching...")
    try:
        url = AADHAR_API_URL.format(aadhar=aadhar)
        res = await asyncio.to_thread(requests.get, url, timeout=15)
        data = res.json()
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
        await update.message.reply_text("*Data Not Found!*\n\nNo information found for this Aadhar.", parse_mode="Markdown")
        return

    increment_search(user_id)

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


async def ifsc_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text("*Usage:* `/ifsc SBIN0001234`", parse_mode="Markdown")
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    ifsc = context.args[0].strip().upper()
    searching = await update.message.reply_text("🔍 Searching...")
    try:
        url = IFSC_API_URL.format(ifsc=ifsc)
        res = await asyncio.to_thread(requests.get, url, timeout=15)
        data = res.json()
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "ifsc_lookup: " + str(e))
        return

    bank = None
    if isinstance(data, dict) and data.get("success"):
        bank = data.get("data")

    await delete_msg(context, chat_id, searching.message_id)

    if not bank:
        await update.message.reply_text("*Data Not Found!*\n\nNo information found for this IFSC code.", parse_mode="Markdown")
        return

    increment_search(user_id)

    def yesno(v):
        if v is True:
            return "✅ Yes"
        if v is False:
            return "❌ No"
        return "None"

    text = (
        "🏦 *Bank / IFSC Info*\n\n"
        "*IFSC:* `" + val(bank.get("IFSC")) + "`\n"
        "*Bank:* `" + val(bank.get("BANK")) + "`\n"
        "*Branch:* `" + val(bank.get("BRANCH")) + "`\n"
        "*Address:* `" + val(bank.get("ADDRESS")) + "`\n"
        "*City:* `" + val(bank.get("CITY")) + "`\n"
        "*District:* `" + val(bank.get("DISTRICT")) + "`\n"
        "*State:* `" + val(bank.get("STATE")) + "`\n"
        "*MICR:* `" + val(bank.get("MICR")) + "`\n"
        "*SWIFT:* `" + val(bank.get("SWIFT")) + "`\n\n"
        "*UPI:* " + yesno(bank.get("UPI")) + "\n"
        "*NEFT:* " + yesno(bank.get("NEFT")) + "\n"
        "*RTGS:* " + yesno(bank.get("RTGS")) + "\n"
        "*IMPS:* " + yesno(bank.get("IMPS"))
    )
    await update.message.reply_text(text, parse_mode="Markdown")


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
    chat_type = update.message.chat.type
    bot_username = (await context.bot.get_me()).username

    if chat_type in ["group", "supergroup"]:
        if "@" + bot_username.lower() not in user_input.lower():
            return
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
        res = await asyncio.to_thread(requests.get, api_url, timeout=15)
        data = res.json()
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nCould not reach the lookup server. Try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    # Check for error / not found
    if isinstance(data, dict):
        status = str(data.get("status", "")).lower()
        msg = str(data.get("message", "") or data.get("msg", "") or data.get("error", "")).lower()
        if status in ("false", "0", "error", "fail", "failed") or "not found" in msg or "invalid" in msg or "no data" in msg:
            await update.message.reply_text("*Data Not Found!*\n\nNo data linked to this Telegram account.", parse_mode="Markdown")
            return
        if not data or (isinstance(data.get("data"), (list, dict)) and not data.get("data")):
            await update.message.reply_text("*Data Not Found!*\n\nNo data linked to this Telegram account.", parse_mode="Markdown")
            return

    increment_search(user_id)

    # Build result from whatever the API returns
    SKIP_KEYS = {"status", "message", "msg", "error", "success", "code", "key", "type"}
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
        await update.message.reply_text("*Data Not Found!*\n\nNo data linked to this Telegram account.", parse_mode="Markdown")
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


if __name__ == "__main__":
    init_db()
    keep_alive()
    print("Flask Server Started!")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("num", num_lookup))
    app.add_handler(CommandHandler("aadhar", aadhar_lookup))
    app.add_handler(CommandHandler("ifsc", ifsc_lookup))
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
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("banlist", banlist_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("unmute", unmute_command))
    app.add_handler(CommandHandler("mutelist", mutelist_command))
    app.add_handler(CommandHandler("warn", warn_command))
    app.add_handler(CommandHandler("warns", warns_command))
    app.add_handler(CommandHandler("resetwarn", resetwarn_command))
    app.add_handler(CommandHandler("adminhelp", adminhelp_command))
    app.add_handler(CommandHandler("maintenance", maintenance_command))
    app.add_handler(CallbackQueryHandler(check_joined_callback, pattern="check_joined"))
    app.add_handler(MessageHandler(filters.StatusUpdate.USERS_SHARED, handle_users_shared))
    app.add_handler(MessageHandler(filters.StatusUpdate.CHAT_SHARED, handle_chat_shared))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lookup))
    print("Bot is Online!")
    app.run_polling()
