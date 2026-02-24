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
from flask import Flask

# ================= RENDER PORT FIX (FREE WEB SERVICE) =================
app = Flask(__name__)

@app.route('/')
def home():
    return "Advanced Schedule Bot Running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN") or "PUT_YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = [6411315434, 6616366458, 6569503326]

IST = pytz.timezone("Asia/Kolkata")
CHANNELS_FILE = "target_channels.json"
SCHEDULED_POSTS_FILE = "scheduled_posts.json"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_data = {}
timers = {}

# ================= JSON DATABASE =================
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

def parse_link(link):
    m = re.match(r"https://t\.me/([a-zA-Z0-9_]+)/(\d+)", link)
    if m:
        return f"@{m.group(1)}", int(m.group(2))
    m2 = re.match(r"https://t\.me/c/(\d+)/(\d+)", link)
    if m2:
        return int(f"-100{m2.group(1)}"), int(m2.group(2))
    return None, None

# ================= RESTORE SCHEDULE AFTER RESTART =================
def restore_scheduled():
    now = datetime.now(IST)
    for post in SCHEDULED_POSTS:
        try:
            run_time = IST.localize(datetime.strptime(post["time"], "%Y-%m-%d %H:%M"))
            delay = (run_time - now).total_seconds()
            if delay > 0:
                t = threading.Timer(delay, publish, [post])
                t.start()
                timers[post["time"]] = t
        except Exception as e:
            logger.error(f"Restore error: {e}")

# ================= START COMMAND =================
@bot.message_handler(commands=["start"])
def start(m):
    if not is_admin(m.from_user.id):
        return
    bot.reply_to(
        m,
        "🤖 <b>Advanced Schedule Bot</b>\n\n"
        "/addchannel - Add target channel\n"
        "/mychannels - View added channels\n"
        "/schedule - Create scheduled post"
    )

# ================= ADD CHANNEL =================
@bot.message_handler(commands=["addchannel"])
def add_channel(m):
    if not is_admin(m.from_user.id):
        return
    user_data[m.chat.id] = {"step": "add_channel"}
    bot.reply_to(m, "Send target channel @username or -100 channel id")

# ================= VIEW CHANNELS =================
@bot.message_handler(commands=["mychannels"])
def mychannels(m):
    if not is_admin(m.from_user.id):
        return
    if not TARGET_CHANNELS:
        bot.reply_to(m, "No channels added yet.")
        return

    text = "<b>Target Channels:</b>\n\n"
    for i, ch in enumerate(TARGET_CHANNELS, 1):
        text += f"{i}. {ch['name']} (<code>{ch['id']}</code>)\n"
    bot.reply_to(m, text)

# ================= SCHEDULE COMMAND =================
@bot.message_handler(commands=["schedule"])
def schedule_cmd(m):
    if not is_admin(m.from_user.id):
        return

    if not TARGET_CHANNELS:
        bot.reply_to(m, "First add a channel using /addchannel")
        return

    kb = types.InlineKeyboardMarkup()
    for i, ch in enumerate(TARGET_CHANNELS):
        kb.add(types.InlineKeyboardButton(ch["name"], callback_data=f"target_{i}"))

    bot.reply_to(m, "Select target channel:", reply_markup=kb)

# ================= CALLBACK HANDLER =================
@bot.callback_query_handler(func=lambda c: True)
def callbacks(c):
    if not is_admin(c.from_user.id):
        return

    if c.data.startswith("target_"):
        idx = int(c.data.split("_")[1])
        user_data[c.message.chat.id] = {
            "step": "post_link",
            "target": TARGET_CHANNELS[idx]["id"],
            "buttons": []
        }
        bot.edit_message_text(
            "📩 Send PUBLIC channel post link (round video/photo/any post)",
            c.message.chat.id,
            c.message.message_id
        )

# ================= MAIN FLOW =================
@bot.message_handler(func=lambda m: True)
def flow(m):
    if m.chat.id not in user_data or not is_admin(m.from_user.id):
        return

    d = user_data[m.chat.id]

    # ADD CHANNEL
    if d["step"] == "add_channel":
        ch = m.text.strip()
        try:
            chat = bot.get_chat(ch)
            name = chat.title
        except:
            name = ch

        TARGET_CHANNELS.append({"id": ch, "name": name})
        save_json(CHANNELS_FILE, TARGET_CHANNELS)
        bot.reply_to(m, f"✅ Channel Added: {name}")
        user_data.pop(m.chat.id)
        return

    # STEP 1: GET POST LINK FIRST (AS YOU REQUESTED)
    if d["step"] == "post_link":
        src, msg_id = parse_link(m.text)
        if not src:
            bot.reply_to(m, "❌ Invalid public channel post link.")
            return

        d["src"] = src
        d["msg_id"] = msg_id
        d["step"] = "ask_buttons"
        bot.reply_to(m, "Do you want to add inline buttons? (yes/no)")
        return

    # STEP 2: ASK BUTTONS YES/NO
    if d["step"] == "ask_buttons":
        if m.text.lower() in ["yes", "y"]:
            d["step"] = "btn_text"
            bot.reply_to(m, "Send Button Text:")
        else:
            d["step"] = "get_time"
            bot.reply_to(m, "Send Schedule Time:\nFormat: YYYY-MM-DD HH:MM")
        return

    # STEP 3: BUTTON TEXT
    if d["step"] == "btn_text":
        d["temp_text"] = m.text
        d["step"] = "btn_url"
        bot.reply_to(m, "Send Button URL (https://...)")
        return

    # STEP 4: BUTTON URL + MULTIPLE BUTTON SUPPORT
    if d["step"] == "btn_url":
        d["buttons"].append({
            "text": d["temp_text"],
            "url": m.text
        })
        d["step"] = "more_buttons"
        bot.reply_to(m, "Add more buttons? (yes/no)")
        return

    if d["step"] == "more_buttons":
        if m.text.lower() in ["yes", "y"]:
            d["step"] = "btn_text"
            bot.reply_to(m, "Send Next Button Text:")
        else:
            d["step"] = "get_time"
            bot.reply_to(m, "Now send Schedule Time:\nFormat: YYYY-MM-DD HH:MM")
        return

    # STEP 5: SCHEDULE TIME
    if d["step"] == "get_time":
        try:
            run_time = IST.localize(datetime.strptime(m.text, "%Y-%m-%d %H:%M"))
        except:
            bot.reply_to(m, "❌ Wrong format! Use YYYY-MM-DD HH:MM")
            return

        delay = (run_time - datetime.now(IST)).total_seconds()
        if delay <= 0:
            bot.reply_to(m, "❌ Time must be in future.")
            return

        post = {
            "target": d["target"],
            "src": d["src"],
            "msg_id": d["msg_id"],
            "buttons": d["buttons"],
            "time": run_time.strftime("%Y-%m-%d %H:%M")
        }

        SCHEDULED_POSTS.append(post)
        save_json(SCHEDULED_POSTS_FILE, SCHEDULED_POSTS)

        t = threading.Timer(delay, publish, [post])
        t.start()

        bot.reply_to(m, "✅ Post Scheduled Successfully with Multiple Buttons!")
        user_data.pop(m.chat.id)

# ================= PUBLISH FUNCTION =================
def publish(p):
    try:
        markup = None
        if p["buttons"]:
            markup = types.InlineKeyboardMarkup()
            for b in p["buttons"]:
                markup.add(types.InlineKeyboardButton(b["text"], url=b["url"]))

        sent = bot.copy_message(
            chat_id=p["target"],
            from_chat_id=p["src"],
            message_id=p["msg_id"]
        )

        if markup:
            bot.edit_message_reply_markup(
                chat_id=p["target"],
                message_id=sent.message_id,
                reply_markup=markup
            )

        logger.info(f"Post published to {p['target']}")

    except Exception as e:
        logger.error(f"Publish failed: {e}")

# ================= START BOT =================
print("🚀 Advanced Render Scheduler Bot Running...")

restore_scheduled()

while True:
    try:
        bot.remove_webhook()
        bot.infinity_polling(
            timeout=30,
            long_polling_timeout=30,
            skip_pending=True,
            none_stop=True
        )
    except Exception as e:
        logger.error(f"Polling Error: {e}")
        time.sleep(10)
