import telebot
from telebot import types
import threading
import time
from datetime import datetime
import pytz
import logging
import re
import json
import os

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = [6411315434, 6616366458, 6569503326]

IST = pytz.timezone("Asia/Kolkata")
CHANNELS_FILE = "target_channels.json"
SCHEDULED_POSTS_FILE = "scheduled_posts.json"

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

timers = {}
user_data = {}

# ================= LOAD / SAVE =================
def load_json(file, default):
    if os.path.exists(file):
        try:
            with open(file, "r") as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

TARGET_CHANNELS = load_json(CHANNELS_FILE, [])
SCHEDULED_POSTS = load_json(SCHEDULED_POSTS_FILE, [])

# ================= HELPERS =================
def is_admin(uid):
    return uid in ADMIN_IDS

def parse_telegram_link(link):
    m1 = re.match(r"https://t\.me/([a-zA-Z0-9_]+)/(\d+)", link)
    if m1:
        return f"@{m1.group(1)}", int(m1.group(2))

    m2 = re.match(r"https://t\.me/c/(\d+)/(\d+)", link)
    if m2:
        return int(f"-100{m2.group(1)}"), int(m2.group(2))

    return None, None

# ================= RESTORE TIMERS AFTER RESTART =================
def restore_scheduled_posts():
    now = datetime.now(IST)
    for idx, post in enumerate(SCHEDULED_POSTS):
        try:
            run_time = IST.localize(datetime.strptime(post["run_time"], "%Y-%m-%d %H:%M"))
            delay = (run_time - now).total_seconds()

            if delay <= 0:
                logger.info(f"Skipping expired post {idx+1}")
                continue

            t = threading.Timer(delay, publish, [post, idx])
            timers[idx] = t
            t.start()
            logger.info(f"Restored scheduled post {idx+1} | Runs at {post['run_time']} IST")

        except Exception as e:
            logger.error(f"Restore error: {e}")

# ================= COMMANDS =================
@bot.message_handler(commands=["start"])
def start(m):
    if not is_admin(m.from_user.id):
        return
    bot.reply_to(
        m,
        "🤖 Schedule Bot Ready\n\n"
        "Commands:\n"
        "/addchannel - Add new channel\n"
        "/mychannels - Show added channels\n"
        "/schedule - Schedule a post\n"
        "/scheduled - View scheduled posts"
    )

@bot.message_handler(commands=["addchannel"])
def addchannel(m):
    if not is_admin(m.from_user.id):
        return
    user_data[m.chat.id] = {"step": "add_channel"}
    bot.reply_to(m, "Send channel ID or @username\nExample: @MyChannel or -1001234567890")

@bot.message_handler(commands=["mychannels"])
def mychannels(m):
    if not is_admin(m.from_user.id):
        return
    if not TARGET_CHANNELS:
        bot.reply_to(m, "No channels added yet.")
        return

    text = "📢 Target Channels:\n\n"
    for i, c in enumerate(TARGET_CHANNELS, 1):
        text += f"{i}. {c['display_name']} ({c['id']})\n"
    bot.reply_to(m, text)

@bot.message_handler(commands=["scheduled"])
def show_scheduled(m):
    if not is_admin(m.from_user.id):
        return

    if not SCHEDULED_POSTS:
        bot.reply_to(m, "No scheduled posts.")
        return

    text = "🗓 Scheduled Posts:\n\n"
    kb = types.InlineKeyboardMarkup(row_width=1)

    for i, post in enumerate(SCHEDULED_POSTS):
        text += f"{i+1}. {post['run_time']} IST\n"
        text += f"Target: {post['target_channel']}\n"
        text += f"Source: {post['src_channel']} | Msg: {post['msg_id']}\n\n"

        kb.add(types.InlineKeyboardButton(
            f"❌ Delete Post {i+1}",
            callback_data=f"delete:{i}"
        ))

    bot.send_message(m.chat.id, text, reply_markup=kb)

@bot.message_handler(commands=["schedule"])
def schedule(m):
    if not is_admin(m.from_user.id):
        return

    if not TARGET_CHANNELS:
        bot.reply_to(m, "First add a channel using /addchannel")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for i, c in enumerate(TARGET_CHANNELS):
        kb.add(types.InlineKeyboardButton(c["display_name"], callback_data=f"sch:{i}"))

    bot.reply_to(m, "Select target channel:", reply_markup=kb)

# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda c: True)
def callbacks(c):
    if not is_admin(c.from_user.id):
        return

    if c.data.startswith("sch:"):
        idx = int(c.data.split(":")[1])
        user_data[c.message.chat.id] = {
            "step": "wait_link",
            "target_channel": TARGET_CHANNELS[idx]["id"],
            "buttons": []
        }
        bot.edit_message_text("Send Telegram post link to copy", c.message.chat.id, c.message.message_id)

    elif c.data.startswith("delete:"):
        post_idx = int(c.data.split(":")[1])
        if post_idx < len(SCHEDULED_POSTS):
            if post_idx in timers:
                timers[post_idx].cancel()
                timers.pop(post_idx, None)

            SCHEDULED_POSTS.pop(post_idx)
            save_json(SCHEDULED_POSTS_FILE, SCHEDULED_POSTS)
            bot.answer_callback_query(c.id, "Deleted successfully", show_alert=True)

# ================= MESSAGE FLOW =================
@bot.message_handler(func=lambda m: True)
def flow(m):
    if m.chat.id not in user_data or not is_admin(m.from_user.id):
        return

    d = user_data[m.chat.id]

    if d["step"] == "add_channel":
        ch_id = m.text.strip()
        display = ch_id
        try:
            chat = bot.get_chat(ch_id)
            display = chat.title or ch_id
        except:
            pass

        TARGET_CHANNELS.append({"id": ch_id, "display_name": display})
        save_json(CHANNELS_FILE, TARGET_CHANNELS)
        bot.reply_to(m, f"✅ Channel Added: {display}")
        user_data.pop(m.chat.id)

    elif d["step"] == "wait_link":
        src, msg_id = parse_telegram_link(m.text)
        if not src:
            bot.reply_to(m, "Invalid Telegram link.")
            return

        d["src_channel"] = src
        d["msg_id"] = msg_id
        d["step"] = "time"
        bot.reply_to(m, "Send schedule time:\nFormat: YYYY-MM-DD HH:MM\nExample: 2026-03-01 18:30")

    elif d["step"] == "time":
        try:
            run_time = IST.localize(datetime.strptime(m.text.strip(), "%Y-%m-%d %H:%M"))
            delay = (run_time - datetime.now(IST)).total_seconds()

            if delay <= 0:
                bot.reply_to(m, "Time must be in future.")
                return

        except:
            bot.reply_to(m, "Wrong format! Use YYYY-MM-DD HH:MM")
            return

        post = {
            "target_channel": d["target_channel"],
            "src_channel": d["src_channel"],
            "msg_id": d["msg_id"],
            "buttons": [],
            "run_time": run_time.strftime("%Y-%m-%d %H:%M")
        }

        SCHEDULED_POSTS.append(post)
        idx = len(SCHEDULED_POSTS) - 1
        save_json(SCHEDULED_POSTS_FILE, SCHEDULED_POSTS)

        t = threading.Timer(delay, publish, [post, idx])
        timers[idx] = t
        t.start()

        bot.reply_to(m, f"✅ Scheduled for {post['run_time']} IST")
        user_data.pop(m.chat.id)

# ================= PUBLISH =================
def publish(p, idx):
    try:
        bot.copy_message(
            chat_id=p["target_channel"],
            from_chat_id=p["src_channel"],
            message_id=p["msg_id"]
        )

        logger.info(f"Posted to {p['target_channel']}")

        if idx < len(SCHEDULED_POSTS):
            SCHEDULED_POSTS.pop(idx)
            save_json(SCHEDULED_POSTS_FILE, SCHEDULED_POSTS)

        timers.pop(idx, None)

    except Exception as e:
        logger.error(f"Publish failed: {e}")

# ================= START =================
print("🚀 Bot is running on Render...")

restore_scheduled_posts()

while True:
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=20)
    except Exception as e:
        logger.error(f"Polling error: {e}")
        time.sleep(5)
