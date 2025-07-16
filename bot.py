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
    "👋 Привет! Ты в боте «Твоя распаковка и анализ ЦА» — он поможет:
    • распаковать твою экспертную личность;
    • сформировать позиционирование и BIO;
    • подробно разобрать продукт/услугу;
    • провести анализ ЦА по JTBD.\n\n"
    "🔐 Чтобы начать, пожалуйста, подтверди согласие с "
    "[\u041f\u043e\u043b\u0438\u0442\u0438\u043a\u043e\u0439 \u043a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u0438](https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit?usp=drive_link&ouid=104429050326439982568&rtpof=true&sd=true) и "
    "[\u0414\u043e\u0433\u043e\u0432\u043e\u0440\u043e\u043c‑\u043e\u0444\u0435\u0440\u0442\u043e\u0439](https://533baa06-ee8c-4f9f-a849-1e8a7826bc45-00-2qjxcpo7ji57w.janeway.replit.dev/).\n\n"
    "✅ Просто нажми «СОГЛАСЕН/СОГЛАСНА», чтобы стартовать."
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

async def get_feedback(text):
    prompt = (
        f"Пользователь ответил:\n\"{text}\"\n\n"
        "Проанализируй ответ: если он поверхностный, спорный или слишком общий — скажи об этом честно."
        "Если достойный — оцени по существу, сдержанно и конструктивно, как коуч или ментор. Без лести и шаблонов."
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except:
        return "Принято. Переходим дальше."

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
        await ctx.bot.send_message(chat_id=cid, text=(
            "✅ Спасибо за согласие!\n\n"
            "Теперь начнём с распаковки личности.\n"
            "Я задам тебе несколько вопросов — просто отвечай на каждый по очереди, как в интервью.\n\n"
            "Готов(а)? Тогда начнём 👇"
        ))
        await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[0])

    elif sess["stage"] in ("done_interview", "done_bio", "done_product") and data in ("bio","product","jtbd"):
        await ctx.bot.send_message(chat_id=cid, text="❗ Сначала пройди предыдущий этап.")

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    text = update.message.text.strip()

    if not sess or sess["stage"] == "welcome":
        return await ctx.bot.send_message(chat_id=cid, text="Нажми «СОГЛАСЕН/СОГЛАСНА», чтобы начать.")

    if sess["stage"] == "interview":
        sess["answers"].append(text)
        idx = len(sess["answers"])

        comment = await get_feedback(text)
        await ctx.bot.send_message(chat_id=cid, text=comment)

        if idx < len(INTERVIEW_Q):
            await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[idx])
        else:
            sess["stage"] = "done_interview"
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU]
            await ctx.bot.send_message(chat_id=cid, text="✅ Распаковка завершена!", reply_markup=InlineKeyboardMarkup(kb))

    elif sess["stage"] == "done_interview" and text.lower() == "bio":
        sess["stage"] = "bio"
        prompt = "Сформируй 3 варианта BIO: каждый — 3 тезиса до 180 символов на основе:\n" + "\n".join(sess["answers"])
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        result = resp.choices[0].message.content
        await ctx.bot.send_message(chat_id=cid, text=result)
        comment = await get_feedback(result)
        await ctx.bot.send_message(chat_id=cid, text=comment)
        sess["stage"] = "done_bio"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c != "bio"]
        await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

    elif sess["stage"] == "done_bio" and text.lower() == "product":
        sess["stage"] = "product_ask"
        sess["product_answers"] = []
        await ctx.bot.send_message(chat_id=cid, text="Расскажи, что это за продукт/услуга и кому он помогает.")

    elif sess["stage"] == "product_ask":
        sess["product_answers"].append(text)
        prompts = ["Какую проблему решает?", "Для кого?", "Почему уникально?"]
        if len(sess["product_answers"]) < len(prompts)+1:
            await ctx.bot.send_message(chat_id=cid, text=prompts[len(sess["product_answers"])-1])
        else:
            prompt = "\n".join(sess["product_answers"])
            resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
            result = resp.choices[0].message.content
            await ctx.bot.send_message(chat_id=cid, text=result)
            comment = await get_feedback(result)
            await ctx.bot.send_message(chat_id=cid, text=comment)
            sess["stage"] = "done_product"
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c!="product"]
            await ctx.bot.send_message(chat_id=cid, text="Отлично! Чего дальше?", reply_markup=InlineKeyboardMarkup(kb))

    elif sess["stage"] == "done_product" and text.lower() == "jtbd":
        prompt = (
            "Проведи анализ ЦА по JTBD на основе:\n"
            + "\n".join(sess["answers"]) + "\n" +
            "\n".join(sess["product_answers"])
            + "\nВключи три неочевидных сегмента."
        )
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
        sess["stage"] = "done_jtbd"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in FINAL_MENU]
        await ctx.bot.send_message(chat_id=cid, text="Завершено! Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

    elif sess["stage"] == "done_jtbd":
        resp_map = {
            "get_access": "Чтобы получить доступ — вот ссылка со скидкой: [оплатить]",
            "have": "Супер! Здорово, что уже внедряешь.",
            "later": "Поняла, напомню о контент‑ассистенте позже 😉"
        }
        key = text.lower().replace(" ", "_")
        await ctx.bot.send_message(chat_id=cid, text=resp_map.get(key, "Спасибо за участие!"), parse_mode="Markdown")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
