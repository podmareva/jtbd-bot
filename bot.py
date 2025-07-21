import os
import asyncio
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
    "[Договором‑оферты](https://docs.google.com/…).\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА», чтобы стартовать."
)

INTERVIEW_Q = [
    "1. Расскажи о себе: кто ты по профессии и чем занимаешься?",
    "2. Какие ценности и убеждения важны для тебя?",
    "3. Что отличает тебя от других специалистов?",
    "4. Какие сильные стороны ты можешь выделить?",
    "5. Какие черты твоей личности помогают в работе?",
    "6. Какие достижения гордишься особенно?",
    "7. Какие задачи тебе нравятся решать больше всего?",
    "8. Что вдохновляет тебя в профессии?",
    "9. Как бы ты описала свой идеальный проект?",
    "10. Какие методы или подходы ты используешь?",
    "11. Какая цель перед тобой стоит сейчас?",
    "12. Что мешает тебе двигаться вперёд?",
    "13. Что говорят о тебе клиенты?",
    "14. Какие отзывы запомнились?",
    "15. Что бы ты изменила в своём подходе с точки зрения эффективности?"
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
    sessions[cid] = {"stage": "welcome", "answers": [], "product_answers": [], "position": ""}
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

    stage = sess["stage"]

    if stage == "welcome" and data == "agree":
        sess["stage"] = "interview"
        await ctx.bot.send_message(chat_id=cid, text="✅ Спасибо за согласие!\nТеперь начнём распаковку личности.\nЯ задам тебе 15 вопросов — отвечай просто и честно 👇")
        await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[0])

    elif stage in ("interview",) and data in ("bio","product","jtbd"):
        await ctx.bot.send_message(chat_id=cid, text="❗ Сначала ответь на все 15 вопросов.")

    elif stage == "done_interview" and data == "bio":
        sess["stage"] = "bio"
        prompt = "На основе позиционирования (" + sess["position"] + ") напиши 5 вариантов короткого bio для Instagram по 180 символов каждый."
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        await ctx.bot.send_message(chat_id=cid, text=resp.choices[0].message.content)
        sess["stage"] = "done_bio"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c!="bio"]
        await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

    elif stage in ("done_interview","done_bio") and data == "product":
        sess["stage"] = "product_ask"
        sess["product_answers"] = []
        await ctx.bot.send_message(chat_id=cid, text="🎯 Расскажи о продукте/услуге — как если бы презентовала клиентам.")

    elif stage == "done_product" and data == "jtbd":
        sess["stage"] = "jtbd"
        await generate_jtbd(cid, ctx)

    elif stage == "done_jtbd" and data in ("get_access","have","later"):
        msgs = {
            "get_access": "👉 Вот ссылка на доступ к контент‑ассистенту:\nhttps://your-link.com",
            "have": "✅ Поддерживаю! Прекрасно, что уже используешь инструмент 😊",
            "later": "🚀 Всё получится! Обращайся, когда будешь готова."
        }
        await ctx.bot.send_message(chat_id=cid, text=msgs[data])
        return

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    if not sess:
        return
    text = update.message.text.strip()

    if sess["stage"] == "interview":
        sess["answers"].append(text)
        # комментарий после каждого ответа
        await ctx.bot.send_message(chat_id=cid, text=f"👍 Спасибо! Приняла: «{text}» — держим тему.")

        idx = len(sess["answers"])
        if idx < 15:
            await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[idx])
        else:
            # готовим позиционирование
            prompt = "На основе этих ответов сделай развёрнутую распаковку личности (1–2 абзаца). Ответ:\n" + "\n".join(sess["answers"])
            resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
            session_position = resp.choices[0].message.content
            sess["position"] = session_position
            await ctx.bot.send_message(chat_id=cid, text="✅ Распаковка готова:\n" + session_position)
            sess["stage"] = "done_interview"
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU]
            await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

    elif sess["stage"] == "product_ask":
        sess["product_answers"].append(text)
        step = len(sess["product_answers"])
        headers = [
            "Спасибо! Что дальше? Опиши основную проблему, которую решает твой продукт.",
            "Расскажи, кому он помогает — кто твой идеальный клиент?",
            "Почему он отличается от аналогов — что уникального в нём?",
            "Какие выгоды клиент получает?"]
        if step <= 4:
            await ctx.bot.send_message(chat_id=cid, text=headers[step-1])
        if step == 4:
            # финальная рекомендация
            prompt = "Проанализируй описание продукта и дай 3–4 практических совета: как раскрывать ценность клиентам."
            resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content": prompt + "\n" + "\n".join(sess["product_answers"]) }])
            await ctx.bot.send_message(chat_id=cid, text="Рекомендации по продукту:\n" + resp.choices[0].message.content)
            sess["stage"] = "done_product"
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in MAIN_MENU if c!="product"]
            await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

    # JTBD бот не прописан здесь — вызываем генератор

async def generate_jtbd(cid, ctx):
    sess = sessions[cid]
    prompt_main = "Опиши основные 3 сегмента ЦА по JTBD на основе твоего продукта:\n" + "\n".join(sess["product_answers"])
    resp_main = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content": prompt_main}])
    main_segs = resp_main.choices[0].message.content

    await ctx.bot.send_message(chat_id=cid, text="🔍 Основные сегменты ЦА:\n" + main_segs)
    await ctx.bot.send_message(chat_id=cid, text="Хочешь ещё 3 неочевидных сегмента ЦА? Да / Нет")

    sess["stage"] = "jtbd_wait_more"
    sess["jtbd_main"] = main_segs

async def jtbd_followup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    if sess and sess["stage"] == "jtbd_wait_more":
        text = update.message.text.lower()
        if text.startswith("да"):
            prompt_extra = "Теперь выдай 3 неочевидных сегмента и разверни каждый:"
            resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content": prompt_extra}])
            await ctx.bot.send_message(chat_id=cid, text="Неочевидные сегменты:\n" + resp.choices[0].message.content)
        sess["stage"] = "done_jtbd"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n,c in FINAL_MENU]
        await ctx.bot.send_message(chat_id=cid, text="Готово! Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, jtbd_followup))
    asyncio.run(app.run_polling())

if __name__ == "__main__":
    main()
