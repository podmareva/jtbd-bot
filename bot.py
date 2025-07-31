import os
import sys
import sqlite3
import secrets
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters, ContextTypes
)
import openai

# ---------- НАСТРОЙКИ ----------

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
MAIN_BOT_USERNAME = os.getenv("MAIN_BOT_USERNAME", "MainBotName")  # указать в .env

# ---------- SQLite: ДОСТУП ЧЕРЕЗ ТОКЕН ----------

DB_PATH = "tokens.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            used INTEGER DEFAULT 0
        )
        """)
init_db()

def create_token(user_id):
    token = secrets.token_urlsafe(8)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO tokens (token, user_id, used) VALUES (?, ?, 0)", (token, user_id))
    return token

def validate_token(token, user_id):
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute(
            "SELECT used, user_id FROM tokens WHERE token = ?", (token,)
        ).fetchone()
        if not res:
            return False, "Неверный токен."
        used, db_uid = res
        if used:
            return False, "Токен уже использован."
        if db_uid != user_id:
            return False, "Нет доступа. Этот токен для другого пользователя."
        conn.execute("UPDATE tokens SET used = 1 WHERE token = ?", (token,))
        return True, None

# ---------- ДАННЫЕ ----------
WELCOME = (
    "👋 Привет! Ты в боте «Твоя распаковка и анализ ЦА» — он поможет:\n"
    "• распаковать твою экспертную личность;\n"
    "• сформировать позиционирование и BIO;\n"
    "• подробно разобрать продукт/услугу;\n"
    "• провести анализ ЦА по JTBD.\n\n"
    "🔐 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности](https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit?usp=drive_link&ouid=104429050326439982568&rtpof=true&sd=true) и "
    "[Договором‑офертой](https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit?usp=drive_link&ouid=104429050326439982568&rtpof=true&sd=true).\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!"
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

# ---------- HANDLERS ----------

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    user_id = update.effective_user.id

    # --- Доступ по токену ---
    args = ctx.args if hasattr(ctx, "args") else []
    if args:
        token = args[0]
        valid, reason = validate_token(token, user_id)
        if not valid:
            await ctx.bot.send_message(chat_id=cid, text=f"⛔️ {reason}")
            return
    else:
        if user_id != ADMIN_ID:
            await ctx.bot.send_message(chat_id=cid, text="⛔️ Нет доступа. Получи персональную ссылку у администратора.")
            return

    sessions[cid] = {
        "stage": "welcome",
        "answers": [],
        "product_answers": [],
        "products": []
    }
    kb = [[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await ctx.bot.send_message(chat_id=cid, text=WELCOME, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def gentoken(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        await ctx.bot.send_message(chat_id=cid, text="⛔️ Только для администратора.")
        return

    if not ctx.args or not ctx.args[0].isdigit():
        await ctx.bot.send_message(chat_id=cid, text="Используй: /gentoken user_id (числовой Telegram ID)")
        return

    target_id = int(ctx.args[0])
    token = create_token(target_id)
    link = f"https://t.me/{MAIN_BOT_USERNAME}?start={token}"

    await ctx.bot.send_message(
        chat_id=cid,
        text=f"✅ Токен сгенерирован: <code>{token}</code>\n"
             f"🔗 Ссылка для пользователя:\n{link}",
        parse_mode="HTML"
    )

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

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    text = update.message.text.strip()
    if not sess:
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

    # Здесь идут другие этапы, если есть

async def finish_interview(cid, sess, ctx):
    print(f"[INFO] Генерация распаковки для cid {cid}")
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

    print(f"[INFO] Генерация позиционирования для cid {cid}")
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

    # Разбиваем позиционирование на 2+ сообщений, если очень длинно
    await send_long_message(ctx, cid, "🎯 Позиционирование:\n\n" + positioning_text)

    sess["stage"] = "done_interview"
    kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU]
    await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
    return

# ---------- BIO ----------
async def generate_bio(cid, sess, ctx):
    style_note = (
        "\n\nОбрати внимание: используй стиль и лексику пользователя, пиши фразы в его манере."
    )
    prompt = (
        "На основе позиционирования сгенерируй 5 вариантов короткого BIO для шапки профиля Instagram на русском языке. "
        "Каждый вариант — 2–3 цепляющих, лаконичных фразы подряд, разделённых слэшами («/»), без списков, без заголовков и пояснений, не более 180 символов. "
        "Варианты пиши только текстом, без оформления Markdown и без номеров. Формулировки — живые, в стиле Instagram: вызывай интерес, добавь call-to-action или эмоцию."
        + style_note
        + "\n\n"
        + sess["positioning"]
    )
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    await ctx.bot.send_message(
        chat_id=cid,
        text="📱 Варианты BIO:\n\n" + resp.choices[0].message.content
    )
    sess["stage"] = "done_bio"
    kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU if c != "bio"]
    await ctx.bot.send_message(
        chat_id=cid,
        text="Что дальше?",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ---------- КРАТКИЙ АНАЛИЗ ПРОДУКТА (учёт стиля пользователя) ----------
async def generate_product_analysis(cid, sess, ctx):
    style_note = (
        "\n\nСохраняй стиль, лексику и тональность пользователя (ориентируйся на его оригинальные формулировки)."
    )
    answers = "\n".join(sess["product_answers"])
    prompt = (
        "На основе ответов пользователя на вопросы о продукте, напиши краткий анализ продукта для Telegram в 3–5 предложениях. "
        "Раскрой суть продукта, ключевые выгоды, отличия от конкурентов, результат для клиента. Язык — русский, стиль деловой, но понятный."
        + style_note
        + "\n\n"
        + answers
    )
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    await ctx.bot.send_message(
        chat_id=cid,
        text="📝 Краткий анализ продукта:\n\n" + resp.choices[0].message.content
    )

# ---------- ДЛИННОСООБЩЕНИЯ ----------
async def send_long_message(ctx, cid, text):
    MAX_LEN = 4000
    for i in range(0, len(text), MAX_LEN):
        await ctx.bot.send_message(chat_id=cid, text=text[i:i+MAX_LEN])

# ---------- JTBD (5 сегментов, учёт всех продуктов, стиль пользователя) ----------
async def start_jtbd(cid, sess, ctx):
    all_products = []
    for prod in sess.get("products", []):
        all_products.append("\n".join(prod))
    ctx_text = "\n".join(sess["answers"]) + "\n" + "\n\n".join(all_products)
    style_note = (
        "\n\nПиши подробно, с примерами, в стиле и лексике пользователя. Избегай шаблонных формулировок и повторов."
    )
    prompt = (
        "На основе распаковки, позиционирования и всех продуктов составь подробный разбор 5 ключевых сегментов целевой аудитории (ЦА) по такому шаблону:\n\n"
        "Пример сегмента:\n"
        "Сегмент 1: Самостоятельные, но перегруженные\n"
        "JTBD: Найти проверенное решение, чтобы не тратить время на ошибки и убрать хаос в доме.\n"
        "Потребности: Порядок, структурные советы, минимизация действий, экономия времени.\n"
        "Боли: Ошибки в решениях, страх ошибок, усталость, чувство вины.\n"
        "Решения: Онлайн-консультация, чек-листы, разбор типичных ошибок, индивидуальные рекомендации.\n"
        "Темы для контента: «5 ошибок при самостоятельном ремонте», «Как сделать планировку кухни без хаоса», «Техника наведения порядка», «Как выбрать мебель для маленькой квартиры», «Как не сойти с ума при переезде».\n"
        "Психографика: Озадачены, устают от хаоса, ищут поддержку, ценят простоту и комфорт.\n"
        "Поведенческая сегментация: Активно ищут информацию, читают отзывы, подписаны на дизайнеров, делятся своими кейсами в чатах.\n"
        "Оффер: Самостоятельно наведи порядок — получи поддержку дизайнера и пошаговый чек-лист.\n\n"
        "Для каждого сегмента оформи ответ по шаблону, используя такие поля:\n"
        "— Сегмент ЦА (уникальное имя)\n"
        "— JTBD (работа клиента)\n"
        "— Потребности (опиши и скрытые мотивы)\n"
        "— Боли (подробно)\n"
        "— Решения (твои продукты/услуги для этого сегмента)\n"
        "— Темы для контента (приводи минимум 5 идей)\n"
        "— Психографика (раздели на интересы, ценности, страхи)\n"
        "— Поведенческая сегментация (детализируй, как ищут решения, как себя ведут)\n"
        "— Оффер (одно-два ёмких предложения для продажи)\n\n"
        "Детализируй каждый пункт с примерами. Не используй таблицы и markdown. Только текст. Ответ только на русском языке."
        + style_note +
        "\n\nИсходная информация:\n" + ctx_text
    )
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    await send_long_message(ctx, cid, "🎯 Основные сегменты ЦА:\n\n" + resp.choices[0].message.content)
    # Кнопка для доп. сегментов
    await ctx.bot.send_message(
        chat_id=cid,
        text="Хочешь увидеть неочевидные сегменты ЦА?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Хочу дополнительные сегменты", callback_data="jtbd_more")],
            [InlineKeyboardButton("Хватит, благодарю", callback_data="jtbd_done")]
        ])
    )
    sess["stage"] = "jtbd_first"

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
        "Добавь ещё 3 неочевидных сегмента целевой аудитории (ЦА) по шаблону:\n\n"
        "Пример:\n"
        "Сегмент 6: Ценители уюта и необычных решений\n"
        "JTBD: Найти идеи для создания стильного и уютного пространства, чтобы проявить индивидуальность.\n"
        "Потребности: Атмосфера, комфорт, оригинальные детали, простота реализации.\n"
        "Боли: Неумение реализовать задумку самостоятельно, страх ошибок в декоре.\n"
        "Решения: Видеоинструкции, подбор материалов, сопровождение на всех этапах.\n"
        "Темы для контента: «5 нестандартных решений для малогабаритной квартиры», «Как объединить разные стили», «ТОП-10 уютных аксессуаров», «Провальные идеи декора: как не повторить», «Где искать вдохновение».\n"
        "Психографика: Интересы — интерьер, Pinterest, скандинавский стиль; ценности — индивидуальность, комфорт; страхи — показаться банальным.\n"
        "Поведенческая сегментация: Активно ищут необычные идеи, участвуют в челленджах, делятся примерами, смотрят блоги о дизайне.\n"
        "Оффер: Создай уют без ошибок — получи подборку идей и бесплатную консультацию по твоей задумке!\n\n"
        "Оформи каждый сегмент по такому же шаблону. Не используй markdown. Только текст на русском языке."
        + style_note +
        "\n\nИсходная информация:\n" + ctx_text
    )
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
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

async def handle_skip_jtbd(update, ctx):
    cid = update.effective_chat.id
    await ctx.bot.send_message(
        chat_id=cid,
        text="Поняла! 😊\n\n"
             "Если захочешь сделать следующий шаг и системно работать с контентом — знай, что у меня есть Контент-ассистент 🤖\n\n"
             "Он поможет:\n"
             "• создать стратегию под любую соцсеть\n"
             "• сформировать рубрики и контент-план\n"
             "• написать посты, сторис и даже сценарии видео\n\n"
             "Подключим его?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🪄 Получить доступ", callback_data="get_access")],
            [InlineKeyboardButton("✅ Уже в арсенале", callback_data="have")],
            [InlineKeyboardButton("⏳ Обращусь позже", callback_data="later")]
        ])
    )
    sessions[cid]["stage"] = "done_jtbd"

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gentoken", gentoken))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(handle_more_jtbd, pattern="jtbd_more"))
    app.add_handler(CallbackQueryHandler(handle_skip_jtbd, pattern="jtbd_done"))
    app.run_polling()

if __name__ == "__main__":
    main()
