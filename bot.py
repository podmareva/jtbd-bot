import os
from datetime import datetime
import secrets

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters, ContextTypes
)

# если используешь openai — оставь
import openai

# БД (psycopg v3)
import psycopg
from psycopg.rows import dict_row

# ------------------ ENV ------------------
load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")
BOT_TOKEN   = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID    = int(os.getenv("ADMIN_ID", "0"))

# username бота-распаковщика (без @)
BOT_NAME = os.getenv("MAIN_BOT_USERNAME", "jtbd_assistant_bot")

# ------------------ DB runner (без глобального соединения) ------------------
def db_run(sql: str, args: tuple = (), fetch: str | None = None):
    """
    Выполнить SQL с новым подключением и 1 ретраем.
    fetch=None -> execute
    fetch='one' -> fetchone()
    fetch='all' -> fetchall()
    """
    try:
        with psycopg.connect(
            DATABASE_URL,
            sslmode="require",
            autocommit=True,
            row_factory=dict_row,
            keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                if fetch == "one":
                    return cur.fetchone()
                if fetch == "all":
                    return cur.fetchall()
                return None
    except psycopg.OperationalError:
        with psycopg.connect(
            DATABASE_URL,
            sslmode="require",
            autocommit=True,
            row_factory=dict_row,
            keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                if fetch == "one":
                    return cur.fetchone()
                if fetch == "all":
                    return cur.fetchall()
                return None

# ------------------ Схема БД ------------------
db_run("""CREATE TABLE IF NOT EXISTS tokens(
  token TEXT PRIMARY KEY,
  bot_name TEXT NOT NULL,
  user_id BIGINT NOT NULL,
  expires_at TIMESTAMPTZ NULL
);""")

db_run("""CREATE TABLE IF NOT EXISTS allowed_users(
  user_id BIGINT NOT NULL,
  bot_name TEXT NOT NULL,
  PRIMARY KEY(user_id, bot_name)
);""")

# На случай старой схемы:
db_run("ALTER TABLE tokens ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL;")

# ------------------ Данные/сессии ------------------
WELCOME = (
    "👋 Привет! Ты в боте «Твоя распаковка и анализ ЦА» — он поможет:\n"
    "• распаковать твою экспертную личность;\n"
    "• сформировать позиционирование и BIO;\n"
    "• подробно разобрать продукт/услугу;\n"
    "• провести анализ ЦА по JTBD.\n\n"
    "🔐 Доступ выдаётся по персональной ссылке от кассира.\n"
    "✅ Открой меня по своей ссылке и нажми «СТАРТ»."
)

INTERVIEW_Q = [
    "1. Расскажи о своём профессиональном опыте. Чем ты занимаешься?",
    "2. Что вдохновляет тебя в твоей работе?",
    "3. Какие ценности ты считаешь ключевыми в жизни и в деятельности?",
    "4. В чём ты видишь свою миссию или предназначение?",
    "5. Что ты считаешь своим главным достижением?",
    "6. Какие черты характера помогают тебе в работе?",
    "7. Есть ли у тебя принципы или убеждения, которыми ты руководствуешься?",
    "8. Какие темы тебе особенно близки и важны?",
    "9. Какими знаниями и навыками ты особенно гордишься?",
    "10. Какие проблемы тебе особенно хочется решить с помощью своей деятельности?",
    "11. Как ты хочешь, чтобы тебя воспринимали клиенты или подписчики?",
    "12. Какие эмоции ты хочешь вызывать у своей аудитории?",
    "13. В чём ты отличаешься от других в своей нише?",
    "14. Какой образ ты стремишься создать в социальных сетях?",
    "15. Что ты хочешь, чтобы люди говорили о тебе после взаимодействия с твоим контентом или продуктом?"
]

PRODUCT_Q = [
    "1. Опиши свой продукт/услугу максимально просто.",
    "2. Чем он реально помогает клиенту?",
    "3. В чем твое/его главное отличие от других решений на рынке?",
    "4. Какой главный результат получает человек после взаимодействия с тобой или твоим продуктом?"
]

MAIN_MENU = [
    ("📱 BIO", "bio"),
    ("🎯 Продукт / Услуга", "product"),
    ("🔍 Анализ ЦА", "jtbd")
]

sessions = {}

# ------------------ Доступ ------------------
def is_allowed(user_id: int) -> bool:
    row = db_run(
        "SELECT 1 FROM allowed_users WHERE user_id=%s AND bot_name=%s",
        (user_id, BOT_NAME),
        fetch="one",
    )
    return row is not None

def try_accept_token(user_id: int, token: str) -> tuple[bool, str]:
    if not token:
        return False, "⛔ Доступ по персональной ссылке. Попросите кассира выдать доступ."

    row = db_run("SELECT * FROM tokens WHERE token=%s", (token,), fetch="one")
    if not row:
        return False, "⛔ Ссылка недействительна или уже активирована."

    if row["bot_name"] != BOT_NAME:
        return False, "⛔ Этот токен выдан для другого бота."

    exp = row.get("expires_at")
    if exp and datetime.utcnow() > exp.replace(tzinfo=None):
        return False, "⛔ Срок действия ссылки истёк. Попросите кассира выдать новую."

    # OK — фиксируем доступ и сжигаем токен
    db_run(
        "INSERT INTO allowed_users(user_id, bot_name) VALUES(%s,%s) ON CONFLICT DO NOTHING",
        (user_id, BOT_NAME)
    )
    db_run("DELETE FROM tokens WHERE token=%s", (token,))
    return True, "✅ Доступ активирован. Можно пользоваться ботом."

def _uid_from_update(update):
    if getattr(update, "effective_user", None):
        return update.effective_user.id
    if getattr(update, "callback_query", None):
        return update.callback_query.from_user.id
    return None

def require_access(fn):
    """Декоратор: пропускает только тех, у кого активирован доступ (кроме /start)."""
    async def wrapper(update, context, *args, **kwargs):
        uid = _uid_from_update(update)
        if ADMIN_ID and uid == ADMIN_ID:
            return await fn(update, context, *args, **kwargs)
        if uid is None or not is_allowed(uid):
            if getattr(update, "message", None):
                await update.message.reply_text("⛔ Доступ не активирован. Откройте бота по персональной ссылке от кассира.")
            elif getattr(update, "callback_query", None):
                await update.callback_query.answer("⛔ Доступ не активирован. Откройте бота по персональной ссылке от кассира.", show_alert=True)
            return
        return await fn(update, context, *args, **kwargs)
    return wrapper

async def send_welcome(ctx: ContextTypes.DEFAULT_TYPE, uid: int):
    # Кнопка согласия, чтобы перейти к интервью
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Согласен(а) — начать распаковку", callback_data="agree")]
    ])
    # Инициализация сессии
    sessions[uid] = {
        "stage": "welcome",
        "answers": [],
        "product_answers": [],
        "products": []
    }
    await ctx.bot.send_message(chat_id=uid, text=WELCOME, reply_markup=kb)

# ------------------ HANDLERS ------------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    args = ctx.args or []

    # Уже есть доступ? Показываем приветствие и стартовый экран
    if is_allowed(uid):
        await update.message.reply_text("🔓 Доступ уже активирован. Запускаю распаковку.")
        await send_welcome(ctx, uid)
        return

    # Пробуем принять токен из /start <token>
    token = args[0] if args else ""
    ok, msg = try_accept_token(uid, token)
    await update.message.reply_text(msg)

    if ok:
        # Сразу запускаем сценарий
        await send_welcome(ctx, uid)
        return
    else:
        # Без токена — дальше не идём
        return

# Админ: ручная генерация токена в Postgres для этого бота
async def gentoken(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Только для администратора.")
        return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Использование: /gentoken <user_id>")
        return
    target_id = int(ctx.args[0])
    token = secrets.token_urlsafe(8)
    # без TTL (или добавь expires_at теперь()+interval)
    db_run(
        "INSERT INTO tokens(token, bot_name, user_id, expires_at) VALUES(%s,%s,%s,NULL) ON CONFLICT DO NOTHING",
        (token, BOT_NAME, target_id)
    )
    link = f"https://t.me/{BOT_NAME}?start={token}"
    await update.message.reply_text(
        f"✅ Токен: <code>{token}</code>\n🔗 Ссылка: {link}",
        parse_mode="HTML"
    )

@require_access
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    query = update.callback_query
    data = query.data
    sess = sessions.get(cid)
    await query.answer()
    if not sess:
        return

    # --- Согласие ---
    if sess["stage"] == "welcome" and data == "agree":
        sess["stage"] = "interview"
        await ctx.bot.send_message(
            chat_id=cid,
            text="✅ Спасибо за согласие!\n\nТеперь начнём распаковку личности.\nЯ задам тебе 15 вопросов — отвечай подробно и честно 👇"
        )
        await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[0])
        return

    # --- BIO по кнопке ---
    if sess["stage"] == "done_interview" and data == "bio":
        sess["stage"] = "bio"
        await generate_bio(cid, sess, ctx)
        return

    # --- Переход к продукту ---
    if sess["stage"] in ("done_interview", "done_bio") and data == "product":
        sess["stage"] = "product_ask"
        sess["product_answers"] = []
        await ctx.bot.send_message(chat_id=cid, text=PRODUCT_Q[0])
        return

    # --- Следующий продукт (мультипродукт!) ---
    if sess["stage"] == "product_finished" and data == "add_product":
        sess["stage"] = "product_ask"
        sess["product_answers"] = []
        await ctx.bot.send_message(chat_id=cid, text="Окей! Расскажи о новом продукте 👇\n" + PRODUCT_Q[0])
        return

    if sess["stage"] == "product_finished" and data == "finish_products":
        await ctx.bot.send_message(chat_id=cid, text="Переходим к анализу ЦА...")
        await start_jtbd(cid, sess, ctx)
        return

    # --- Переход к JTBD ---
    if sess["stage"] in ("done_interview", "done_bio", "done_product") and data == "jtbd":
        await start_jtbd(cid, sess, ctx)
        return

    # JTBD ещё раз или завершить
    if sess["stage"] == "jtbd_done" and data == "jtbd_again":
        await start_jtbd(cid, sess, ctx)
        return
    if sess["stage"] == "jtbd_done" and data == "finish_unpack":
        await ctx.bot.send_message(
            chat_id=cid,
            text="✅ Распаковка завершена!\n\n"
                 "Спасибо за работу! Теперь ты можешь использовать Контент-ассистента для стратегий и идей. "
                 "Если нужна помощь — пиши!"
        )
        return

    if data == "jtbd_more" and sess.get("stage") == "jtbd_first":
        await handle_more_jtbd(update, ctx)
        return

    if data == "jtbd_done" and sess.get("stage") == "jtbd_first":
        await handle_skip_jtbd(update, ctx)
        return

@require_access
async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    text = (update.message.text or "").strip()
    if not sess:
        return

@require_access
async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    text = (update.message.text or "").strip()

    # Если сессии нет (например, бот рестартанулся) — покажем приветствие
    if not sess:
        await send_welcome(ctx, cid)
        return

    # ---------- INTERVIEW FLOW ----------
    if sess["stage"] == "interview":
        sess["answers"].append(text)
        try:
            comment = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Ты — поддерживающий коуч. На «ты». Дай короткий комментарий к ответу — по теме, дружелюбно, без вопросов."},
                    {"role": "user", "content": text}
                ]
            )
            await ctx.bot.send_message(chat_id=cid, text=comment.choices[0].message.content)
        except Exception as e:
            await ctx.bot.send_message(chat_id=cid, text="⚠️ Не удалось получить комментарий, но мы продолжаем.")
            print("OpenAI comment error:", e)

        idx = len(sess["answers"])
        if idx < len(INTERVIEW_Q):
            await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[idx])
        else:
            print(f"[INFO] Завершаем интервью для cid {cid}")
            await finish_interview(cid, sess, ctx)
        return

    # ---------- PRODUCT FLOW с мультипродуктом ----------
    if sess["stage"] == "product_ask":
        sess["product_answers"].append(text)
        idx = len(sess["product_answers"])
        if idx < len(PRODUCT_Q):
            await ctx.bot.send_message(chat_id=cid, text=PRODUCT_Q[idx])
        else:
            # Сохраняем продукт (все его ответы)
            sess.setdefault("products", []).append(sess["product_answers"].copy())
            await generate_product_analysis(cid, sess, ctx)
            # Спрашиваем: есть ли ещё продукты?
            kb = [
                [InlineKeyboardButton("Добавить ещё продукт", callback_data="add_product")],
                [InlineKeyboardButton("Перейти к анализу ЦА", callback_data="finish_products")]
            ]
            await ctx.bot.send_message(
                chat_id=cid,
                text="Спасибо! Все ответы по продукту получены.\nХочешь рассказать ещё об одном продукте?",
                reply_markup=InlineKeyboardMarkup(kb)
            )
            sess["stage"] = "product_finished"
        return

# ------------------ Генерации ------------------
async def finish_interview(cid, sess, ctx):
    answers = "\n".join(sess["answers"])
    style_note = (
        "\n\nОбрати внимание: используй стиль, лексику, энергетику и выражения, которые пользователь использовал в своих ответах. "
        "Пиши в его манере — не переусложняй, не добавляй шаблонные фразы, старайся повторять тональность."
    )
    unpack = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты профессиональный коуч и бренд-стратег. На основе ответов проведи глубокую, подробную распаковку личности: "
                    "раскрой ценности, жизненные и профессиональные убеждения, сильные стороны, уникальные черты, мотивы, личную историю, "
                    "цели, миссию, послание для аудитории, триггеры, раскрывающие потенциал. Пиши на русском языке, с деталями и живыми примерами, "
                    "разбивая по логическим блокам с подзаголовками. Формат — Markdown."
                    + style_note
                )
            },
            {"role": "user", "content": answers}
        ]
    )
    unpack_text = unpack.choices[0].message.content
    sess["unpacking"] = unpack_text
    await send_long_message(ctx, cid, "✅ Твоя распаковка:\n\n" + unpack_text)

    pos = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты бренд-стратег. На основе распаковки личности подробно сформулируй позиционирование на русском языке "
                    "в развернутом виде — от лица человека (1–2 абзаца о себе), затем детализируй: "
                    "— основные направления развития\n"
                    "— ключевые ценности\n"
                    "— сильные стороны\n"
                    "— послание для аудитории\n"
                    "— миссия\n"
                    "— слоган (1 фраза)\n"
                    "— цель сообщества (если есть)\n"
                    "— уникальность и отличия\n"
                    "— итоговый призыв к действию\n\n"
                    "Сначала дай общий абзац о человеке, затем — остальные пункты с подзаголовками и списками. Всё на русском, стильно и вдохновляюще. Формат Markdown."
                    + style_note
                )
            },
            {"role": "user", "content": unpack_text}
        ]
    )
    positioning_text = pos.choices[0].message.content
    sess["positioning"] = positioning_text

    await send_long_message(ctx, cid, "🎯 Позиционирование:\n\n" + positioning_text)

    sess["stage"] = "done_interview"
    kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU]
    await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

async def generate_bio(cid, sess, ctx):
    style_note = "\n\nОбрати внимание: используй стиль и лексику пользователя, пиши фразы в его манере."
    prompt = (
        "На основе позиционирования сгенерируй 5 вариантов короткого BIO для шапки профиля Instagram на русском языке. "
        "Каждый вариант — 2–3 цепляющих, лаконичных фразы подряд, разделённых слэшами («/»), без списков, без заголовков и пояснений, не более 180 символов. "
        "Варианты пиши только текстом, без оформления Markdown и без номеров. Формулировки — живые, в стиле Instagram: вызывай интерес, добавь call-to-action или эмоцию."
        + style_note + "\n\n" + sess["positioning"]
    )
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}])
    await ctx.bot.send_message(chat_id=cid, text="📱 Варианты BIO:\n\n" + resp.choices[0].message.content)
    sess["stage"] = "done_bio"
    kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU if c != "bio"]
    await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

async def generate_product_analysis(cid, sess, ctx):
    style_note = "\n\nСохраняй стиль, лексику и тональность пользователя (ориентируйся на его оригинальные формулировки)."
    answers = "\n".join(sess["product_answers"])
    prompt = (
        "На основе ответов пользователя на вопросы о продукте, напиши краткий анализ продукта для Telegram в 3–5 предложениях. "
        "Раскрой суть продукта, ключевые выгоды, отличия от конкурентов, результат для клиента. Язык — русский, стиль деловой, но понятный."
        + style_note + "\n\n" + answers
    )
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}])
    await ctx.bot.send_message(chat_id=cid, text="📝 Краткий анализ продукта:\n\n" + resp.choices[0].message.content)

async def send_long_message(ctx, cid, text):
    MAX_LEN = 4000
    for i in range(0, len(text), MAX_LEN):
        await ctx.bot.send_message(chat_id=cid, text=text[i:i+MAX_LEN], parse_mode="HTML")

@require_access
async def start_jtbd(cid, sess, ctx):
    all_products = []
    for prod in sess.get("products", []):
        all_products.append("\n".join(prod))
    ctx_text = "\n".join(sess["answers"]) + "\n" + "\n\n".join(all_products)
    style_note = "\n\nПиши подробно, с примерами, в стиле и лексике пользователя. Избегай шаблонных формулировок и повторов."
    prompt = (
        "На основе распаковки, позиционирования и всех продуктов составь РОВНО 5 ключевых сегментов целевой аудитории (ЦА), строго по шаблону и с HTML-разметкой:\n\n"
        "<b>Сегмент 1: ...</b>\n"
        "<u>JTBD:</u> ...\n\n"
        "<u>Потребности:</u> ...\n\n"
        "<u>Боли:</u> ...\n\n"
        "<u>Решения:</u> ...\n\n"
        "<u>Темы для контента:</u> ...\n\n"
        "<u>Психографика:</u> ...\n\n"
        "<u>Поведенческая сегментация:</u> ...\n\n"
        "<u>Оффер:</u> ...\n\n"
        "Оформи строго 5 таких сегментов, каждый — отдельным блоком. Только HTML-теги для оформления. Ответ только на русском языке."
        + style_note +
        "\n\nИсходная информация:\n" + ctx_text
    )
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}])
    await send_long_message(ctx, cid, "🎯 Основные сегменты ЦА:\n\n" + resp.choices[0].message.content)
    await ctx.bot.send_message(
        chat_id=cid,
        text="Хочешь увидеть неочевидные сегменты ЦА?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Хочу дополнительные сегменты", callback_data="jtbd_more")],
            [InlineKeyboardButton("Хватит, благодарю", callback_data="jtbd_done")]
        ])
    )
    sess["stage"] = "jtbd_first"

@require_access
async def handle_more_jtbd(update, ctx):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    all_products = []
    for prod in sess.get("products", []):
        all_products.append("\n".join(prod))
    ctx_text = "\n".join(sess["answers"]) + "\n" + "\n\n".join(all_products)
    style_note = (
        "\n\nПиши подробно, в стиле пользователя, избегай шаблонов и повторов. Для каждого сегмента дай не менее 5 идей для контента. "
        "Психографику разбей на интересы, ценности, страхи."
    )
    prompt = (
        "Добавь ещё 3 неочевидных сегмента целевой аудитории (ЦА), строго по шаблону и с HTML-разметкой... "
        + style_note + "\n\nИсходная информация:\n" + ctx_text
    )
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}])
    await send_long_message(ctx, cid, "🔍 Дополнительные неочевидные сегменты:\n\n" + resp.choices[0].message.content)
    await ctx.bot.send_message(
        chat_id=cid,
        text="Что дальше?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Проанализировать ЦА ещё раз", callback_data="jtbd_again")],
            [InlineKeyboardButton("Завершить распаковку", callback_data="finish_unpack")]
        ])
    )
    sess["stage"] = "jtbd_done"

@require_access
async def handle_skip_jtbd(update, ctx):
    cid = update.effective_chat.id
    await ctx.bot.send_message(
        chat_id=cid,
        text=(
            "Принято! 👌\n\n"
            "Если захочешь сделать следующий шаг и системно работать с контентом — знай, что у меня есть Контент-ассистент 🤖\n\n"
            "Он поможет:\n"
            "• создать стратегию под любую соцсеть\n"
            "• сформировать рубрики и контент-план\n"
            "• написать посты, сторис и даже сценарии видео\n\n"
            "Подключим его?"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🪄 Получить доступ", callback_data="get_access")],
            [InlineKeyboardButton("✅ Уже в арсенале", callback_data="have")],
            [InlineKeyboardButton("⏳ Обращусь позже", callback_data="later")]
        ])
    )
    sessions[cid]["stage"] = "jtbd_done"

# ------------------ MAIN ------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gentoken", gentoken))  # админская

    # кнопки/сообщения
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CallbackQueryHandler(handle_more_jtbd, pattern="jtbd_more"))
    app.add_handler(CallbackQueryHandler(handle_skip_jtbd, pattern="jtbd_done"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
