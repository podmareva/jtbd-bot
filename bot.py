import os
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
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
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и начнём!"
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
            "Теперь начнём с распаковки личности.\n"
            "Я задам тебе *15 вопросов* — отвечай честно и просто.\n\n"
            "Готов(а)? Тогда поехали 👇"
        ), parse_mode="Markdown")
        await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[0])

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    if not sess:
        return
    text = update.message.text.strip()

    # Этап интервью
    if sess["stage"] == "interview":
        sess["answers"].append(text)

        # Комментарий к каждому ответу
        cmpt = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content":"Ты профессиональный бренд-эксперт — дай короткий комментарий по ответу."},
                {"role":"user","content":text}
            ]
        )
        await ctx.bot.send_message(chat_id=cid, text=cmpt.choices[0].message.content)

        idx = len(sess["answers"])
        if idx < len(INTERVIEW_Q):
            await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[idx])
        else:
            sess["stage"] = "done_interview"
            # Итоговая распаковка
            summary = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role":"system","content":(
                        "Проанализируй ответы клиента и составь подробную распаковку личности и экспертности:\n"
                        "1. Ценности\n2. Мотивация\n3. Сильные стороны и уникальность\n"
                        "4. Позиционирование\n5. Что транслирует аудиториям"
                    )},
                    {"role":"user","content":"\n".join(sess["answers"])}
                ]
            ).choices[0].message.content
            await ctx.bot.send_message(chat_id=cid, text="✅ Распаковка завершена! Вот итог:\n\n" + summary)
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU]
            await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

    # Остальные этапы (bio, product, jtbd)
    elif sess["stage"] == "done_interview" and text.lower() == "bio":
        sess["stage"] = "bio"
        prompt = "Сформируй 3 варианта BIO, каждый — 3 тезиса по 180 символов на основе:\n" + "\n".join(sess["answers"])
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
        sess["stage"] = "done_bio"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c!="bio"]
        await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

    elif sess["stage"] == "done_bio" and text.lower() == "product":
        sess["stage"] = "product_ask"
        sess["product_answers"] = []
        await ctx.bot.send_message(chat_id=cid, text="Расскажи о продукте/услуге и кому он помогает.")

    elif sess["stage"] == "product_ask":
        sess["product_answers"].append(text)
        questions = ["Какую проблему решает?", "Для кого?", "В чём уникальность?"]
        idx = len(sess["product_answers"])
        if idx < len(questions):
            await ctx.bot.send_message(chat_id=cid, text=questions[idx])
        else:
            prompt = "\n".join(sess["product_answers"])
            resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
            await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
            sess["stage"] = "done_product"
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c!="product"]
            await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

    elif sess["stage"] == "done_product" and text.lower() == "jtbd":
        prompt = (
            "Сделай анализ ЦА по JTBD на основе:\n"
            + "\n".join(sess["answers"]) + "\n" + "\n".join(sess["product_answers"])
            + "\nВключи три неочевидных сегмента."
        )
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
        sess["stage"] = "done_jtbd"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in FINAL_MENU]
        await ctx.bot.send_message(chat_id=cid, text="Выбери, что дальше:", reply_markup=InlineKeyboardMarkup(kb))

    elif sess["stage"] == "done_jtbd" and text.lower().replace(" ", "_") in ["get_access","have","later"]:
        key = text.lower().replace(" ", "_")
        msgs = {
            "get_access": "👉 Ссылка на оплату: https://your-link.com",
            "have": "👏 Здорово! Продолжай в том же духе!",
            "later": "🚀 Когда будешь готов(а), я здесь!"
        }
        await ctx.bot.send_message(chat_id=cid, text=msgs[key])

    else:
        await ctx.bot.send_message(chat_id=cid, text="Используй меню выше или пиши /start, чтобы начать заново.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
