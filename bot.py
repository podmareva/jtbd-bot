import os
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters, ContextTypes
)
import openai

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")

sessions = {}

WELCOME = (
    "👋 Привет! Ты в боте «Твоя распаковка и анализ ЦА» — он поможет:\n"
    "• распаковать твою экспертную личность;\n"
    "• сформировать позиционирование и BIO;\n"
    "• подробно разобрать продукт/услугу;\n"
    "• провести анализ ЦА по методу JTBD.\n\n"
    "🔐 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности](https://docs.google.com/…) и "
    "[Договором‑офертой](https://docs.google.com/…)\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!"
)

INTERVIEW_Q = [
    "1. Чем ты занимаешься и почему ты выбрал это направление?",
    "2. Какие ценности лежат в основе твоей деятельности?",
    "3. Что для тебя самое важное в работе с клиентами?",
    "4. Какие у тебя сильные стороны как эксперта?",
    "5. Что тебя вдохновляет и даёт силы продолжать?",
    "6. Какие принципы ты не меняешь ни при каких обстоятельствах?",
    "7. Каким ты хочешь быть в глазах своей аудитории?",
    "8. Каким опытом ты хочешь делиться чаще всего?",
    "9. Какие изменения хочешь принести в жизнь клиентов?",
    "10. Чем ты отличаешься от других специалистов?",
    "11. Есть ли у тебя миссия, которую ты транслируешь?",
    "12. Какие темы считаешь важными для твоего контента?",
    "13. С какими клиентами тебе интересно работать?",
    "14. Есть ли истории клиентов, которые тебя вдохновили?",
    "15. Какими достижениями ты особенно гордишься?"
]

MAIN_MENU = [
    ("📱 BIO", "bio"),
    ("🎯 Продукт / Услуга", "product"),
    ("🔍 Анализ ЦА", "jtbd")
]

FINAL_MENU = [
    ("🪄 Получить доступ", "get_access"),
    ("✅ Уже в арсенале", "have"),
    ("⏳ Обращусь позже", "later")
]

def ask_openai(messages):
    return openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=messages).choices[0].message.content

def chunk_send(bot, chat_id, text, max_len=3000):
    parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
    for part in parts:
        bot.send_message(chat_id=chat_id, text=part)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sessions[cid] = {"stage": "welcome", "answers": [], "product_answers": []}
    kb = [[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await ctx.bot.send_message(chat_id=cid, text=WELCOME, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    query = update.callback_query; data = query.data
    sess = sessions.get(cid)
    await query.answer()
    if not sess:
        return
    
    if sess["stage"] == "welcome" and data == "agree":
        sess["stage"] = "interview"
        sess["answers"] = []
        await ctx.bot.send_message(chat_id=cid, text="✅ Спасибо за согласие!\n\nТеперь начнём распаковку личности.\nЯ задам тебе 15 вопросов — отвечай просто и честно 👇")
        await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[0])
        return

    if sess["stage"] == "done_interview" and data == "bio":
        sess["stage"] = "bio"
        await generate_bio(cid, sess, ctx)
        return

    if sess["stage"] in ("done_interview", "done_bio") and data == "product":
        sess["stage"] = "product_ask"
        sess["product_answers"] = []
        await ctx.bot.send_message(chat_id=cid, text="🎯 Расскажи о продукте/услуге — живо, как презентацию клиентах.")
        return

    if sess["stage"] in ("done_interview", "done_bio", "done_product") and data == "jtbd":
        await start_jtbd(cid, sess, ctx)
        return

    if sess["stage"] == "jtbd_first" and data == "jtbd_more":
        await handle_more_jtbd(update, ctx)
        return

    if sess["stage"] == "jtbd_first" and data == "jtbd_done":
        await handle_skip_jtbd(update, ctx)
        return

async def generate_bio(cid, sess, ctx):
    positioning = sess.get("positioning", "")
    prompt = (
        "На основе этого позиционирования сформулируй 5 вариантов короткого BIO для Instagram (до 180 символов):\n\n"
        + positioning
    )
    bio_text = ask_openai([{"role": "user", "content": prompt}])
    chunk_send(ctx.bot, cid, bio_text)
    sess["stage"] = "done_bio"
    kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU if c != "bio"]
    await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

async def start_jtbd(cid, sess, ctx):
    window = "\n".join(sess["answers"] + sess["product_answers"])
    prompt0 = (
        "🎯 Основные сегменты ЦА по JTBD (структурировано):\n"
        "- Название сегмента\n"
        "- Job‑to‑be‑done\n"
        "- Потребности (3)\n"
        "- Боли (3)\n"
        "- Триггеры (3)\n"
        "- Барьеры (3)\n"
        "- Альтернативы (3)\n"
        "\nКонтекст:\n" + window
    )
    text0 = ask_openai([{"role": "user", "content": prompt0}])
    chunk_send(ctx.bot, cid, text0)
    kb = [
        [InlineKeyboardButton("Хочу ещё сегменты", callback_data="jtbd_more")],
        [InlineKeyboardButton("Хватит, благодарю", callback_data="jtbd_done")]
    ]
    await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
    sess["stage"] = "jtbd_first"

async def handle_more_jtbd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions[cid]
    window = "\n".join(sess["answers"] + sess["product_answers"])
    prompt = (
        "Добавь ещё 3 дополнительные сегмента по JTBD (структурировано как ранее), контекст:\n" + window
    )
    text = ask_openai([{"role": "user", "content": prompt}])
    chunk_send(ctx.bot, cid, text)
    await ctx.bot.send_message(chat_id=cid, text=(
        "У меня есть контент‑ассистент — создаёт стратегии, посты и сценарии.\n\nЧто дальше?"
    ), reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Получить доступ", callback_data="get_access")],
        [InlineKeyboardButton("Уже в арсенале", callback_data="have")],
        [InlineKeyboardButton("Обращусь позже", callback_data="later")]
    ]))
    sess["stage"] = "done_jtbd"

async def handle_skip_jtbd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions[cid]
    await ctx.bot.send_message(chat_id=cid, text=(
        "Поняла! У меня есть контент‑ассистент — создаёт стратегии, посты и сценарии.\n\nЧто дальше?"
    ), reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Получить доступ", callback_data="get_access")],
        [InlineKeyboardButton("Уже в арсенале", callback_data="have")],
        [InlineKeyboardButton("Обращусь позже", callback_data="later")]
    ]))
    sess["stage"] = "done_jtbd"

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    if not sess:
        return
    text = update.message.text.strip()

        if sess["stage"] == "interview":
        sess["answers"].append(text)
        # дружелюбный микро‑комментарий
        comment = ask_openai([
            {"role": "system",
             "content": "Ответь одним тёплым предложением поддержки, без вопросов, на \"ты\""},
            {"role": "user", "content": text}
        ])
        await ctx.bot.send_message(cid, comment)

        idx = len(sess["answers"])
        if idx < len(INTERVIEW_Q):                              #  ←  осталось >0 вопросов
            await ctx.bot.send_message(cid, INTERVIEW_Q[idx])
            return                                               #  ←  выходим, ждём ответа

        # ----- ниже код выполнится ОДИН РАЗ после 15‑го ответа -----
        sess["stage"] = "done_interview"

        # 1. Глубокая распаковка
        full_answers = "\n".join(sess["answers"])
        unpack = ask_openai([
            {"role": "system",
             "content": ("Ты стратег‑психолог. Сделай структурную распаковку: "
                         "ценности, мотивация, сильные стороны, уникальность.")},
            {"role": "user", "content": full_answers}
        ])

        # 2. Позиционирование
        positioning = ask_openai([
            {"role": "system",
             "content": "Сформулируй чёткое позиционирование: ниша, ценность, отличие."},
            {"role": "user", "content": unpack}
        ])
        sess["positioning"] = positioning

        # отправляем по частям, чтобы не обрезалось
        chunk_send(ctx.bot, cid, "✅ Твоя распаковка:\n\n" + unpack)
        chunk_send(ctx.bot, cid, "🎯 Позиционирование:\n\n" + positioning)

        # меню
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU]
        await ctx.bot.send_message(cid, "Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess["stage"] == "product_ask":
        sess["product_answers"].append(text)
        prompt = "🔎 Вот анализ твоего продукта — 3–4 практических совета:\n" + "\n".join(sess["product_answers"])
        content = ask_openai([{"role":"user","content":prompt}])
        chunk_send(ctx.bot, cid, content)
        sess["stage"] = "done_product"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c != "product"]
        await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess["stage"] == "done_jtbd" and text.lower().replace(" ", "_") in ["get_access", "have", "later"]:
        replies = {
            "get_access": "👉 Вот ссылка на оплату контент‑ассистента: https://your-link.com",
            "have": "👏 Отлично, продолжаем!",
            "later": "🚀 Обращайся, когда будешь готов(а)."
        }
        await ctx.bot.send_message(chat_id=cid, text=replies[text.lower().replace(" ", "_")])
        return

    await ctx.bot.send_message(chat_id=cid, text="Нажми /start или выбери кнопку ✨")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CallbackQueryHandler(handle_more_jtbd, pattern="jtbd_more"))
    app.add_handler(CallbackQueryHandler(handle_skip_jtbd, pattern="jtbd_done"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
