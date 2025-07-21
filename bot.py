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
    query = update.callback_query; data = query.data
    sess = sessions.get(cid); await query.answer()
    if not sess: return

    if sess["stage"] == "welcome" and data == "agree":
        sess["stage"] = "interview"; sess["answers"] = []
        await ctx.bot.send_message(chat_id=cid, text="✅ Спасибо! Давай распаковываться. Поехали👇")
        await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[0]); return

    # BIO
    if sess["stage"] == "done_interview" and data == "bio":
        sess["stage"] = "bio"; await generate_bio(cid, sess, ctx); return
    # Product
    if sess["stage"] in ("done_interview", "done_bio") and data == "product":
        sess["stage"] = "product_ask"; sess["product_answers"] = []
        await ctx.bot.send_message(chat_id=cid, text="Расскажи о своём продукте/услуге — ярко и живо, как если бы презентовала его потенциальному клиенту."); return
    # JTBD
    if sess["stage"] in ("done_interview","done_bio","done_product") and data == "jtbd":
        await start_jtbd(cid, sess, ctx); return
    return

async def generate_bio(cid, sess, ctx):
    prompt = (
        "Сформируй 3 варианта BIO для Инстаграм:\n"
        f"- Каждый вариант: 3–4 цепляющих тезиса (до 180 символов).\n"
        "- Говорим дружелюбно, на «ты».\n"
        "Ответы:\n" + "\n".join(sess["answers"])
    )
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
    await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
    sess["stage"] = "done_bio"
    kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c!="bio"]
    await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

async def start_jtbd(cid, sess, ctx):
    # Сначала собираем базовые сегменты
    prompt0 = (
        "На основе распаковки и продукта выдели 3–4 основных сегмента целевой аудитории.\n"
        "Структурировано: название сегмента + краткое описание."
        "\nОтветь дружелюбно, на «ты»."
    )
    resp0 = openai.ChatCompletion.create(model="gpt-3.5-turbo",
        messages=[{"role":"user","content":prompt0 + "\n\n" + "\n".join(sess["answers"] + sess["product_answers"])}])
    text0 = resp0.choices[0].message.content
    kb = [[InlineKeyboardButton("Да, дополнительные сегменты", callback_data="more_jtbd")],
          [InlineKeyboardButton("Хватит, благодарю", callback_data="skip_jtbd")]]
    await ctx.bot.send_message(chat_id=cid, text=text0, reply_markup=InlineKeyboardMarkup(kb))
    # переходим в stage jtbd_first
    sess["stage"] = "jtbd_first"

async def handle_more_jtbd(update, ctx):
    cid = update.effective_chat.id; sess = sessions[cid]
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo",
        messages=[{"role":"user","content":"Добавь ещё 3 неочевидных сегмента, дружелюбно на «ты»."}])
    await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
    # Переходим к финальному предложению
    await ctx.bot.send_message(chat_id=cid,
        text="У меня есть контент‑ассистент — он умеет создавать контент‑стратегии, посты и сценарии.\n\nЧто дальше?",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Получить доступ", callback_data="get_access")],
                                           [InlineKeyboardButton("Уже в арсенале", callback_data="have")],
                                           [InlineKeyboardButton("Обращусь позже", callback_data="later")]]))
    sess["stage"] = "done_jtbd"

async def handle_skip_jtbd(update, ctx):
    cid = update.effective_chat.id; sess = sessions[cid]
    await ctx.bot.send_message(chat_id=cid,
        text="Поняла! У меня есть контент‑ассистент — он умеет создавать контент‑стратегии, посты и сценарии.\n\nЧто дальше?",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Получить доступ", callback_data="get_access")],
                                           [InlineKeyboardButton("Уже в арсенале", callback_data="have")],
                                           [InlineKeyboardButton("Обращусь позже", callback_data="later")]]))
    sess["stage"] = "done_jtbd"

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id; sess = sessions.get(cid)
    if not sess: return
    text = update.message.text.strip()

    if sess["stage"] == "interview":
        sess["answers"].append(text)
        cmpt = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"system","content":"Ты — эксперт, на «ты», комментируй ответ коротко по делу."},
                      {"role":"user","content":text}]
        )
        await ctx.bot.send_message(chat_id=cid, text=cmpt.choices[0].message.content)
        idx = len(sess["answers"])
        await ctx.bot.send_message(chat_id=cid, text=(INTERVIEW_Q[idx] if idx<15 else ""))
        if idx == 15:
            sess["stage"] = "done_interview"
        return

    if sess["stage"] == "product_ask":
        sess["product_answers"].append(text)
        # читаем продукт и сразу выдаём рекомендации
        prompt = (
            "Проанализируй описание продукта и дай 3‑4 практических рекомендации:\n"
            + "\n".join(sess["product_answers"]) + "\n"
            "Советы: как раскрывать ценность, что улучшить, как презентовать."
        )
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
        sess["stage"] = "done_product"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c!="product"]
        await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess["stage"] == "done_jtbd" and text.lower().replace(" ","_") in ["get_access","have","later"]:
        msgs = {
            "get_access": "👉 Вот ссылка на оплату контент‑ассистента: https://your-link.com",
            "have": "👏 Отлично, продолжаешь — супер!",
            "later": "🚀 Обратись, когда захочешь продолжить."
        }
        await ctx.bot.send_message(chat_id=cid, text=msgs[text.lower().replace(" ","_")])
        return

    await ctx.bot.send_message(chat_id=cid, text="👍 Используй кнопки или пиши /start")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CallbackQueryHandler(handle_more_jtbd, pattern="more_jtbd"))
    app.add_handler(CallbackQueryHandler(handle_skip_jtbd, pattern="skip_jtbd"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
