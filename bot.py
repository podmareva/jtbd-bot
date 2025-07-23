import os
import sys
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters, ContextTypes
)
import openai
print(">>> Бот загружен, файл bot.py исполняется")

# ---------- НАСТРОЙКИ ----------

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Защита от двойного запуска
if "RUNNING_BOT" in os.environ:
    print("❌ Бот уже запущен. Останови другой процесс, чтобы избежать конфликта.")
    sys.exit(1)
os.environ["RUNNING_BOT"] = "1"

sessions = {}

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

# ---------- HANDLERS ----------

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    print(">>> Функция /start вызвана")
    cid = update.effective_chat.id
    sessions[cid] = {"stage": "welcome", "answers": [], "product_answers": []}
    kb = [[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await ctx.bot.send_message(chat_id=cid, text=WELCOME, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

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

    # --- Переход к JTBD ---
    if sess["stage"] in ("done_interview", "done_bio", "done_product") and data == "jtbd":
        await start_jtbd(cid, sess, ctx)
        return

    if data == "jtbd_more" and sess["stage"] == "jtbd_first":
        await handle_more_jtbd(update, ctx)
        return

    if data == "jtbd_done" and sess["stage"] == "jtbd_first":
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

    # ---------- PRODUCT FLOW ----------
    if sess["stage"] == "product_ask":
        sess["product_answers"].append(text)
        idx = len(sess["product_answers"])
        if idx < len(PRODUCT_Q):
            await ctx.bot.send_message(chat_id=cid, text=PRODUCT_Q[idx])
        else:
            # Сначала анализ продукта
            await generate_product_analysis(cid, sess, ctx)
            # Потом сообщение и кнопка Анализ ЦА
            await ctx.bot.send_message(
                chat_id=cid,
                text="Спасибо! Все ответы по продукту получены.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Анализ ЦА", callback_data="jtbd")]
                ])
            )
            sess["stage"] = "done_product"
        return

    # Тут идут другие этапы, если есть

async def finish_interview(cid, sess, ctx):
    print(f"[INFO] Генерация распаковки для cid {cid}")
    answers = "\n".join(sess["answers"])

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
                )
            },
            {"role": "user", "content": answers}
        ]
    )
    unpack_text = unpack.choices[0].message.content
    sess["unpacking"] = unpack_text
    await ctx.bot.send_message(chat_id=cid, text="✅ Твоя распаковка:\n\n" + unpack_text)

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
                )
            },
            {"role": "user", "content": unpack_text}
        ]
    )
    positioning_text = pos.choices[0].message.content
    sess["positioning"] = positioning_text

    # Разбиваем позиционирование на два сообщения
    parts = positioning_text.split('\n\n', 1)
    await ctx.bot.send_message(chat_id=cid, text="🎯 Позиционирование:\n\n" + parts[0])
    if len(parts) > 1:
        await ctx.bot.send_message(chat_id=cid, text=parts[1])

    sess["stage"] = "done_interview"
    kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU]
    await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
    return

# ---------- BIO ----------
async def generate_bio(cid, sess, ctx):
    prompt = (
        "На основе позиционирования сгенерируй 5 вариантов короткого BIO для шапки профиля Instagram на русском языке. "
        "Каждый вариант — 2–3 цепляющих, лаконичных фразы подряд, разделённых слэшами («/»), без списков, без заголовков и пояснений, не более 180 символов. "
        "Варианты пиши только текстом, без оформления Markdown и без номеров. Формулировки — живые, в стиле Instagram: вызывай интерес, добавь call-to-action или эмоцию."
        "\n\n"
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

# ---------- PRODUCT ANALYSIS ----------
async def generate_product_analysis(cid, sess, ctx):
    prompt = (
        "На основе ответов пользователя на вопросы о продукте, напиши краткий анализ продукта для Telegram в 3–5 предложениях. "
        "Раскрой суть продукта, ключевые выгоды, отличия от конкурентов, результат для клиента. Язык — русский, стиль деловой, но понятный."
        "\n\n"
        + "\n".join(sess["product_answers"])
    )
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    await ctx.bot.send_message(
        chat_id=cid,
        text="📝 Краткий анализ продукта:\n\n" + resp.choices[0].message.content
    )

# ---------- JTBD ----------
async def start_jtbd(cid, sess, ctx):
    ctx_text = "\n".join(sess["answers"] + sess["product_answers"])
    prompt = (
        "Сформулируй 3–4 основных сегмента ЦА по методу JTBD на основании распаковки, позиционирования и продукта. "
        "Для каждого сегмента укажи:\n"
        "- Job‑to‑be‑done\n- Неочевидные потребности\n- Неочевидные боли\n"
        "- Триггеры\n- Барьеры\n- Альтернативы\n\n"
        "Исходная информация:\n" + ctx_text
    )
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    await ctx.bot.send_message(
        chat_id=cid,
        text="🎯 Основные сегменты ЦА:\n\n" + resp.choices[0].message.content,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Хочу дополнительные сегменты", callback_data="jtbd_more")],
            [InlineKeyboardButton("Хватит, благодарю", callback_data="jtbd_done")]
        ])
    )
    sess["stage"] = "jtbd_first"

async def handle_more_jtbd(update, ctx):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    ctx_text = "\n".join(sess["answers"] + sess["product_answers"])
    prompt = (
        "Добавь ещё 3 неочевидных сегмента ЦА по JTBD в том же формате также на основании распаковки, позиционирования и продукта. "
        "(Job, потребности, боли, триггеры, барьеры, альтернативы):\n\n" + ctx_text
    )
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    await ctx.bot.send_message(
        chat_id=cid,
        text="🔍 Дополнительные сегменты:\n\n" + resp.choices[0].message.content
    )
    await ctx.bot.send_message(
        chat_id=cid,
        text="✅ Распаковка и анализ ЦА завершены — теперь у тебя есть фундамент для позиционирования, упаковки и коммуникации.\n\n"
             "Следующий шаг — системная и креативная работа с контентом.\n"
             "У меня как раз есть компаньон: *Контент-ассистент* 🤖\n\n"
             "Он поможет:\n"
             "• создать стратегию под любую соцсеть\n"
             "• сформировать рубрики и контент-план\n"
             "• написать посты, сторис и даже сценарии видео\n\n"
             "Хочешь подключить его прямо сейчас?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🪄 Получить доступ", callback_data="get_access")],
            [InlineKeyboardButton("✅ Уже в арсенале", callback_data="have")],
            [InlineKeyboardButton("⏳ Обращусь позже", callback_data="later")]
        ])
    )
    sess["stage"] = "done_jtbd"

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
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    # Доп. обработчики JTBD‑кнопок
    app.add_handler(CallbackQueryHandler(handle_more_jtbd, pattern="jtbd_more"))
    app.add_handler(CallbackQueryHandler(handle_skip_jtbd, pattern="jtbd_done"))
    app.run_polling()

if __name__ == "__main__":
    main
