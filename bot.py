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
    "🔐 Чтобы начать, пожалуйста, подтверди согласие с "
    "[Политикой конфиденциальности](https://docs.google.com/…) и "
    "[Договором‑офертой](https://docs.google.com/…).\n\n"
    "✅ Просто нажми «СОГЛАСЕН/СОГЛАСНА», чтобы стартовать."
)

INTERVIEW_Q = [
    "1. Расскажи о своём профессиональном опыте – чем гордишься?",
    "2. Какие ценности и принципы важны для тебя?",
    "3. Что тебя вдохновляет в работе?",
    "4. Какие личные качества помогают тебе добиваться успеха?",
    "5. Какие знания или навыки ты используешь чаще всего?",
    "6. Как ты взаимодействуешь с клиентом?",
    "7. Что клиенты ценят в тебе больше всего?",
    "8. Какие цели ты ставишь перед собой в этом году?",
    "9. Какие вызовы или трудности ты преодолеваешь?",
    "10. Какой результат любишь достигать?",
    "11. Что для тебя значимо в профессии?",
    "12. Как ты улучшаешь свои навыки?",
    "13. Какая твоя уникальность по сравнению с другими?",
    "14. Что тебя мотивирует развиваться дальше?",
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
        await ctx.bot.send_message(chat_id=cid, text="✅ Спасибо за согласие!\nТеперь начнём распаковку личности.\nЯ задам тебе 15 вопросов — отвечай просто и честно 👇")
        await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[0])
        return

    if sess["stage"] == "done_interview" and data == "bio":
        sess["stage"] = "bio"
        prompt = "На основе позиционирования сформулируй 5 вариантов короткого BIO для Instagram (до 180 символов каждый):\n" + "\n".join(sess["answers"])
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
        sess["stage"] = "done_bio"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c!="bio"]
        await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess["stage"] in ("done_interview", "done_bio") and data == "product":
        sess["stage"] = "product_ask"
        sess["product_answers"] = []
        await ctx.bot.send_message(chat_id=cid, text="🎯 Расскажи о своём продукте/услуге — как презентацию клиентам живо и ясно.")
        return

    if sess["stage"] == "done_product" and data == "jtbd":
        sess["stage"] = "jtbd"
        await ctx.bot.send_message(chat_id=cid, text="🔍 Отлично! Начинаем анализ ЦА по JTBD…")
        # формируем сегменты
        prompt1 = "На основе следующей информации сформулируй 3–4 основных сегмента ЦА по JTBD:\n" + "\n".join(sess["product_answers"])
        resp1 = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt1}])
        await ctx.bot.send_message(chat_id=cid, text="Основные сегменты ЦА:\n" + resp1.choices[0].message.content)
        kb = [[InlineKeyboardButton("Да, хочу дополнительные", callback_data="jtbd_more")],
              [InlineKeyboardButton("Нет, спасибо", callback_data="jtbd_no")]]
        await ctx.bot.send_message(chat_id=cid, text="Хочешь получить ещё 3 неочевидных сегмента?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess["stage"] == "jtbd" and data == "jtbd_more":
        prompt2 = "Добавь ещё 3 неочевидных сегмента ЦА по JTBD и распиши, как выше."
        resp2 = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt2}])
        await ctx.bot.send_message(chat_id=cid, text="Дополнительные сегменты:\n" + resp2.choices[0].message.content)
        sess["stage"] = "done_jtbd"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in FINAL_MENU]
        await ctx.bot.send_message(chat_id=cid, text="На этом всё. Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess["stage"] == "jtbd" and data == "jtbd_no":
        sess["stage"] = "done_jtbd"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in FINAL_MENU]
        await ctx.bot.send_message(chat_id=cid, text="Понял, спасибо! Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess.get("stage","") == "done_jtbd" and data in ("get_access","have","later"):
        msgs = {
            "get_access": "👉 Вот ссылка на оплату контент‑ассистента: https://your-link.com",
            "have": "✅ Отлично, ты уже в деле! Продолжай в том же духе.",
            "later": "🚀 Обращайся, когда будешь готов — я всегда рядом!"
        }
        await ctx.bot.send_message(chat_id=cid, text=msgs[data])
        return

    # любой вызов других кнопок без стадии — напоминаем
    if data in ("bio","product","jtbd"):
        await ctx.bot.send_message(chat_id=cid, text="❗ Сначала пройди полную распаковку.")
        return

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    if not sess:
        return
    text = update.message.text.strip()

    if sess["stage"] == "interview":
        sess["answers"].append(text)
        # комментируем ответ
        comment = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":"Кратко прокомментируй по теме и тепло этот ответ:\n" + text}]
        ).choices[0].message.content
        await ctx.bot.send_message(chat_id=cid, text=comment)

        idx = len(sess["answers"])
        if idx < len(INTERVIEW_Q):
            await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[idx])
        else:
            # финальная распаковка
            prompt = "На основе этих ответов сформулируй позиционирование и глубокую распаковку личности:\n" + "\n".join(sess["answers"])
            resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
            await ctx.bot.send_message(chat_id=cid, text="✅ Твоя распаковка:\n" + resp.choices[0].message.content)
            sess["stage"] = "done_interview"
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU]
            await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

    elif sess["stage"] == "product_ask":
        sess["product_answers"].append(text)
        prompts = [
            "Что это за продукт/услуга?",
            "Для кого он?",
            "Какие ключевые проблемы решает?",
            "Что делает его уникальным?"
        ]
        if len(sess["product_answers"]) < len(prompts):
            await ctx.bot.send_message(chat_id=cid, text=prompts[len(sess["product_answers"])])
        else:
            intro = "Вот конкретные рекомендации:"
            prompt = intro + "\nПроанализируй и дай рекомендации по раскрытию ценности продукта:\n" + "\n".join(sess["product_answers"])
            resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
            await ctx.bot.send_message(chat_id=cid, text=intro + "\n" + resp.choices[0].message.content)
            sess["stage"] = "done_product"
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c!="product"]
            await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
