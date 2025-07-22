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
    "• провести анализ ЦА по JTBD.\n\n"
    "🔐 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности](https://docs.google.com/…) и "
    "[Договором‑офертой](https://docs.google.com/…).\n\n"
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

async def start(update, ctx):
    cid = update.effective_chat.id
    sessions[cid] = {"stage": "welcome", "answers": [], "product_answers": []}
    kb = [[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await ctx.bot.send_message(chat_id=cid, text=WELCOME, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update, ctx):
    cid = update.effective_chat.id
    query = update.callback_query
    data = query.data
    sess = sessions.get(cid)
    await query.answer()
    if not sess:
        return

    if sess["stage"] == "welcome" and data == "agree":
        sess["stage"] = "interview"
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
        await ctx.bot.send_message(chat_id=cid, text="Расскажи о своём продукте/услуге — ярко и живо, как если бы презентовала его потенциальному клиенту.")
        return

    if sess["stage"] in ("done_interview", "done_bio", "done_product") and data == "jtbd":
        await start_jtbd(cid, sess, ctx)
        return

    if data == "jtbd_more" and sess["stage"] == "jtbd_first":
        await handle_more_jtbd(update, ctx)
        return

    if data == "jtbd_done" and sess["stage"] == "jtbd_first":
        await handle_skip_jtbd(update, ctx)
        return

async def message_handler(update, ctx):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    text = update.message.text.strip()
    if not sess:
        return

    if sess["stage"] == "interview":
        sess["answers"].append(text)
        # Комментарий к ответу
        comment = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Ты — поддерживающий коуч. На «ты». Дай короткий комментарий к ответу — по теме, дружелюбно, без вопросов."},
                {"role": "user", "content": text}
            ]
        )
        await ctx.bot.send_message(chat_id=cid, text=comment.choices[0].message.content)
        idx = len(sess["answers"])
        if idx < len(INTERVIEW_Q):
            await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[idx])
        else:
            sess["stage"] = "done_interview"
            # Распаковка
            answers = "\n".join(sess["answers"])
            unpack = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "На основе ответов сделай глубокую распаковку личности: ценности, убеждения, сильные стороны, сообщения для аудитории."},
                    {"role": "user", "content": answers}
                ]
            )
            await ctx.bot.send_message(chat_id=cid, text="✅ Твоя распаковка:\n\n" + unpack.choices[0].message.content)

            # Позиционирование
            pos = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "На основе распаковки сделай чёткое позиционирование и его детализацию."},
                    {"role": "user", "content": unpack.choices[0].message.content}
                ]
            )
            sess["positioning"] = pos.choices[0].message.content
            await ctx.bot.send_message(chat_id=cid, text=sess["positioning"])
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU]
            await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess["stage"] == "product_ask":
        sess["product_answers"].append(text)
        if len(sess["product_answers"]) < 3:
            prompts = [
                "А теперь расскажи, какую проблему решает этот продукт?",
                "И для кого он предназначен?"
            ]
            await ctx.bot.send_message(chat_id=cid, text=prompts[len(sess["product_answers"]) - 1])
        else:
            joined = "\n".join(sess["product_answers"])
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "user", "content": "Проанализируй этот продукт/услугу и сформулируй его ценность, сильные стороны и рекомендации по продвижению:\n" + joined}
                ]
            )
            await ctx.bot.send_message(chat_id=cid, text="🔎 Анализ продукта:\n\n" + resp.choices[0].message.content)
            sess["stage"] = "done_product"
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU if c != "product"]
            await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

# ---------- BIO ----------
async def generate_bio(cid, sess, ctx):
    prompt = (
        "На основе позиционирования сформулируй 5 вариантов BIO для Instagram. "
        "Каждый вариант — 3–4 цепляющих тезиса, суммарно до 180 символов:\n\n"
        + sess["positioning"]
    )
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    await ctx.bot.send_message(chat_id=cid, text="📱 Варианты BIO:\n\n" + resp.choices[0].message.content)
    sess["stage"] = "done_bio"
    kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU if c != "bio"]
    await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

# ---------- JTBD ----------
async def start_jtbd(cid, sess, ctx):
    ctx_text = "\n".join(sess["answers"] + sess["product_answers"])
    prompt = (
        "Сформулируй 3–4 основных сегмента ЦА по методу JTBD. "
        "Для каждого сегмента укажи:\n"
        "- Job‑to‑be‑done\n- Неочевидные потребности\n- Неочевидные боли\n"
        "- Триггеры\n- Барьеры\n- Альтернативы\n\n"
        "Исходная информация:\n" + ctx_text
    )
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                        messages=[{"role": "user", "content": prompt}])
    await ctx.bot.send_message(chat_id=cid,
                               text="🎯 Основные сегменты ЦА:\n\n" + resp.choices[0].message.content,
                               reply_markup=InlineKeyboardMarkup([
                                   [InlineKeyboardButton("Хочу дополнительные сегменты", callback_data="jtbd_more")],
                                   [InlineKeyboardButton("Хватит, благодарю", callback_data="jtbd_done")]
                               ]))
    sess["stage"] = "jtbd_first"

async def handle_more_jtbd(update, ctx):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    ctx_text = "\n".join(sess["answers"] + sess["product_answers"])
    prompt = (
        "Добавь ещё 3 неочевидных сегмента ЦА по JTBD в том же формате "
        "(Job, потребности, боли, триггеры, барьеры, альтернативы):\n\n" + ctx_text
    )
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                        messages=[{"role": "user", "content": prompt}])
    await ctx.bot.send_message(chat_id=cid,
                               text="🔍 Дополнительные сегменты:\n\n" + resp.choices[0].message.content)
    await ctx.bot.send_message(chat_id=cid,
                               text="У меня есть контент‑ассистент — он создаёт стратегии, посты и сценарии.\nЧто дальше?",
                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(n, callback_data=c)] for n, c in FINAL_MENU]))
    sess["stage"] = "done_jtbd"

async def handle_skip_jtbd(update, ctx):
    cid = update.effective_chat.id
    await ctx.bot.send_message(chat_id=cid,
                               text="Поняла! У меня есть контент‑ассистент — он создаёт стратегии, посты и сценарии.\nЧто дальше?",
                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(n, callback_data=c)] for n, c in FINAL_MENU]))
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
    main()
