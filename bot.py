import os
import re
import asyncio
import requests
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
ANON_TG_API = "https://anon-tg-info.vercel.app/tg2num/userid?key=temp40098&q={info}"


CHANNEL_USERNAME = "@racksun19"
CHANNEL_LINK = "https://t.me/racksun19"
GROUP_USERNAME = "@racksungroup"
GROUP_LINK = "https://t.me/racksungroup"

USERS_FILE = "users.txt"
known_users = set()


def load_users():
    global known_users
    if not os.path.exists(USERS_FILE):
        return
    f = open(USERS_FILE, "r")
    for line in f:
        line = line.strip()
        if line.isdigit():
            known_users.add(int(line))
    f.close()


def track_user(user_id):
    if not user_id:
        return
    if user_id in known_users:
        return
    known_users.add(user_id)
    f = open(USERS_FILE, "a")
    f.write(str(user_id) + "\n")
    f.close()


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
    if cleaned:
        return cleaned
    return "None"


def val(v):
    if v is None or str(v).strip() == "":
        return "None"
    return str(v).strip()


async def delete_searching(context, chat_id, msg_id):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
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
        [InlineKeyboardButton("✅ I have Joined", callback_data="check_joined")]
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
        parse_mode="Markdown"
    )


async def check_joined_callback(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    track_user(user_id)
    member_ok = await is_member(user_id, context)
    if not member_ok:
        await query.answer("❌ You have not joined yet! Please join first.", show_alert=True)
        return
    await query.message.delete()
    context.user_data.pop("join_msg_id", None)
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="✅ *You have successfully joined our channel!*\n\nYou can now use the bot freely. Send /start to begin.",
        parse_mode="Markdown"
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
    welcome_msg = "".join(parts)
    await update.message.reply_text(welcome_msg, reply_markup=main_menu_markup(), parse_mode="Markdown")


async def start(update, context):
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
    context.user_data.clear()
    await show_main_menu(update, context)


async def back_command(update, context):
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
    await show_main_menu(update, context, header="🔙 *Back to main menu.*")


async def cancel_command(update, context):
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
    context.user_data.clear()
    await show_main_menu(update, context, header="❌ *Cancelled.*")


async def settings_command(update, context):
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
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
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
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
        "  /report      — Report an issue to admin\n"
        "  /settings    — Show bot features\n"
        "  /back        — Back to main menu\n"
        "  /cancel      — Cancel current action\n"
        "  /help        — Show this help message"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def stats_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    msg = "📊 *Bot Stats*\n\n*Total Users:* `" + str(len(known_users)) + "`"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def report_command(update, context):
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
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
    full_name = user.first_name or ""
    if user.last_name:
        full_name = full_name + " " + user.last_name
    if not full_name.strip():
        full_name = "Unknown"
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
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ *Failed to send report.*\nPlease try again after some time.",
            parse_mode="Markdown"
        )
        print("Report send error:", str(e))


async def reply_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "*Usage:* `/reply <user_id> <your message>`\n\n"
            "*Example:*\n"
            "`/reply 1234567890 Thanks, we have fixed the issue!`",
            parse_mode="Markdown"
        )
        return
    target_id = context.args[0]
    if not target_id.isdigit():
        await update.message.reply_text("❌ *Invalid User ID!*\nPlease enter a valid numeric User ID.", parse_mode="Markdown")
        return
    message = " ".join(context.args[1:])
    reply_text = "💬 *Reply from Admin*\n\n" + message
    try:
        await context.bot.send_message(chat_id=int(target_id), text=reply_text, parse_mode="Markdown")
        await update.message.reply_text(
            "✅ *Reply sent successfully!*\n\n"
            "*Sent to User ID:* `" + target_id + "`\n"
            "*Message:* " + message,
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ *Failed to send reply.*\n\n"
            "User may have blocked the bot or ID is wrong.\n"
            "*Error:* " + str(e),
            parse_mode="Markdown"
        )


async def num_lookup(update, context):
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
    if not context.args:
        await update.message.reply_text("*Usage:* `/num 9876543219`", parse_mode="Markdown")
        return
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
                entry = {
                    "name": r.get("NAME") or r.get("name"),
                    "father": r.get("fname"),
                    "mobile": r.get("MOBILE") or r.get("mobile"),
                    "alt": r.get("alt"),
                    "aadhar": r.get("id"),
                    "email": r.get("email"),
                    "circle": r.get("circle"),
                    "address": r.get("ADDRESS") or r.get("address"),
                }
                entries.append(entry)
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
                    entry = {
                        "name": r.get("NAME") or r.get("name"),
                        "father": r.get("fname"),
                        "mobile": r.get("MOBILE") or r.get("mobile"),
                        "alt": r.get("alt"),
                        "aadhar": r.get("id"),
                        "email": r.get("email"),
                        "circle": r.get("circle"),
                        "address": r.get("ADDRESS") or r.get("address"),
                    }
                    entries.append(entry)
        except Exception:
            pass

    if not entries:
        await delete_searching(context, chat_id, searching.message_id)
        await update.message.reply_text("*Data Not Found!*\n\nNo information found for this number.", parse_mode="Markdown")
        return

    await delete_searching(context, chat_id, searching.message_id)

    i = 0
    for entry in entries:
        i = i + 1
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
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
    if not context.args:
        await update.message.reply_text("*Usage:* `/aadhar 652507323571`", parse_mode="Markdown")
        return
    aadhar = context.args[0].replace(" ", "").replace("-", "")
    searching = await update.message.reply_text("🔍 Searching...")
    try:
        url = AADHAR_API_URL.format(aadhar=aadhar)
        res = await asyncio.to_thread(requests.get, url, timeout=15)
        data = res.json()
    except Exception:
        await delete_searching(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
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
    if not entries:
        await delete_searching(context, chat_id, searching.message_id)
        await update.message.reply_text("*Data Not Found!*\n\nNo information found for this Aadhar.", parse_mode="Markdown")
        return

    await delete_searching(context, chat_id, searching.message_id)

    i = 0
    for entry in entries:
        i = i + 1
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
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
    if not context.args:
        await update.message.reply_text("*Usage:* `/ifsc SBIN0001234`", parse_mode="Markdown")
        return
    ifsc = context.args[0].strip().upper()
    searching = await update.message.reply_text("🔍 Searching...")
    try:
        url = IFSC_API_URL.format(ifsc=ifsc)
        res = await asyncio.to_thread(requests.get, url, timeout=15)
        data = res.json()
    except Exception:
        await delete_searching(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        return
    bank = None
    if isinstance(data, dict) and data.get("success"):
        bank = data.get("data")
    if not bank:
        await delete_searching(context, chat_id, searching.message_id)
        await update.message.reply_text("*Data Not Found!*\n\nNo information found for this IFSC code.", parse_mode="Markdown")
        return
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
    await delete_searching(context, chat_id, searching.message_id)
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_users_shared(update, context):
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
    if update.message.users_shared:
        for user in update.message.users_shared.users:
            await update.message.reply_text("*User ID:* `" + str(user.user_id) + "`", parse_mode="Markdown")


async def handle_chat_shared(update, context):
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
    if update.message.chat_shared:
        await update.message.reply_text("*Chat ID:* `" + str(update.message.chat_shared.chat_id) + "`", parse_mode="Markdown")


async def lookup(update, context):
    user_id = update.message.from_user.id
    track_user(user_id)
    chat_id = update.message.chat_id
    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return
    await delete_join_message(context, chat_id)
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

    tg_id = None
    if is_username:
        try:
            chat_obj = await context.bot.get_chat(user_input)
            tg_id = chat_obj.id
        except Exception:
            await delete_searching(context, chat_id, searching.message_id)
            await update.message.reply_text("*Data Not Found!*\n\nUsername not found or is private.", parse_mode="Markdown")
            return
    else:
        tg_id = digits_only

    try:
        api_url = ANON_TG_API.format(info=str(tg_id))
        res = await asyncio.to_thread(requests.get, api_url, timeout=15)
        data = res.json()
    except Exception:
        await delete_searching(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nCould not reach the lookup server. Try again later.", parse_mode="Markdown")
        return

    await delete_searching(context, chat_id, searching.message_id)

    entry = None
    if isinstance(data, dict):
        resp = data.get("response") or {}
        params = resp.get("parameters") or {}
        results = resp.get("data") or []
        if params.get("success") and isinstance(results, list) and len(results) > 0:
            entry = results[0]

    if not entry or not entry.get("number"):
        await update.message.reply_text("*Data Not Found!*\n\nNo phone number linked to this Telegram account.", parse_mode="Markdown")
        return

    phone = entry.get("number")
    country = entry.get("country")
    country_code = entry.get("country_code")

    text = (
        "*Result:*\n\n"
        "*Tg Id:* `" + str(tg_id) + "`\n"
        "*Country:* `" + val(country) + "`\n"
        "*Country Code:* `" + val(country_code) + "`\n"
        "*Number:* `" + val(phone) + "`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def broadcast_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "📢 *Broadcast Usage:*\n\n`/broadcast Aapka message yahan`",
            parse_mode="Markdown"
        )
        return
    message = " ".join(context.args)
    if not os.path.exists(USERS_FILE):
        await update.message.reply_text("❌ *No users found!*\n\nusers.txt file nahi mili.", parse_mode="Markdown")
        return
    f = open(USERS_FILE, "r")
    user_ids = []
    for line in f:
        line = line.strip()
        if line.isdigit():
            user_ids.append(int(line))
    f.close()
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
        parse_mode="Markdown"
    )


if __name__ == "__main__":
    load_users()
    keep_alive()
    print("Flask Server Started!")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("num", num_lookup))
    app.add_handler(CommandHandler("aadhar", aadhar_lookup))
    app.add_handler(CommandHandler("ifsc", ifsc_lookup))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("back", back_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("reply", reply_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CallbackQueryHandler(check_joined_callback, pattern="check_joined"))
    app.add_handler(MessageHandler(filters.StatusUpdate.USERS_SHARED, handle_users_shared))
    app.add_handler(MessageHandler(filters.StatusUpdate.CHAT_SHARED, handle_chat_shared))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lookup))
    print("Bot is Online!")
    app.run_polling()
