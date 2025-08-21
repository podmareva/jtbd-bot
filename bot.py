import os, json, secrets, logging, hashlib
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("cashier")

async def safe_edit(q, text: str, **kwargs):
    """
    Универсальное редактирование: если сообщение медиа — меняем caption,
    если обычное — меняем text.
    """
    try:
        m = q.message
        if getattr(m, "photo", None) or getattr(m, "document", None) or getattr(m, "video", None) or getattr(m, "video_note", None):
            return await q.edit_message_caption(caption=text, **kwargs)
        return await q.edit_message_text(text, **kwargs)
    except Exception:
        # fallback на альтернативный метод + лог
        try:
            return await q.edit_message_caption(caption=text, **kwargs)
        except Exception:
            log.exception("safe_edit: both edit_message_text and edit_message_caption failed")
            return await q.edit_message_text(text, **kwargs)

# -------------------- CONFIG / ENV --------------------
load_dotenv()

BOT_TOKEN    = os.getenv("CASHIER_BOT_TOKEN")
ADMIN_ID     = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")

# --- Robokassa ---
ROBOKASSA_MERCHANT_LOGIN = os.getenv("ROBOKASSA_MERCHANT_LOGIN")
ROBOKASSA_PASSWORD_1     = os.getenv("ROBOKASSA_PASSWORD_1")
ROBOKASSA_PASSWORD_2     = os.getenv("ROBOKASSA_PASSWORD_2")

# целевые боты (username)
BOT_UNPACK = os.getenv("BOT_UNPACK", "jtbd_assistant_bot")
BOT_COPY   = os.getenv("BOT_COPY",   "content_helper_assist_bot")

# юр-документы + инфо о разработчике (ссылки)
POLICY_URL      = (os.getenv("POLICY_URL") or "").strip()
OFFER_URL       = (os.getenv("OFFER_URL") or "").strip()
ADS_CONSENT_URL = (os.getenv("ADS_CONSENT_URL") or "").strip()
DEV_INFO_URL    = (os.getenv("DEV_INFO_URL") or "").strip()

# кружок (video note) — file_id (опционально)
DEV_VIDEO_NOTE_ID = os.getenv("DEV_VIDEO_NOTE_ID", "").strip()

# срок жизни персональных ссылок (часы)
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "48"))

# примеры ответов (file_id картинок)
EXAMPLE_IDS = [
    os.getenv("EXAMPLE_1_ID"),
    os.getenv("EXAMPLE_2_ID"),
    os.getenv("EXAMPLE_3_ID"),
    os.getenv("EXAMPLE_4_ID"),
    os.getenv("EXAMPLE_5_ID"),
]

# Акция (только 2 бота)
PROMO_ACTIVE = os.getenv("PROMO_ACTIVE", "true").lower() == "true"
PROMO_PRICES = {
    "unpack": 1890.00,
    "copy":   2490.00,
    "b12":    3990.00,
}

# Конец акции и TZ для напоминаний
PROMO_END_ISO = os.getenv("PROMO_END_ISO", "").strip()
TIMEZONE      = os.getenv("TIMEZONE", "Europe/Moscow")

if not (BOT_TOKEN and ADMIN_ID and DATABASE_URL and POLICY_URL and OFFER_URL and ADS_CONSENT_URL):
    raise RuntimeError("Проверь .env: CASHIER_BOT_TOKEN, ADMIN_ID, DATABASE_URL, POLICY_URL, OFFER_URL, ADS_CONSENT_URL")
if not (ROBOKASSA_MERCHANT_LOGIN and ROBOKASSA_PASSWORD_1 and ROBOKASSA_PASSWORD_2):
    raise RuntimeError("Проверь .env: добавь данные от Робокассы (ROBOKASSA_MERCHANT_LOGIN, ROBOKASSA_PASSWORD_1, ROBOKASSA_PASSWORD_2)")

# logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("cashier")

# -------------------- DB --------------------
conn = psycopg.connect(DATABASE_URL, autocommit=True, sslmode="require", row_factory=dict_row)
cur  = conn.cursor()

def ensure_conn():
    global conn, cur
    try:
        conn.execute("SELECT 1")
    except Exception:
        log.warning("🔄 Восстанавливаю соединение с БД...")
        conn = psycopg.connect(DATABASE_URL, autocommit=True, sslmode="require", row_factory=dict_row)
        cur = conn.cursor()

# Изменили статус по умолчанию на 'pending' и добавили 'awaiting_payment'
cur.execute("""CREATE TABLE IF NOT EXISTS consents(
  user_id BIGINT PRIMARY KEY,
  accepted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);""")
cur.execute("""CREATE TABLE IF NOT EXISTS products(
  code TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  price NUMERIC(10,2) NOT NULL,
  targets JSONB NOT NULL
);""")
cur.execute("""CREATE TABLE IF NOT EXISTS orders(
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  product_code TEXT NOT NULL REFERENCES products(code),
  amount NUMERIC(10,2) NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending/awaiting_payment/paid/rejected
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);""")
# Таблица receipts больше не нужна, но не будем ее удалять, чтобы не сломать старые данные
cur.execute("""CREATE TABLE IF NOT EXISTS tokens(
  token TEXT PRIMARY KEY,
  bot_name TEXT NOT NULL,
  user_id BIGINT NOT NULL,
  expires_at TIMESTAMPTZ NULL
);""")
cur.execute("ALTER TABLE tokens ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL;")
cur.execute("""CREATE TABLE IF NOT EXISTS allowed_users(
  user_id BIGINT NOT NULL,
  bot_name TEXT NOT NULL,
  PRIMARY KEY(user_id, bot_name)
);""")
cur.execute("""CREATE TABLE IF NOT EXISTS invoice_requests(
  id BIGSERIAL PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed BOOLEAN NOT NULL DEFAULT FALSE
);""")


# Каталог базовых цен
CATALOG = {
    "unpack": {"title": "Бот №1 «Распаковка + Анализ ЦА (JTBD)»",        "price": 2990.00, "targets": [BOT_UNPACK]},
    "copy":   {"title": "Бот №2 «Твой личный контент-помощник»",         "price": 5490.00, "targets": [BOT_COPY]},
    "b12":    {"title": "Пакет «Распаковка + контент»",                  "price": 7990.00, "targets": [BOT_UNPACK, BOT_COPY]},
}
for code, p in CATALOG.items():
    cur.execute(
        """INSERT INTO products(code, title, price, targets)
           VALUES (%s,%s,%s,%s::jsonb)
           ON CONFLICT (code) DO UPDATE SET title=EXCLUDED.title, price=EXCLUDED.price, targets=EXCLUDED.targets""",
        (code, p["title"], p["price"], json.dumps(p["targets"]))
    )

# -------------------- Utils --------------------
def generate_robokassa_link(order_id: int, amount: float, description: str) -> str:
    """Генерирует ссылку на оплату через Робокассу."""
    merchant_login = ROBOKASSA_MERCHANT_LOGIN
    password_1 = ROBOKASSA_PASSWORD_1
    
    # Формируем строку для хеширования
    # :shp_item=... - можно добавить доп. параметры
    signature_string = f"{merchant_login}:{amount}:{order_id}:{password_1}"
    
    # Создаем MD5 хеш
    signature_hash = hashlib.md5(signature_string.encode('utf-8')).hexdigest()
    
    # Формируем URL
    payment_url = (
        f"https://auth.robokassa.ru/Merchant/Index.aspx?"
        f"MerchantLogin={merchant_login}&"
        f"OutSum={amount}&"
        f"InvId={order_id}&"
        f"Description={description}&"
        f"SignatureValue={signature_hash}"
    )
    
    return payment_url

def set_consent(user_id: int):
    ensure_conn()
    try:
        cur.execute(
            "INSERT INTO consents(user_id, accepted_at) VALUES(%s, now()) ON CONFLICT DO NOTHING",
            (user_id,)
        )
    except Exception as e:
        log.warning("Ошибка при сохранении согласия: %s", e)

def get_product(code: str) -> Optional[dict]:
    ensure_conn()
    try:
        cur.execute("SELECT * FROM products WHERE code=%s", (code,))
        return cur.fetchone()
    except Exception as e:
        log.warning("Ошибка при получении продукта: %s", e)
        return None

def current_price(code: str) -> float:
    ensure_conn()
    base = float(get_product(code)["price"])
    if PROMO_ACTIVE and code in PROMO_PRICES:
        return float(PROMO_PRICES[code])
    return base

def create_order(user_id: int, code: str) -> int:
    ensure_conn()
    price = current_price(code)
    cur.execute(
        "INSERT INTO orders(user_id, product_code, amount, status) VALUES(%s,%s,%s,'pending') RETURNING id",
        (user_id, code, price)
    )
    return cur.fetchone()["id"]

def set_status(order_id: int, status: str):
    ensure_conn()
    cur.execute("UPDATE orders SET status=%s WHERE id=%s", (status, order_id))

def get_order(order_id: int) -> Optional[dict]:
    ensure_conn()
    cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
    return cur.fetchone()

def get_user_by_order(order_id: int) -> Optional[int]:
    ensure_conn()
    cur.execute("SELECT user_id FROM orders WHERE id=%s", (order_id,))
    row = cur.fetchone()
    return row["user_id"] if row else None
    
def gen_tokens_with_ttl(user_id: int, targets: list[str], ttl_hours: int):
    ensure_conn()
    links = []
    expires_at = datetime.utcnow() + timedelta(hours=ttl_hours) if ttl_hours > 0 else None
    for bot_name in targets:
        token = secrets.token_urlsafe(8)
        cur.execute(
            "INSERT INTO tokens(token, bot_name, user_id, expires_at) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (token, bot_name, user_id, expires_at)
        )
        links.append((bot_name, f"https://t.me/{bot_name}?start={token}"))
    return links

def shop_keyboard():
    # Убрали кнопку "Загрузить чек"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Оплатить бота «Распаковка + Анализ ЦА»",         callback_data="buy:unpack")],
        [InlineKeyboardButton("Оплатить бота «Твой личный контент-помощник»",   callback_data="buy:copy")],
        [InlineKeyboardButton("Оплатить ботов «Распаковка+контент»",            callback_data="buy:b12")],
    ])

# ----- Примеры ответов -----
async def send_examples_screens(ctx, chat_id: int):
    ids = [fid for fid in EXAMPLE_IDS if fid]
    if not ids:
        return
    media = []
    for i, fid in enumerate(ids):
        try:
            if i == 0:
                media.append(InputMediaPhoto(media=fid, caption="Примеры ответов ботов"))
            else:
                media.append(InputMediaPhoto(media=fid))
        except Exception as e:
            log.warning("Bad example file_id skipped: %s", e)
    if media:
        try:
            await ctx.bot.send_media_group(chat_id=chat_id, media=media)
        except Exception as e:
            log.warning("send_media_group error: %s", e)

# -------------------- Handlers --------------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    
    if DEV_VIDEO_NOTE_ID:
        try:
            await ctx.bot.send_video_note(chat_id=uid, video_note=DEV_VIDEO_NOTE_ID)
        except Exception as e:
            log.warning("video note send error: %s", e)

    keyboard = [
        [InlineKeyboardButton("📄 Политика конфиденциальности", url=POLICY_URL)],
        [InlineKeyboardButton("📜 Договор оферты",              url=OFFER_URL)],
        [InlineKeyboardButton("✉️ Согласие на рекламу",        url=ADS_CONSENT_URL)],
        [InlineKeyboardButton("✅ Согласен — перейти к оплате", callback_data="consent_ok")],
    ]
    
    if DEV_INFO_URL:
        keyboard.append([InlineKeyboardButton("👨‍💻 О разработчике", url=DEV_INFO_URL)])

    kb = InlineKeyboardMarkup(keyboard)
    
    await ctx.bot.send_message(
        chat_id=uid,
        text=(
            "Прежде чем продолжить, подтвердите согласие с условиями использования.\n\n"
            "Нажимая кнопку \u00ab✅ Согласен — перейти к оплате\u00bb, вы принимаете условия:"
        ),
        reply_markup=kb
    )

async def cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

    try:
        await q.answer("⏳ Обрабатываю…", show_alert=False)
    except Exception:
        pass

    try:
        if data == "consent_ok":
            set_consent(uid)

            await safe_edit(q, "✅ Вы подтвердили согласие. Давайте покажу, как работают боты:", parse_mode="HTML")

            await ctx.bot.send_message(
                chat_id=uid,
                text=(
                    "🧠 <b>Бот №1: Распаковка + Анализ ЦА (JTBD)</b>\n"
                    "Поможет понять, что на самом деле «покупает» клиент, и как правильно сформулировать позиционирование.\n\n"
                    "✍️ <b>Бот №2: Контент-помощник</b>\n"
                    "Создаёт контент-план, тексты, Reels, визуальные подсказки — на основе вашей распаковки."
                ),
                parse_mode="HTML"
            )

            await send_examples_screens(ctx, uid)
            
            # Текст с ценами можно оставить
            await ctx.bot.send_message(
                chat_id=uid,
                text=(
                    "🎁 <b>Спеццены только до 1 сентября:</b>\n\n"
                    "🛠 <b>Отдельные боты</b>\n"
                    "• Распаковка + Анализ ЦА — <s>2 990 ₽</s> → <b>1 890 ₽</b>\n"
                    "• Контент-помощник — <s>5 490 ₽</s> → <b>2 490 ₽</b>\n\n"
                    "💎 <b>Пакет 1+2</b>\n"
                    "• Всё вместе — <s>7 990 ₽</s> → <b>3 990 ₽</b>"
                ),
                parse_mode="HTML"
            )


            await ctx.bot.send_message(
                chat_id=uid,
                text="👇 Выберите продукт, который хотите оплатить:",
                reply_markup=shop_keyboard()
            )
            return
        
        if data == "go_shop":
            await q.edit_message_text(
                "👇 Выберите продукт, который хотите оплатить:",
                reply_markup=shop_keyboard()
            )
            return

        if data.startswith("buy:"):
            code = data.split(":", 1)[1]
            prod = get_product(code)
            if not prod:
                await q.edit_message_text("Продукт не найден. Обновите витрину: /start")
                return

            order_id = create_order(uid, code)
            price = current_price(code)
            
            # Генерируем ссылку на оплату через Робокассу
            payment_link = generate_robokassa_link(
                order_id=order_id,
                amount=price,
                description=prod['title'].replace('"', '') # Убираем кавычки из описания
            )

            set_status(order_id, "awaiting_payment")

            old = float(prod["price"])
            old_line = f"Старая цена: <s>{old:.2f} ₽</s>\n" if PROMO_ACTIVE else ""

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Оплатить через Робокассу", url=payment_link)],
                [InlineKeyboardButton("✅ Я оплатил(а)", callback_data=f"check_payment:{order_id}")],
                [InlineKeyboardButton("◀️ Назад к списку", callback_data="go_shop")]
            ])

            await q.edit_message_text(
                f"🧾 <b>{prod['title']}</b>\n\n"
                f"{old_line}Сумма к оплате: <b>{price:.2f} ₽</b>\n\n"
                "Нажмите на кнопку ниже, чтобы перейти к безопасной оплате через Робокассу.",
                parse_mode="HTML",
                reply_markup=kb
            )
            return

        if data.startswith("check_payment:"):
            order_id = int(data.split(":", 1)[1])
            order = get_order(order_id)
            if not order or order['user_id'] != uid:
                await q.edit_message_text("Заказ не найден.")
                return

            if order['status'] == 'paid':
                 await q.edit_message_text("✅ Этот заказ уже оплачен. Ваши ссылки были отправлены ранее.")
                 return
            
            # Отправляем уведомление админу для ручной проверки
            kb_admin = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm:{order_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{order_id}")
                ]
            ])
            
            await ctx.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🔔 Пользователь <a href=\"tg://user?id={uid}\">{uid}</a> нажал 'Я оплатил(а)' "
                    f"по заказу #{order_id}.\n\n"
                    "Пожалуйста, проверьте поступление средств в ЛК Робокассы и подтвердите заказ."
                ),
                reply_markup=kb_admin,
                parse_mode="HTML"
            )

            await q.edit_message_text("✅ Спасибо! Мы получили ваше уведомление. Администратор скоро проверит платеж и, в случае успеха, я пришлю вам доступы.")
            return

        if data.startswith("confirm:"):
            order_id = int(data.split(":", 1)[1])
            
            order = get_order(order_id)
            if not order:
                await q.edit_message_text(f"⚠️ Заказ #{order_id} не найден в базе.")
                return

            set_status(order_id, "paid")
            
            product = get_product(order["product_code"])
            if not product:
                await q.edit_message_text(f"⚠️ Продукт '{order['product_code']}' для заказа #{order_id} не найден.")
                return

            user_id = order["user_id"]
            targets = product["targets"]
            links = gen_tokens_with_ttl(user_id, targets, TOKEN_TTL_HOURS)

            link_lines = "\n".join([f"➡️ <a href='{link}'>{bot_name}</a>" for bot_name, link in links])
            
            try:
                await ctx.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "✅ Оплата подтверждена!\n\n"
                        "Вот ваши персональные ссылки для доступа к ботам:\n\n"
                        f"{link_lines}\n\n"
                        f"⚠️ <b>Важно:</b> Ссылки действительны в течение {TOKEN_TTL_HOURS} часов. "
                        "Обязательно перейдите по ним и запустите ботов, чтобы доступ сохранился навсегда."
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                await safe_edit(q, f"✅ Доступ по заказу #{order_id} успешно выдан пользователю {user_id}.")
            except Exception as e:
                log.error(f"Не удалось отправить ссылки пользователю {user_id} по заказу #{order_id}: {e}")
                await safe_edit(q, f"❌ Ошибка при выдаче доступа по заказу #{order_id}. Пользователю {user_id} не удалось отправить сообщение. Проверьте логи.")
            return
            
    except Exception as e:
        log.exception("Ошибка в cb, data=%s", data)
        try:
            await safe_edit(q, "Ой, что-то пошло не так. Попробуйте снова или нажмите /start")
        except Exception:
            pass

# --- Админские команды и прочее ---

async def fallback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Эта команда будет срабатывать на любые текстовые сообщения, кроме команд
    await update.message.reply_text(
        "Я принимаю оплату и выдаю доступы. Для начала работы нажмите /start.\n\n"
        "Если у вас возник вопрос по оплате или работе ботов, напишите администратору."
    )

import time
from telegram import Update
from telegram.error import Conflict

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(cb))
    
    # Админские хендлеры для получения file_id
    app.add_handler(CommandHandler("vnote", help_vnote))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE & filters.User(ADMIN_ID), detect_vnote))
    app.add_handler(CommandHandler("photoid", cmd_photoid))

    # Обработчик для любых текстовых сообщений, которые не являются командами
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))

    while True:
        try:
            log.info("🚀 Запускаю бота через polling...")
            app.run_polling(allowed_updates=Update.ALL_TYPES)
        except Conflict:
            log.warning("⚠️ Обнаружен второй экземпляр. Ждём 10 секунд и пробуем снова...")
            time.sleep(10)
        except Exception as e:
            log.exception("🔥 Ошибка в run_polling. Перезапуск через 15 секунд...")
            time.sleep(15)

# --- Вспомогательные админские функции (остаются без изменений) ---
async def help_vnote(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text("Пришлите кружок (video note) — верну file_id.")

async def detect_vnote(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if update.message.video_note:
        await update.message.reply_text(f"file_id кружка: {update.message.video_note.file_id}\nСкопируйте в .env как DEV_VIDEO_NOTE_ID")

async def cmd_photoid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    m = update.message
    if m and m.reply_to_message and m.reply_to_message.photo:
        await m.reply_text(f"[ADMIN] example file_id: {m.reply_to_message.photo[-1].file_id}")
        return
    if m and m.photo:
        await m.reply_text(f"[ADMIN] example file_id: {m.photo[-1].file_id}")
        return
    await m.reply_text("Пришлите фото или ответьте на него командой /photoid.")


if __name__ == "__main__":
    main()
