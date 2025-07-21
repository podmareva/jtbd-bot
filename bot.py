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
    "1. Чем ты занимаешься и почему ты выбрал(а) это направление?",
    "2. Какие ценности лежат в основе твоей деятельности?",
    "3. Что для тебя самое важное в работе с клиентами?",
    "4. Какие у тебя сильные стороны как эксперта?",
    "5. Что тебя вдохновляет и даёт силы продолжать?",
    "6. Какие принципы ты не меняешь ни при каких обстоятельствах?",
    "7. Каким ты хочешь быть в глазах своей аудитории?",
    "8. Каким опытом ты хочешь делиться чаще всего?",
    "9. Какие изменения хочешь привнести в жизни клиентов?",
    "10. Чем ты отличаешься от других специалистов?",
    "11. Есть ли у тебя миссия, которую ты транслируешь?",
    "12. Какие темы считаешь важными для блога?",
    "13. С какими клиентами тебе наиболее интересно работать?",
    "14. Есть ли истории клиентов, которые вдохновили тебя?",
    "15. Какими достижениями ты особенно гордишься?"
]

MAIN_MENU = [("📱 BIO", "bio"), ("🎯 Продукт / Услуга", "product"), ("🔍 Анализ ЦА", "jtbd")]
FINAL_MENU = [("🪄 Получить доступ", "get_access"), ("✅ Уже в арсенале", "have"), ("⏳ Обращусь позже", "later")]

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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

    if sess["stage"] == "welcome" and data == "agree":
        sess["stage"] = "interview"
        sess["answers"] = []
        await ctx.bot.send_message(chat_id=cid, text=(
            "✅ Спасибо за согласие!\n\n"
            "Начнём распаковку личности. Отвечай просто и честно на 15 вопросов 👇"
        ))
        await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[0])
        return

    # Блок для кнопок после распаковки
    if sess["stage"] == "done_interview" and data == "bio":
        sess["stage"] = "bio"
        await generate_bio(cid, sess, ctx)
        return
    if sess["stage"] in ("done_interview", "done_bio") and data == "product":
        sess["stage"] = "product_ask"
        sess["product_answers"] = []
        await ctx.bot.send_message(chat_id=cid, text="Расскажи о своём продукте/услуге и кому он помогает.")
        return
    if sess["stage"] in ("done_interview", "done_bio", "done_product") and data == "jtbd":
        await run_jtbd(cid, sess, ctx)
        return

async def generate_bio(cid, sess, ctx):
    prompt = (
        "Сформируй 3 варианта BIO (каждый — 3 тезиса до 180 символов, дружелюбно на «ты»):\n"
        + "\n".join(sess["answers"])
    )
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
    await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
    sess["stage"] = "done_bio"
    kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c!="bio"]
    await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

async def run_jtbd(cid, sess, ctx):
    prompt = (
        "Сделай глубокий анализ ЦА по JTBD на основе распаковки и описания продукта. "
        "Выдели 3 неочевидных сегмента, потребности, боли, триггеры, барьеры, альтернативы. Обращайся на «ты»."
    )
    window = "\n".join(sess["answers"] + sess["product_answers"])
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content": prompt + "\n\n" + window}])
    await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
    sess["stage"] = "done_jtbd"
    kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in FINAL_MENU]
    await ctx.bot.send_message(chat_id=cid, text="Выбери, что дальше:", reply_markup=InlineKeyboardMarkup(kb))

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    if not sess:
        return
    text = update.message.text.strip()

    if sess["stage"] == "interview":
        sess["answers"].append(text)

        cmpt = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content":"Ты — эксперт. Пиши дружелюбно на «ты», дай короткий комментарий по делу."},
                {"role":"user","content":text}
            ]
        )
        await ctx.bot.send_message(chat_id=cid, text=cmpt.choices[0].message.content)

        idx = len(sess["answers"])
        if idx < len(INTERVIEW_Q):
            await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[idx])
        else:
            sess["stage"] = "done_interview"
            summary_prompt = (
                "Ты — стратег‑психолог. Проанализируй ответы (не повторяй дословно) и выдай глубокую распаковку личности:\n"
                "I. Ключевые ценности (5–7 пунктов)\n"
                "II. Внутренняя мотивация (2–3 абзаца)\n"
                "III. Сильные стороны + уникальность\n"
                "IV. Позиционирование для аудитории\n"
                "V. Ядро сообщений (5–7 буллетов)\n\n"
                "Пиши дружелюбно, на «ты»."
            )
            full = "\n".join(sess["answers"])
            resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[
                {"role":"system","content":summary_prompt},
                {"role":"user","content":full}
            ])
            await ctx.bot.send_message(chat_id=cid, text="✅ Твоя распаковка:\n\n" + resp.choices[0].message.content)
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU]
            await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess["stage"] == "product_ask":
        sess["product_answers"].append(text)
        questions = ["Какую проблему решает?", "Для кого?", "В чём уникальность?"]
        idx = len(sess["product_answers"]) - 1
        if idx < len(questions):
            await ctx.bot.send_message(chat_id=cid, text=questions[idx])
        else:
            prompt = "\n".join(sess["product_answers"])
            resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
            await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
            sess["stage"] = "done_product"
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c!="product"]
            await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess["stage"] == "done_jtbd" and text.lower().replace(" ", "_") in ["get_access","have","later"]:
        msgs = {
            "get_access": "👉 Ссылка на оплату: https://your-link.com",
            "have": "👏 Отлично, продолжай!",
            "later": "🚀 Я тут, когда будешь готов(а)."
        }
        await ctx.bot.send_message(chat_id=cid, text=msgs[text.lower().replace(" ", "_")])
        return

    await ctx.bot.send_message(chat_id=cid, text="Нажимай кнопки меню или пиши /start для старта.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
