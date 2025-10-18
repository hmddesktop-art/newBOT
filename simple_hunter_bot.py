#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# wolfcardbot.py - Extracts Werewolf for Telegram Stats & Displays in Chat
# author - Carson True
# license - GPL

# edited by @jeffffc
# /search by @jamiscs
# /info by @Olgabrezel

import requests
import logging
import sqlite3
import collections 
import re 
import time
import random  # اضافه شده برای انتخاب رندوم

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import datetime 
import json
import html

from unidecode import unidecode
# ⚠️ فرض بر این است که config.py شامل BOT_TOKEN, LOG_GROUP_ID و MAIN_ADMIN_ID است.
from config import BOT_TOKEN, LOG_GROUP_ID, MAIN_ADMIN_ID 
from achvlist import ACHV 

# import wwstats # حذف شد چون get_stats به صورت محلی تعریف شده

# 🚨 تغییر سطح لاگ به DEBUG برای عیب‌یابی عمیق‌تر 🚨
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG) 
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# ثابت‌های مربوط به آیتم‌ها و تشخیص پایان بازی
# ----------------------------------------------------------------------
# --- سیشتیر عادی (نام جدید) ---
MUTE_COST_PER_MINUTE = 2
MUTE_MAX_USAGE_MINUTES = 10 

# --- بیلاخ ---
BILAKH_COST = 5

# --- سیشتیر بابا ---
SISHTIR_BABA_COST_PER_MINUTE = 6
SISHTIR_BABA_MAX_USAGE_MINUTES = 10 

# ثابت‌های تشخیص پایان بازی گرگینه (Werewolf Game End)
WEREWOLFBETABOT_ID = 6534806119 
FAM_AWARD_AMOUNT = 1 

# ----------------------------------------------------------------------
# تعریف آیتم‌های فروشگاه (Shop Items Definition)
# ----------------------------------------------------------------------
# در فایل simple_hunter_bot.py (حدود خط 43)

SHOP_ITEMS = {
    # آیتم سیشتیر عادی
    "item_mute_minutes": { 
        "name": f"🔇 سیشتیر (۱ دقیقه)",
        "price": MUTE_COST_PER_MINUTE, 
        "duration_minutes": 1, 
        "description": f"برای استفاده، <b>(ریپلای به کاربر هدف) سیشتیر [مدت به دقیقه]</b> را ارسال کنید. کاربر هدف را ساکت می‌کند. این سکوت توسط ✋ <b>بیلاخ</b> خنثی می‌شود. (حداکثر: {MUTE_MAX_USAGE_MINUTES} دقیقه در هر فرمان)",
        "emoji": "🔇"
    },
    # آیتم بیلاخ
    "item_bilakh_has_count": {
        "name": "✋ بیلاخ (خنثی‌کننده سیشتیر)",
        "price": BILAKH_COST, # 5 فم
        "duration_minutes": 1, 
        "description": "در صورت هدف قرار گرفتن توسط 🔇 <b>سیشتیر (عادی)</b>، این آیتم به‌صورت خودکار مصرف شده و سکوت شما را خنثی می‌کند. <b>(نیاز به فرمان ندارد)</b>. (1 عدد = 1 خنثی‌سازی)",
        "emoji": "✋" 
    },
    # آیتم سیشتیر بابا
    "item_mute_baba_minutes": {
        "name": f"🪓 سیشتیر بابا (۱ دقیقه)",
        "price": SISHTIR_BABA_COST_PER_MINUTE, # 6 فم برای 1 دقیقه
        "duration_minutes": 1,
        "description": f"برای استفاده، <b>(ریپلای به کاربر هدف) سیشتیر بابا [مدت به دقیقه]</b> را ارسال کنید. قوی‌ترین سکوت است و <b>بیلاخ نمی‌تواند</b> آن را خنثی کند. (حداکثر: {SISHTIR_BABA_MAX_USAGE_MINUTES} دقیقه در هر فرمان)",
        "emoji": "🪓" 
    }
}


# ----------------------------------------------------------------------
# سیستم امتیازدهی فم و ادمین (Fam & Admin Scoring System) با SQLite
# ----------------------------------------------------------------------

DB_NAME = 'fam_scores.db'

def init_db():
    """ایجاد اتصال به دیتابیس و ساخت جداول مورد نیاز."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # جدول امتیازات فم
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fam_scores (
                user_id INTEGER PRIMARY KEY,
                score INTEGER NOT NULL DEFAULT 0
            )
        """)
        # جدول ادمین‌های ربات 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        # جدول سکوت مجازی ادمین‌های گروه
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS virtual_mutes (
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                mute_until REAL NOT NULL,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        # جدول جدید برای موجودی آیتم‌های خریداری شده
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_inventory (
                user_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, item_id)
            )
        """)
        # جدول شرط‌بندی‌ها
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                bet_id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT DEFAULT 'pending'  -- pending, accepted, rejected, cancelled, resolved
            )
        """)

        conn.commit()
        if 'MAIN_ADMIN_ID' in globals() and MAIN_ADMIN_ID is not None:
             cursor.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (MAIN_ADMIN_ID,))
             conn.commit()
        
        conn.close()
        logger.info("SQLite database and tables initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing SQLite database: {e}")

# توابع شرط‌بندی
def create_bet_db(creator_id, target_id, amount):
    try:
        logger.info(f"Attempting to create bet: creator={creator_id}, target={target_id}, amount={amount}")
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO bets (creator_id, target_id, amount)
            VALUES (?, ?, ?)
        """, (creator_id, target_id, amount))
        bet_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"Bet created successfully with ID {bet_id}")
        return bet_id
    except Exception as e:
        logger.error(f"Error creating bet: {e}")
        return None

def get_bet_db(bet_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bets WHERE bet_id = ?", (bet_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Error getting bet {bet_id}: {e}")
        return None

def update_bet_status_db(bet_id, status):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE bets SET status = ? WHERE bet_id = ?", (status, bet_id))
        conn.commit()
        conn.close()
        logger.info(f"Bet {bet_id} status updated to {status}")
        return True
    except Exception as e:
        logger.error(f"Error updating bet {bet_id} status: {e}")
        return False

# ----------------------------------------------------------------------
# توابع مدیریت موجودی آیتم‌ها (Inventory Management Functions)
# ----------------------------------------------------------------------

def get_inventory_count_db(user_id, item_id):
    """تعداد یک آیتم خاص را در موجودی کاربر برمی‌گرداند."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT count FROM user_inventory WHERE user_id = ? AND item_id = ?", (user_id, item_id))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception as e:
        logger.error(f"Error getting inventory count for user {user_id}: {e}")
        return 0

def update_inventory_db(user_id, item_id, amount):
    """موجودی یک آیتم خاص را در دیتابیس به‌روزرسانی می‌کند (می‌تواند مثبت یا منفی باشد)."""
    current_count = get_inventory_count_db(user_id, item_id)
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        new_count = max(0, current_count + amount) # موجودی نباید منفی شود
        
        cursor.execute("""
            INSERT INTO user_inventory (user_id, item_id, count) VALUES (?, ?, ?)
            ON CONFLICT(user_id, item_id) DO UPDATE SET count = excluded.count
        """, (user_id, item_id, new_count))
        
        conn.commit()
        conn.close()
        return new_count
    except Exception as e:
        logger.error(f"Error updating inventory for user {user_id}: {e}")
        return current_count

# ----------------------------------------------------------------------
# توابع مدیریت فم (Fam Management Functions)
# ----------------------------------------------------------------------

def get_fam_score_db(user_id):
    """امتیاز فم کاربر را از دیتابیس برمی‌گرداند."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT score FROM fam_scores WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception as e:
        logger.error(f"Error getting fam score for user {user_id}: {e}")
        return 0

def update_fam_score_db(user_id, amount):
    """امتیاز فم کاربر را در دیتابیس به‌روزرسانی می‌کند."""
    current_score = get_fam_score_db(user_id)
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        new_score = current_score + amount
        cursor.execute("""
            INSERT INTO fam_scores (user_id, score) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET score = excluded.score
        """, (user_id, new_score))
        conn.commit()
        conn.close()
        return new_score
    except Exception as e:
        logger.error(f"Error updating fam score for user {user_id}: {e}")
        return current_score


def get_top_fam_db():
    """۱۰ نفر برتر جدول فم را از دیتابیس برمی‌گرداند."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, score FROM fam_scores ORDER BY score DESC LIMIT 10")
        results = cursor.fetchall()
        conn.close()
        return results 
    except Exception as e:
        logger.error(f"Error getting top fam scores: {e}")
        return []
        
# ----------------------------------------------------------------------
# توابع مدیریت سکوت مجازی (Virtual Mute Management)
# ----------------------------------------------------------------------

def set_virtual_mute_db(user_id, chat_id, mute_until_timestamp):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO virtual_mutes (user_id, chat_id, mute_until) VALUES (?, ?, ?)
            ON CONFLICT(user_id, chat_id) DO UPDATE SET mute_until = excluded.mute_until
        """, (user_id, chat_id, mute_until_timestamp))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error setting virtual mute for user {user_id} in chat {chat_id}: {e}")

def is_virtually_muted_db(user_id, chat_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT mute_until FROM virtual_mutes WHERE user_id = ? AND chat_id = ? AND mute_until > ?",
            (user_id, chat_id, time.time())
        )
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"Error checking virtual mute for user {user_id} in chat {chat_id}: {e}")
        return False
        
# ----------------------------------------------------------------------
# توابع بررسی دسترسی ادمین (Admin Access Functions) 
# ----------------------------------------------------------------------

def is_admin(user_id):
    if 'MAIN_ADMIN_ID' in globals() and user_id == MAIN_ADMIN_ID:
        return True
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM bot_admins WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"Error checking admin status for user {user_id}: {e}")
        return False

def admin_only(func):
    async def wrapper(update: Update, context, *args, **kwargs):
        user = update.message.from_user if update.message else (update.callback_query.from_user if update.callback_query else None)
        if not user:
             logger.warning("Attempted admin command without user context.")
             return
             
        user_id = user.id
        if is_admin(user_id):
            return await func(update, context, *args, **kwargs)
        else:
            if update.message:
                await update.message.reply_text("❌ شما دسترسی ادمین برای اجرای این فرمان را ندارید.")
            elif update.callback_query:
                await update.callback_query.answer("❌ دسترسی شما محدود شده است.")
    return wrapper

# توابع ادمین 
@admin_only
async def add_bot_admin(update: Update, context):
    if not update.message.reply_to_message:
        await update.message.reply_text("برای افزودن ادمین، لطفاً پیام کاربر مورد نظر را ریپلای کنید: /add_admin")
        return

    target_user = update.message.reply_to_message.from_user
    target_id = target_user.id
    target_name = html.escape(target_user.first_name)
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (target_id,))
        conn.commit()
        
        if conn.total_changes > 0:
            await update.message.reply_html(f"✅ کاربر <b>{target_name}</b> با موفقیت به عنوان ادمین ربات اضافه شد.")
        else:
            await update.message.reply_html(f"⚠️ کاربر <b>{target_name}</b> از قبل ادمین ربات بود.")
        conn.close()    
    except Exception as e:
        logger.error(f"Error adding admin: {e}")
        await update.message.reply_text("❌ خطایی در هنگام افزودن ادمین رخ داد.")

@admin_only
async def remove_bot_admin(update: Update, context):
    if not update.message.reply_to_message:
        await update.message.reply_text("برای حذف ادمین، لطفاً پیام کاربر مورد نظر را ریپلای کنید: /remove_admin")
        return

    target_user = update.message.reply_to_message.from_user
    target_id = target_user.id
    target_name = html.escape(target_user.first_name)
    
    if 'MAIN_ADMIN_ID' in globals() and target_id == MAIN_ADMIN_ID:
        await update.message.reply_text("❌ ادمین اصلی را نمی‌توان حذف کرد.")
        return

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bot_admins WHERE user_id = ?", (target_id,))
        conn.commit()
        
        if conn.total_changes > 0:
            await update.message.reply_html(f"✅ کاربر <b>{target_name}</b> با موفقیت از لیست ادمین‌های ربات حذف شد.")
        else:
            await update.message.reply_html(f"⚠️ کاربر <b>{target_name}</b> از قبل در لیست ادمین‌های ربات نبود.")
        conn.close()
    except Exception as e:
        logger.error(f"Error removing admin: {e}")
        await update.message.reply_text("❌ خطایی در هنگام حذف ادمین رخ داد.")


# ----------------------------------------------------------------------
# توابع فرمان‌های ادمین و فم
# ----------------------------------------------------------------------

async def display_fam_score(update: Update, context):
    """/fam یا /my_fam: نمایش امتیاز فم و موجودی آیتم‌های کاربر."""
    user = update.message.from_user
    score = get_fam_score_db(user.id)
    
    # --- آیتم‌ها ---
    mute_minutes_count = get_inventory_count_db(user.id, "item_mute_minutes") 
    bilakh_count = get_inventory_count_db(user.id, "item_bilakh_has_count")
    mute_baba_minutes_count = get_inventory_count_db(user.id, "item_mute_baba_minutes")
    
    # بهبود فرمت پیام
    await update.message.reply_html(
        f"🏆 امتیاز **فم** شما: <b>{score} فم</b>\n\n"
        f"**موجودی آیتم:**\n"
        f"🔇 سیشتیر: <b>{mute_minutes_count} دقیقه</b> (فرمان: سیشتیر [مدت])\n"
        f"✋ بیلاخ: <b>{bilakh_count} عدد</b> (خنثی‌کننده سیشتیر عادی)\n"
        f"🪓 سیشتیر بابا: <b>{mute_baba_minutes_count} دقیقه</b> (فرمان: سیشتیر بابا [مدت])"
    )

@admin_only
async def add_fam_score(update: Update, context):
    """/add_fam <مقدار>: دادن یا کسر امتیاز از کاربر (با ریپلای) و ذخیره در دیتابیس."""
    
    if not update.message.reply_to_message:
        await update.message.reply_text("برای دادن امتیاز، لطفاً پیام کاربر مورد نظر را ریپلای (Reply) کنید و سپس دستور را به صورت زیر وارد نمایید: /add_fam <مقدار>")
        return
        
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("لطفاً مقدار امتیاز را مشخص کنید. مثال: /add_fam 10")
        return

    target_user = update.message.reply_to_message.from_user
    target_id = target_user.id
    target_name = html.escape(target_user.first_name)

    try:
        amount = int(context.args[0])
        if amount == 0:
             await update.message.reply_text("مقدار امتیاز نمی‌تواند صفر باشد.")
             return
    except ValueError:
        await update.message.reply_text("مقدار امتیاز باید یک عدد صحیح باشد.")
        return

    new_score = update_fam_score_db(target_id, amount)

    action = "اهدا" if amount > 0 else "کسر"
    
    await update.message.reply_html(
        f"✅ <b>{abs(amount)} فم</b> به {target_name} {action} شد.\n"
        f"مجموع امتیاز جدید: <b>{new_score} فم</b> 📈"
    )
    
async def fam_leaderboard(update: Update, context):
    """/top_fam یا /leaderboard: نمایش جدول رده‌بندی فم از دیتابیس."""
    top_10 = get_top_fam_db()
    
    if not top_10:
        await update.message.reply_text("هنوز هیچ امتیازی ثبت نشده است.")
        return
        
    leaderboard_msg = "🏆 **جدول رده‌بندی فم (TOP 10)** 🏆\n\n"
    
    for index, (user_id, score) in enumerate(top_10, 1):
        # تلاش برای گرفتن نام کاربر از تلگرام
        user_info = None
        try:
             user_info = await context.bot.get_chat(user_id)
             user_name = html.escape(user_info.first_name)
        except Exception:
             user_name = f"کاربر ناشناس"
             
        user_link = f"<a href='tg://user?id={user_id}'>{user_name}</a>" 
        leaderboard_msg += f"{index}. {user_link}: <b>{score} فم</b>\n"
    
    await update.message.reply_html(leaderboard_msg)


# ----------------------------------------------------------------------
# هندلر تشخیص پایان بازی @werewolfbetabot و جایزه فم
# ----------------------------------------------------------------------

async def handle_game_end_betabot(update: Update, context):
    """
    تشخیص پایان بازی از طریق پیام‌های @werewolfbetabot، 
    استخراج برندگان (IDهای هایپرلینک شده) و جایزه‌دهی فم.
    """
    message = update.message
    if not message or not message.text:
        return
        
    chat_id = message.chat_id
    
    # بررسی محتوای پیام برای تشخیص پایان بازی
    if "برنده" not in message.text or "مدت زمان بازی" not in message.text:
        return
        
    entities = message.entities if message.entities else []
    
    winner_ids = set()
    winner_names = []
    full_text = message.text
    
    # استخراج ID برندگان از انتیتی‌های Hyperlink (tg://user?id=...)
    for entity in entities:
        if entity.type == 'text_link' and entity.url.startswith('tg://user?id='):
            try:
                user_id = int(entity.url.split('=')[1])
            except ValueError:
                continue

            start = entity.offset
            end = entity.offset + entity.length
            entity_text = full_text[start:end]
            
            # بررسی محتوای اطراف لینک برای اطمینان از اینکه برنده هستند
            context_text = full_text[start-10:end+50]
            if "برنده" in context_text: 
                winner_ids.add(user_id)
                winner_names.append(entity_text)
                
    if not winner_ids:
        logger.info(f"Game end detected, but no winner ID found in message entities in chat {chat_id}")
        return 

    total_winners = len(winner_ids)
    
    if total_winners > 0:
        for user_id in winner_ids:
            update_fam_score_db(user_id, FAM_AWARD_AMOUNT)
        
        winner_names_text = ", ".join([f"<b>{html.escape(name)}</b>" for name in winner_names])
        
        # بهبود فرمت پیام
        announcement_msg = (
            f"🎉 پایان بازی!\n"
            f"برندگان: {winner_names_text}\n"
            f"به هر یک از برندگان، <b>{FAM_AWARD_AMOUNT} فم</b> جایزه اهدا شد! 💰"
        )
        await message.reply_html(announcement_msg)
        
        log_msg = f"🎉 **پایان بازی @werewolfbetabot - جایزه فم**\n"
        log_msg += f"گروه: {html.escape(message.chat.title)} (<code>{chat_id}</code>)\n"
        log_msg += f"🏅 برندگان (IDها): {', '.join([str(id) for id in winner_ids])}\n"
        log_msg += f"💰 جایزه: {FAM_AWARD_AMOUNT} فم برای هر نفر."
        
        if 'LOG_GROUP_ID' in globals() and LOG_GROUP_ID:
            await context.bot.send_message(LOG_GROUP_ID, log_msg, parse_mode='HTML')
        
        logger.info(f"Fam awarded to {total_winners} winners in chat {chat_id}")
        
# ----------------------------------------------------------------------
# هندلرهای استفاده از آیتم‌های خریداری شده (Usage Handlers)
# ----------------------------------------------------------------------

async def use_mute_item(update: Update, context):
    """'سیشتیر [مدت]': استفاده از آیتم سیشتیر (item_mute_minutes)."""
    
    ITEM_ID = "item_mute_minutes"
    BILAKH_ITEM_ID = "item_bilakh_has_count"

    if not update.message.chat.type in ['group', 'supergroup'] or not update.message.reply_to_message:
        return
        
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    target_user_id = update.message.reply_to_message.from_user.id
    target_name = html.escape(update.message.reply_to_message.from_user.first_name)
    
    match = re.search(r'^سیشتیر\s*(\d+)$', update.message.text.strip(), re.IGNORECASE)
    
    if not match:
        return # اگر الگو دقیقا منطبق نیست، نادیده بگیر
    
    try:
        duration_minutes = int(match.group(1))
        if duration_minutes <= 0 or duration_minutes > MUTE_MAX_USAGE_MINUTES: 
             await update.message.reply_text(f"مدت زمان سیشتیر باید بین ۱ تا {MUTE_MAX_USAGE_MINUTES} دقیقه باشد.")
             return
    except ValueError:
        return

    available_minutes = get_inventory_count_db(user_id, ITEM_ID)
    if available_minutes < duration_minutes:
        await update.message.reply_html(
            f"❌ موجودی زمان سیشتیر کافی نیست. شما <b>{available_minutes} دقیقه</b> موجودی دارید، اما برای این کار به <b>{duration_minutes} دقیقه</b> نیاز است.\n"
            f"از طریق /start در خصوصی ربات، به فروشگاه بروید و زمان بیشتری بخرید."
        )
        return
    
    new_available_minutes = None 
    try:
        # 1. کسر موجودی (deduct minutes)
        minutes_to_deduct = -duration_minutes
        new_available_minutes = update_inventory_db(user_id, ITEM_ID, minutes_to_deduct) 

        # 2. بررسی بیلاخ هدف و خنثی‌سازی (منطق سوختن سیشتیر اعمال شد)
        target_bilakh_count = get_inventory_count_db(target_user_id, BILAKH_ITEM_ID)
        
        if target_bilakh_count >= 1:
            # خنثی‌سازی: کسر بیلاخ از کاربر هدف (-1)
            update_inventory_db(target_user_id, BILAKH_ITEM_ID, -1) 
            
            # پیام خنثی‌سازی (به‌روزرسانی و حذف موجودی بیلاخ)
            await update.message.reply_html(
                f"✋ **بیلاخ** فعال شد!\n"
                f"سیشتیر مهاجم سوخت و <b>{target_name}</b> با مصرف بیلاخ در امان ماند. 🛡️"
                # ❌ موجودی باقی‌مانده بیلاخ هدف در پیام عمومی اعلام نمی‌شود.
            )
            # لاگ‌گیری خنثی‌سازی
            log_msg = f"🛡 **خنثی‌سازی بیلاخ و سوختن سیشتیر**\n"
            log_msg += f"👤 کاربر استفاده‌کننده: <a href='tg://user?id={user_id}'>{update.message.from_user.first_name}</a> (<code>{user_id}</code>)\n"
            log_msg += f"🎯 کاربر هدف: <a href='tg://user?id={target_user_id}'>{target_name}</a> (<code>{target_user_id}</code>)\n"
            log_msg += f"⏱ مدت سوخته: {duration_minutes} دقیقه\n"
            log_msg += f"📦 آیتم بیلاخ مصرف شد. سکوت اعمال نشد. موجودی جدید مهاجم: {new_available_minutes} دقیقه."
            
            if 'LOG_GROUP_ID' in globals() and LOG_GROUP_ID:
                await context.bot.send_message(LOG_GROUP_ID, log_msg, parse_mode='HTML')
                
            return # پایان اجرا، چون خنثی شد و سوخت


        # 3. اجرای منطق سکوت (در صورت عدم خنثی‌سازی)
        target_member = await context.bot.get_chat_member(chat_id, target_user_id)
        is_chat_admin = target_member.status in ('administrator', 'creator')
        
        if is_chat_admin:
            mute_until_dt = datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)
            set_virtual_mute_db(target_user_id, chat_id, mute_until_dt.timestamp())
            
            log_action = "🔨 **استفاده از آیتم - سیشتیر (مجازی)**"

        else:
            mute_until = datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)
            mute_permissions = ChatPermissions(can_send_messages=False)
            
            await context.bot.restrict_chat_member(
                chat_id, 
                target_user_id,
                permissions=mute_permissions, 
                until_date=mute_until
            )
            
            log_action = "🔨 **استفاده از آیتم - سیشتیر (API)**"

        # 4. ارسال پیام موفقیت‌آمیز و لاگ‌گیری
        success_msg = (
            f"✅ <b>سیشتیر</b> روی <b>{target_name}</b> اعمال شد!\n"
            f"کاربر به مدت <b>{duration_minutes} دقیقه</b> محدود خواهد ماند. 🤫 ⏱️"
        )
        await update.message.reply_html(
            f"{success_msg}" # ❌ موجودی باقی‌مانده از پیام عمومی حذف شد.
        )
        
        log_msg = f"{log_action}\n"
        log_msg += f"👤 کاربر استفاده‌کننده: <a href='tg://user?id={user_id}'>{update.message.from_user.first_name}</a> (<code>{user_id}</code>)\n"
        log_msg += f"🎯 کاربر هدف: <a href='tg://user?id={target_user_id}'>{target_name}</a> (<code>{target_user_id}</code>)\n"
        log_msg += f"⏱ مدت: {duration_minutes} دقیقه\n"
        log_msg += f"📦 موجودی جدید: {new_available_minutes} دقیقه"
        
        if 'LOG_GROUP_ID' in globals() and LOG_GROUP_ID:
            await context.bot.send_message(LOG_GROUP_ID, log_msg, parse_mode='HTML')
        
    except Exception as e:
        # 5. بازگرداندن آیتم در صورت خطای فنی (مانند عدم مجوز ربات)
        if new_available_minutes is not None:
            update_inventory_db(user_id, ITEM_ID, duration_minutes) 
        
        error_msg = str(e)
        if "not enough rights" in error_msg:
             error_msg = "ربات مجوز اعمال محدودیت (Restrict Member) را در این گروه ندارد."
        
        # بهبود فرمت پیام خطا
        await update.message.reply_html(
            f"❌ خطایی در اجرای سیشتیر رخ داد. زمان سیشتیر به موجودی شما برگشت داده شد.\n"
            f"علت: <b>{error_msg}</b>"
        )
        
async def use_sishtir_baba_item(update: Update, context):
    """'سیشتیر بابا [مدت]': استفاده از آیتم سکوت اجباری بابا (item_mute_baba_minutes)."""
    
    ITEM_ID = "item_mute_baba_minutes"
    
    if not update.message.chat.type in ['group', 'supergroup'] or not update.message.reply_to_message:
        return
        
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    target_user_id = update.message.reply_to_message.from_user.id
    target_name = html.escape(update.message.reply_to_message.from_user.first_name)
    
    # استفاده از Regex برای تطبیق "سیشتیر بابا [عدد]"
    match = re.search(r'^سیشتیر\s+بابا\s*(\d+)$', update.message.text.strip(), re.IGNORECASE)
    
    if not match:
        return # اگر الگو دقیقا منطبق نیست، نادیده بگیر
    
    try:
        duration_minutes = int(match.group(1))
        
        if duration_minutes <= 0 or duration_minutes > SISHTIR_BABA_MAX_USAGE_MINUTES: 
             await update.message.reply_text(f"مدت زمان سیشتیر بابا باید بین ۱ تا {SISHTIR_BABA_MAX_USAGE_MINUTES} دقیقه باشد.")
             return
             
    except ValueError:
        return

    available_minutes = get_inventory_count_db(user_id, ITEM_ID)
    if available_minutes < duration_minutes:
        await update.message.reply_html(
            f"❌ موجودی زمان سیشتیر بابا کافی نیست. شما <b>{available_minutes} دقیقه</b> موجودی دارید، اما برای این کار به <b>{duration_minutes} دقیقه</b> نیاز است.\n"
            f"از طریق /start در خصوصی ربات، به فروشگاه بروید و زمان بیشتری بخرید."
        )
        return
    
    new_available_minutes = None 
    try:
        # 1. کسر موجودی (deduct minutes)
        minutes_to_deduct = -duration_minutes
        new_available_minutes = update_inventory_db(user_id, ITEM_ID, minutes_to_deduct) 

        # 2. اجرای منطق سکوت (بیلاخ را نادیده می‌گیرد)
        target_member = await context.bot.get_chat_member(chat_id, target_user_id)
        is_chat_admin = target_member.status in ('administrator', 'creator')
        
        if is_chat_admin:
            mute_until_dt = datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)
            set_virtual_mute_db(target_user_id, chat_id, mute_until_dt.timestamp())
            
            log_action = "🔨 **استفاده از آیتم - سیشتیر بابا (مجازی)**"

        else:
            mute_until = datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)
            mute_permissions = ChatPermissions(can_send_messages=False)
            
            await context.bot.restrict_chat_member(
                chat_id, 
                target_user_id,
                permissions=mute_permissions, 
                until_date=mute_until
            )
            
            log_action = "🔨 **استفاده از آیتم - سیشتیر بابا (API)**"

        # 3. ارسال پیام موفقیت‌آمیز و لاگ‌گیری
        success_msg = (
            f"✅ <b>سیشتیر بابا</b> روی <b>{target_name}</b> اعمال شد!\n"
            f"کاربر به مدت <b>{duration_minutes} دقیقه</b> محدود خواهد ماند. 🤫 ⏱️"
        )
        await update.message.reply_html(
            f"{success_msg}" # ❌ موجودی باقی‌مانده از پیام عمومی حذف شد.
        )
        
        log_msg = f"{log_action}\n"
        log_msg += f"👤 کاربر استفاده‌کننده: <a href='tg://user?id={user_id}'>{update.message.from_user.first_name}</a> (<code>{user_id}</code>)\n"
        log_msg += f"🎯 کاربر هدف: <a href='tg://user?id={target_user_id}'>{target_name}</a> (<code>{target_user_id}</code>)\n"
        log_msg += f"⏱ مدت: {duration_minutes} دقیقه\n"
        log_msg += f"📦 موجودی جدید: {new_available_minutes} دقیقه"
        
        if 'LOG_GROUP_ID' in globals() and LOG_GROUP_ID:
            await context.bot.send_message(LOG_GROUP_ID, log_msg, parse_mode='HTML')
        
    except Exception as e:
        # 4. بازگرداندن آیتم در صورت خطا
        if new_available_minutes is not None:
            update_inventory_db(user_id, ITEM_ID, duration_minutes) 
        
        error_msg = str(e)
        if "not enough rights" in error_msg:
             error_msg = "ربات مجوز اعمال محدودیت (Restrict Member) را در این گروه ندارد."
        
        # بهبود فرمت پیام خطا
        await update.message.reply_html(
            f"❌ خطایی در اجرای سیشتیر رخ داد. زمان سکوت به موجودی شما برگشت داده شد.\n"
            f"علت: <b>{error_msg}</b>"
        )

# ----------------------------------------------------------------------
# هندلر پاکسازی پیام ادمین‌های سکوت شده (Virtual Mute Handler)
# ----------------------------------------------------------------------
async def admin_virtual_mute_handler(update: Update, context):
    
    logger.debug(f"*** DEBUG: admin_virtual_mute_handler called. Update ID: {update.update_id}") 
    
    if not update.message or update.message.chat.type not in ['group', 'supergroup'] or update.message.from_user.is_bot:
        return
        
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in ('administrator', 'creator'):
            return 
    except Exception:
        return

    if is_virtually_muted_db(user_id, chat_id):
        try:
            await update.message.delete()
            logger.info(f"Deleted message from virtually muted admin {user_id} in chat {chat_id}")
            
        except Exception as e:
            logger.error(f"Failed to delete message from virtually muted admin {user_id}: {e}")
            
# ----------------------------------------------------------------------
# توابع فرمان‌های فروشگاه و منوها (Shop & Menu Command Handlers) 
# ----------------------------------------------------------------------

def get_user_inventory_details(user_id):
    """Fetches Fam score and detailed inventory for a user."""
    fam_score = get_fam_score_db(user_id)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT item_id, count FROM user_inventory WHERE user_id = ? AND count > 0", (user_id,))
    inventory = cursor.fetchall()
    conn.close()

    inventory_text = ""
    if not inventory:
        inventory_text = "   - شما هیچ آیتم فعالی ندارید."
    else:
        for item_id_db, count in inventory:
            # از دیکشنری SHOP_ITEMS برای نمایش نام و اموجی استفاده می‌کنیم
            item_data = SHOP_ITEMS.get(item_id_db)
            if item_data:
                 unit = "دقیقه" if 'minutes' in item_id_db else "عدد"
                 # نمایش فقط بخش اصلی نام آیتم
                 item_display_name = item_data['name'].split('(')[0].strip()
                 inventory_text += f"   - {item_data['emoji']} <b>{item_display_name}</b>: {count} {unit}\n"
            else:
                 # در صورت عدم تطابق با SHOP_ITEMS
                 inventory_text += f"   - 📦 <b>{item_id_db}</b>: {count} \n"
                 
    return fam_score, inventory_text

async def get_main_menu_message_and_keyboard(user_id):
    """Generates the main menu message text and inline keyboard with inventory."""
    fam_score, inventory_text = get_user_inventory_details(user_id)
    
    keyboard = [
        [InlineKeyboardButton("🛒 فروشگاه فم", callback_data="open_shop")],
        [InlineKeyboardButton("📚 راهنمای آیتم‌ها", callback_data="open_help_menu")] 
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # بهبود فرمت پیام
    welcome_text = (
        f"🌟 به منوی اصلی ربات فمیلی خوش آمدید!\n\n"
        f"👤 شناسه شما: <code>{user_id}</code>\n"
        f"💰 امتیاز فم شما: <b>{fam_score} فم</b>\n\n"
        f"📦 موجودی آیتم‌های شما:\n"
        f"{inventory_text}"
    )
    
    return welcome_text, reply_markup

def get_shop_message_and_keyboard(user_id):
    """Generates the shop message text and inline keyboard."""
    fam_score = get_fam_score_db(user_id)
    
    keyboard = []
    
    for item_id, item_data in SHOP_ITEMS.items():
        price_display = item_data['price']
        button_text = f"{item_data['emoji']} {item_data['name']} - {price_display} فم"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"shop_buy:{item_id}")])
        
    # **اضافه کردن دکمه بازگشت به منوی اصلی**
    keyboard.append([InlineKeyboardButton("↩️ بازگشت به منوی اصلی", callback_data="open_main_menu")]) 
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # بهبود فرمت پیام
    shop_message = (
        "🛍 **فروشگاه آیتم‌های ویژه فم** 🛍\n\n"
        f"امتیاز **فم** شما: <b>{fam_score} فم</b> 🏆\n\n"
        "برای خرید روی آیتم مورد نظر کلیک کنید.\n"
        "برای مشاهده راهنمای استفاده از آیتم‌ها، به منوی اصلی بازگردید."
    )
    
    return shop_message, reply_markup

async def shop_callback_handler(update: Update, context):
    """مدیریت Callback Query برای خرید از فروشگاه و اضافه کردن به موجودی (پاسخ با پاپ‌آپ)."""
    query = update.callback_query
    
    if not query.data.startswith("shop_buy:"):
        await query.answer()
        return
        
    item_id = query.data.split(":")[1]
    item_data = SHOP_ITEMS.get(item_id)
    user_id = query.from_user.id
    
    if not item_data:
        await query.answer("❌ آیتم مورد نظر پیدا نشد.", show_alert=True)
        return
        
    item_name = item_data['name']
    item_price = item_data['price']
    
    current_score = get_fam_score_db(user_id)
    
    if current_score < item_price:
        error_text = f"💰 موجودی ناکافی!\nشما {current_score} فم دارید اما {item_name} نیاز به {item_price} فم دارد."
        await query.answer(error_text, show_alert=True)
        return

    # منطق خرید: کسر امتیاز و افزودن به موجودی
    new_score = update_fam_score_db(user_id, -item_price) 
    
    amount_to_add = item_data.get('duration_minutes', 1) 
    
    new_item_count = update_inventory_db(user_id, item_id, amount_to_add) 
    
    # 1. پاسخ به کاربر با پاپ‌آپ
    unit = "دقیقه" if 'minutes' in item_id else "عدد"
    success_text = f"✅ خرید موفقیت‌آمیز!\n{item_name} خریداری شد. موجودی جدید: {new_item_count} {unit}."

    await query.answer(success_text, show_alert=True)
    
    # 2. به‌روزرسانی پیام فروشگاه 
    shop_message, reply_markup = get_shop_message_and_keyboard(user_id)
    try:
        await query.edit_message_text(
            shop_message,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    except Exception as e:
         if "message is not modified" not in str(e):
             logger.error(f"Error editing shop message after purchase: {e}")
    
    # 3. ارسال پیام به گروه لاگ
    log_msg = f"🛒 **خرید جدید در فروشگاه فم**\n"
    log_msg += f"👤 کاربر: <a href='tg://user?id={user_id}'>{query.from_user.first_name}</a> (<code>{user_id}</code>)\n"
    log_msg += f"📦 آیتم: {item_name}\n"
    log_msg += f"💸 قیمت: {item_price} فم\n"
    log_msg += f"📉 امتیاز جدید: {new_score} فم\n"
    log_msg += f"📦 موجودی جدید: {new_item_count} {unit}"
         
    if 'LOG_GROUP_ID' in globals() and LOG_GROUP_ID:
        await context.bot.send_message(LOG_GROUP_ID, log_msg, parse_mode='HTML')


def get_help_message():
    """Generates the clear and structured item usage guide (راهنمای آیتم‌ها)."""
    
    help_text = (
        "📖 **راهنمای جذاب استفاده از آیتم‌های فروشگاه** 📖\n\n"
        "🎉 سلام! این راهنما مثل یک نقشه گنج، شما رو با آیتم‌های فوق‌العاده فروشگاه آشنا می‌کنه. "
        "هر آیتم رو با دقت بخونید و از قدرت‌هاشون در گروه‌ها استفاده کنید! 💪\n\n"
        "🛒 آیتم‌ها رو از فروشگاه (/shop) بخرید و بعدش با دستورات ساده فعالشون کنید. حالا بیایید شیرجه بزنیم تو جزئیات:\n\n"
    )

    # 1. سیشتیر (نام جدید)
    item_mute = SHOP_ITEMS["item_mute_minutes"]
    help_text += (
        f"**1. {item_mute['emoji']} سیشتیر عادی ({MUTE_COST_PER_MINUTE} فم/دقیقه)**\n"
        f"   🚀 **چطور استفاده کنم؟** پیام کاربر هدف رو ریپلای کنید و بنویسید: **سیشتیر [مدت به دقیقه]** (مثال: سیشتیر 5)\n"
        f"   ⚡ **قدرت:** کاربر رو ساکت می‌کنه و نمی‌تونه حرف بزنه! 🤐\n"
        f"   🛡️ **نکته کلیدی:** می‌تونه با **بیلاخ** خنثی بشه (و سیشتیرتون می‌سوزه! 🔥)\n"
        f"   ⏰ **محدودیت:** حداکثر {MUTE_MAX_USAGE_MINUTES} دقیقه در هر بار. عالی برای کنترل شیطون‌ها! 😈\n\n"
    )

    # 2. بیلاخ
    item_bilakh = SHOP_ITEMS["item_bilakh_has_count"]
    help_text += (
        f"**2. {item_bilakh['emoji']} بیلاخ (خنثی‌کننده - {BILAKH_COST} فم/عدد)**\n"
        f"   🛡️ **چطور استفاده کنم؟** هیچی! کاملاً **خودکار** فعال می‌شه. 🚀\n"
        f"   ⚡ **قدرت:** اگر کسی با سیشتیر عادی بهتون حمله کنه، بیلاخ مصرف می‌شه و شما رو نجات می‌ده! 🦸\n"
        f"   ❗ **نکته:** فقط سیشتیر عادی رو خنثی می‌کنه، نه باباش رو! (هر عدد = 1 نجات)\n\n"
    )

    # 3. سیشتیر بابا
    item_baba = SHOP_ITEMS["item_mute_baba_minutes"]
    help_text += (
        f"**3. {item_baba['emoji']} سیشتیر بابا ({SISHTIR_BABA_COST_PER_MINUTE} فم/دقیقه)**\n"
        f"   🚀 **چطور استفاده کنم؟** پیام کاربر هدف رو ریپلای کنید و بنویسید: **سیشتیر بابا [مدت به دقیقه]** (مثال: سیشتیر بابا 3)\n"
        f"   ⚡ **قدرت:** قوی‌ترین سکوت! کاربر کاملاً ساکت می‌شه و هیچی نمی‌تونه نجاتش بده. 💥\n"
        f"   🛡️ **نکته کلیدی:** حتی **بیلاخ** هم نمی‌تونه جلوش رو بگیره! 😎\n"
        f"   ⏰ **محدودیت:** حداکثر {SISHTIR_BABA_MAX_USAGE_MINUTES} دقیقه در هر بار. برای مواقع خاص استفاده کنید!\n\n"
    )

    help_text += (
        "🌟 **نکته نهایی:** فم‌هاتون رو عاقلانه خرج کنید و از آیتم‌ها برای سرگرمی بیشتر در گروه‌ها استفاده کنید! اگر سؤالی داشتید، همیشه در خدمتیم. 😊"
    )
    
    return help_text

async def open_shop_callback(update: Update, context):
    """Handles the callback query to display the shop from the main menu."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    shop_message, reply_markup = get_shop_message_and_keyboard(user_id)
    
    try:
        await query.edit_message_text(
            shop_message,
            reply_markup=reply_markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    except Exception as e:
        # Avoid error if message is not modified
        if "message is not modified" not in str(e):
             logger.error(f"Error editing message to display shop: {e}")

async def help_menu_callback(update: Update, context):
    """Handles the callback query to display the item usage guide."""
    query = update.callback_query
    await query.answer()

    help_message = get_help_message()
    
    # Keyboard to go back to the main menu
    keyboard = [
        [InlineKeyboardButton("↩️ بازگشت به منوی اصلی", callback_data="open_main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(
            help_message,
            reply_markup=reply_markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error editing message to display help guide: {e}")

async def main_menu_callback(update: Update, context):
    """Handles the callback query to return to the main /start menu."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    
    # استفاده از تابع جدید برای محتوای اصلی منو
    welcome_text, reply_markup = await get_main_menu_message_and_keyboard(user.id)

    try:
        await query.edit_message_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing message back to main menu: {e}")
        
# ----------------------------------------------------------------------
# هندلر شرط‌بندی (Bet Handler)
# ----------------------------------------------------------------------

async def handle_bet(update: Update, context):
    """تشخیص 'بت [عدد]' با ریپلای و ارسال درخواست تایید."""
    message = update.message
    if not message.chat.type in ['group', 'supergroup'] or not message.reply_to_message:
        return

    match = re.search(r'^بت\s*(\d+)$', message.text.strip(), re.IGNORECASE)
    if not match:
        return

    try:
        amount = int(match.group(1))
        if amount <= 0:
            await message.reply_text("مقدار شرط باید مثبت باشد.")
            return
    except ValueError:
        return

    creator_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id

    if creator_id == target_id:
        await message.reply_text("نمی‌توانید با خودتان شرط ببندید!")
        return

    creator_fam = get_fam_score_db(creator_id)

    if creator_fam < amount:
        await message.reply_text("شما فم کافی ندارید!")
        return

    bet_id = create_bet_db(creator_id, target_id, amount)
    if not bet_id:
        await message.reply_text("خطا در ایجاد شرط. (دیتابیس چک کنید)")
        return

    creator_name = message.from_user.first_name
    target_name = message.reply_to_message.from_user.first_name

    keyboard = [
        [InlineKeyboardButton("✅ قبول شرط", callback_data=f"accept_bet:{bet_id}")],
        [InlineKeyboardButton("❌ رد شرط", callback_data=f"reject_bet:{bet_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    bet_msg = (
        f"🎲 <b>شرط جدید!</b>\n"
        f"ایجادکننده: <b>{creator_name}</b>\n"
        f"هدف: <b>{target_name}</b>\n"
        f"مقدار: <b>{amount} فم</b>\n"
        f"<i>حریف می‌تواند قبول یا رد کند.</i>"
    )
    await message.reply_html(bet_msg, reply_markup=reply_markup)

# Callback handler برای شرط‌بندی
async def bet_callback(update: Update, context):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    bet_id = int(data.split(':')[1])

    bet = get_bet_db(bet_id)
    if not bet or bet[4] != 'pending':  # status
        await query.answer("این شرط معتبر نیست یا قبلاً حل شده.")
        return

    creator_id, target_id, amount = bet[1], bet[2], bet[3]

    if 'accept_bet' in data:
        if user_id != target_id:
            await query.answer("این شرط برای شما نیست.")
            return
        target_fam = get_fam_score_db(target_id)
        if target_fam < amount:
            await query.answer("شما فم کافی ندارید!")
            return
        # قبول: کسر فم هر دو
        update_fam_score_db(creator_id, -amount)
        update_fam_score_db(target_id, -amount)
        # انتخاب رندوم برنده
        participants = [creator_id, target_id]
        winner_id = random.choice(participants)
        loser_id = target_id if winner_id == creator_id else creator_id
        # انتقال فم به برنده
        update_fam_score_db(winner_id, 2 * amount)
        update_bet_status_db(bet_id, 'resolved')
        winner_name = query.from_user.first_name if winner_id == user_id else (await context.bot.get_chat(creator_id)).first_name
        loser_name = (await context.bot.get_chat(loser_id)).first_name
        resolve_msg = (
            f"✅ شرط قبول شد و حل شد!\n"
            f"برنده: <b>{winner_name}</b> (+{2*amount} فم)\n"
            f"بازنده: <b>{loser_name}</b> (-{amount} فم)"
        )
        await query.edit_message_text(resolve_msg, parse_mode='HTML')
        await query.answer("شرط قبول و حل شد!")

    elif 'reject_bet' in data:
        if user_id != target_id:
            await query.answer("این شرط برای شما نیست.")
            return
        update_bet_status_db(bet_id, 'rejected')
        await query.edit_message_text(query.message.text_html + "\n❌ شرط رد شد!")
        await query.answer("شرط رد شد.")

# ----------------------------------------------------------------------
# توابع خوش‌آمدگویی و /start
# ----------------------------------------------------------------------
async def startme(update: Update, context):
    """/start: ارسال پیام خوش‌آمدگویی. (کامل در پیوی، کوتاه در گروه)"""
    if update.message.chat.type == 'private':
        user = update.message.from_user
        
        # استفاده از تابع جدید برای محتوای اصلی منو
        welcome_text, reply_markup = await get_main_menu_message_and_keyboard(user.id)
        
        await update.message.reply_html(
            welcome_text,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

    else: 
        await update.message.reply_html(
            "✅ ربات فم فعال است.\n"
            "برای مشاهده فروشگاه و امکانات کامل، لطفاً ربات را در <b>چت خصوصی</b> استارت کنید: /start"
        )

# ----------------------------------------------------------------------
# توابع خوش‌آمدگویی (Welcome Functions) 
# ----------------------------------------------------------------------

def get_stats(user_id):
    wuff_url = "http://www.tgwerewolf.com/Stats/PlayerStats/?pid={}&json=true"
    try:
        # ⚠️ افزودن timeout برای جلوگیری از بلاک شدن ربات در صورت تأخیر سرور آمار
        response = requests.get(wuff_url.format(user_id), timeout=5) 
        response.raise_for_status()
        return response.json()
    except Exception as e:
        # در صورت شکست آمارگیری، لاگ ثبت می‌شود و None برمی‌گردد.
        logger.error(f"Error fetching stats for user {user_id}: {e}")
        return None

def format_welcome_message(user, chat_id, chat_title, stats):
    """
    متن خوش‌آمدگویی را با فرمت کاراکترهای (┓, ┫, ┛) ایجاد می‌کند.
    """
    user_id = user.id
    user_name = html.escape(user.first_name)
    user_username = user.username if user.username else ""
    
    # متغیرهای لینک
    name_link = f"<a href='tg://user?id={user_id}'>{user_name}</a>"
    stats_link_base = f"https://www.tgwerewolf.com/Stats/Player/{user_id}?referrer=stats"
    reg_link = f"https://t.me/TsWwPlus_Bot?start=registry-1001085673308"
    rules_link = f"https://t.me/ExecutrixBot?start=rules_{chat_id}"

    # جمع‌آوری خطوط پیام
    lines = []
    
    lines.append(f"دوست عزیز 🪽🪽 {name_link}")
    lines.append(f"به گروه {html.escape(chat_title)}")
    lines.append("خوش اومدی")
    
    lines.append(f"┓ شناسه: <code>{user_id}</code>")
    
    if user_username:
        lines.append(f"┫ نام کاربری: @{user_username}")
    
    stats = stats if isinstance(stats, dict) else {}
    game_played = stats.get('gamesPlayed', 0)
    
    # آمار گرگینه (با لینک) - اعمال شرط: فقط اگر بازی‌ها > ۱۰ باشد، لینک آمار نشان داده می‌شود.
    if game_played > 10:
        lines.append(f"┫ <a href=\"{stats_link_base}\">آمار گرگینه شما</a> ({game_played} بازی)")
    
    # لینک‌های ثابت - اعمال شرط جدید
    if game_played <= 10:
        lines.append(f"┫ <a href=\"https://telegram.me/Werewolf_Helper_Bot\">ربات آموزش بازی</a>")
        lines.append(f"┫ <a href=\"https://telegram.me/joinchat/BuYO30KjuJzxkBYiRokdHg\">گروه آموزش بازی</a>")
        
    lines.append(f"┫ <a href=\"https://telegram.me/joinchat/AAAAAERQ3SsWpurYKCCj8g\">کانال اطلاع رسانی</a>")
    lines.append(f"┫ <a href=\"https://telegram.me/joinchat/AAAAAEx-a7HIMj6LxTdRCQ\">کانال ثبت خاطرات</a>")
    lines.append(f"┫ <a href=\"https://telegram.me/Werewolf_Reports_Bot\">انتقادات و پیشنهادات</a>")
    lines.append(f"┫ <a href=\"{reg_link}\">ثبت نام در خانواده</a>")
    
    # قوانین گروه (با کاراکتر پایانی)
    lines.append(f"┛ <a href=\"{rules_link}\">قوانین گروه</a>")
    
    lines.append("با تشکر از شما")

    # حذف هرگونه خط خالی اضافی
    return '\n'.join([line for line in lines if line.strip() or line.startswith(('┓', '┫', '┛'))])


async def welcome_new_member(update: Update, context):
    logger.debug(f"*** DEBUG: welcome_new_member handler called. Update ID: {update.update_id}")

    if update.message and update.message.new_chat_members:
        chat_id = update.message.chat_id
        chat_title = update.message.chat.title
        
        for user in update.message.new_chat_members:
            if user.id == context.bot.id or user.is_bot:
                continue
            
            # --- مرحله عیب‌یابی: تأیید مجوزها ---
            try:
                member_status = await context.bot.get_chat_member(chat_id, context.bot.id)
                
                if member_status.status not in ('administrator', 'creator'):
                    logger.warning(
                        f"Skipping welcome in chat {chat_id}. Bot is NOT an admin/creator. "
                        f"Status: {member_status.status}"
                    )
                    return
                
                if member_status.can_post_messages is False:
                     logger.warning(
                        f"Skipping welcome in chat {chat_id}. Bot is admin but can_post_messages is EXPLICITLY False. "
                        f"Status: {member_status.status}, Can Post: {member_status.can_post_messages}"
                     )
                     return 

            except Exception as e:
                logger.error(f"Failed to check bot's admin status in chat {chat_id}: {e}")
                return 

            logger.info(f"Received NEW_CHAT_MEMBERS update for user {user.id} in chat {chat_id}. Attempting to process welcome message.")

            # آمارگیری (با timeout)
            stats = get_stats(user.id)
            
            welcome_msg = format_welcome_message(user, chat_id, chat_title, stats)
            
            try:
                # 1. تلاش برای ارسال پیام با فرمت HTML (اولویت اول)
                await update.message.reply_html(
                    welcome_msg, 
                    disable_web_page_preview=True
                )
                logger.info(f"Successfully sent HTML welcome message in chat {chat_id} for user {user.id}")

            except Exception as e:
                error_details = str(e)
                logger.error(f"Error sending HTML welcome message in chat {chat_id} for user {user.id}. Error: {error_details}. Trying Markdown fallback...")
                
                # 2. فال‌بک (Fallback) در صورت خطای HTML: تلاش با Markdown V2
                markdown_msg = welcome_msg.replace('<b>', '**').replace('</b>', '**')
                markdown_msg = re.sub(r'<a href=[\'"]([^\'"]+)[\'"]>([^<]+)</a>', r'[\2](\1)', markdown_msg)
                markdown_msg = re.sub(r'<code>([^<]+)</code>', r'`\1`', markdown_msg) 
                markdown_msg = re.sub(r'<[^>]+>', '', markdown_msg) 
                
                # escaping characters for Markdown V2
                markdown_msg = re.sub(r'([_*[\]()~`>#+-=|\{\}.!])', r'\\\1', markdown_msg)
                
                try:
                    await update.message.reply_markdown_v2(
                        markdown_msg,
                        disable_web_page_preview=True
                    )
                    logger.info(f"Sent Markdown V2 fallback welcome message in chat {chat_id} for user {user.id}")
                except Exception as fallback_e:
                     # 3. فال‌بک نهایی (Final Fallback): متن ساده 
                     final_fallback_msg = f"دوست عزیز {user.first_name}، به گروه {chat_title} خوش اومدی!\nبرای مشاهده امکانات ربات، در چت خصوصی /start را ارسال کنید."
                     logger.critical(f"Critical Error (Markdown V2 also failed) sending welcome message in chat {chat_id}: {fallback_e}. Sending simple text.")
                     
                     try:
                        await update.message.reply_text(
                            final_fallback_msg,
                            disable_web_page_preview=True
                        )
                     except Exception as simple_e:
                         logger.critical(f"Final Fallback (Simple Text) FAILED in chat {chat_id}: {simple_e}")


# ----------------------------------------------------------------------
# توابع فرمان‌های آماری (Dummy Handlers) 
# ----------------------------------------------------------------------

async def display_kills(update: Update, context):
    pass 
async def display_killed_by(update: Update, context):
    pass 
async def display_deaths(update: Update, context):
    pass 
async def display_search(update: Update, context):
    pass 
async def display_about(update: Update, context):
    pass
async def display_achv(update: Update, context):
    pass
async def display_achv_info(update: Update, context):
    pass
async def display_stats(update: Update, context):
    pass

# ----------------------------------------------------------------------
# مدیریت خطا (Error Handler) 
# ----------------------------------------------------------------------

async def error_handler(update: Update, context):
    e = str(context.error).lower()
    if "timed out" in e or "not modified" in e or "query_id_invalid" in e:
        return
    
    bot = context.bot
    msg = f"This update caused error.\n{context.error}\n\n"
    
    if update:
        if hasattr(update, 'message'):
            update_json = update.message.to_json() if update.message else update.to_json()
        else:
             update_json = update.to_json()

    else:
        update_json = "No update object available."

    msg += f"```json\n{json.dumps(json.loads(update_json), indent=2, ensure_ascii=False)}```"
    if 'LOG_GROUP_ID' in globals() and LOG_GROUP_ID:
        try:
             # ارسال پیام خطا به گروه لاگ با Markdown
             await bot.send_message(LOG_GROUP_ID, msg, parse_mode='Markdown')
        except Exception as e:
             logger.error(f"Failed to send error log to group: {e}")
             
    logger.error(f"Update {update} caused error {context.error}")


# ----------------------------------------------------------------------
# تابع اصلی (Main Function)
# ----------------------------------------------------------------------

def main():
    # ۱. مقداردهی اولیه دیتابیس (شامل جداول جدید)
    init_db() 
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # -------------------------------------------------------------
    # فعال‌سازی هندلر حیاتی خوش‌آمدگویی (اولویت بالا)
    # -------------------------------------------------------------
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member)) 
    
    # -------------------------------------------------------------
    # هندلرهای ادمین
    # -------------------------------------------------------------
    application.add_handler(CommandHandler('add_admin', add_bot_admin))
    application.add_handler(CommandHandler('remove_admin', remove_bot_admin))
    
    # -------------------------------------------------------------
    # هندلرهای فم
    # -------------------------------------------------------------
    application.add_handler(CommandHandler(['fam', 'my_fam'], display_fam_score))
    application.add_handler(CommandHandler('add_fam', add_fam_score))
    application.add_handler(CommandHandler(['top_fam', 'leaderboard'], fam_leaderboard))
    
    # -------------------------------------------------------------
    # هندلر تشخیص پایان بازی بتوبات
    # -------------------------------------------------------------
    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS & filters.User(WEREWOLFBETABOT_ID), 
        handle_game_end_betabot
    ))
    
    # -------------------------------------------------------------
    # هندلرهای استفاده از آیتم‌های خریداری شده
    # -------------------------------------------------------------
    # سیشتیر عادی (قابل خنثی‌سازی توسط بیلاخ)
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^سیشتیر\s*(\d+)$') & filters.REPLY, use_mute_item))
    
    # سیشتیر بابا (خنثی‌ناپذیر)
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^سیشتیر\s+بابا\s*(\d+)$') & filters.REPLY, use_sishtir_baba_item))
    
    # -------------------------------------------------------------
    # هندلر شرط‌بندی ساده – قبل از virtual mute برای اولویت
    # -------------------------------------------------------------
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^بت\s*(\d+)$') & filters.REPLY, handle_bet))
    
    # هندلر callback برای شرط‌بندی
    application.add_handler(CallbackQueryHandler(bet_callback, pattern=r'^(accept_bet|reject_bet|cancel_bet):'))
    
    # -------------------------------------------------------------
    # سکوت مجازی (Virtual Mute) – بعد از bet برای اجازه اجرا
    # -------------------------------------------------------------
    application.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), admin_virtual_mute_handler))
    
    # -------------------------------------------------------------
    # هندلرهای فروشگاه و منوها (فقط در چت خصوصی)
    # -------------------------------------------------------------
    application.add_handler(CallbackQueryHandler(open_shop_callback, pattern="^open_shop$")) 
    application.add_handler(CallbackQueryHandler(help_menu_callback, pattern="^open_help_menu$")) 
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^open_main_menu$")) 
    application.add_handler(CallbackQueryHandler(shop_callback_handler, pattern="^shop_buy:")) 
    
    # -------------------------------------------------------------
    # فعال‌سازی هندلرهای ضروری
    # -------------------------------------------------------------
    application.add_handler(CommandHandler('start', startme)) 
    
    # -------------------------------------------------------------
    # فرمان‌های آماری 
    # -------------------------------------------------------------
    application.add_handler(CommandHandler('stats', display_stats)) 
    
    application.add_error_handler(error_handler)
    
    application.run_polling(poll_interval=0)


if __name__ == '__main__':
    main()
