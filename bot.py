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
    "• сформировать позиционирование;\n"
    "• создать Bio для Instagram;\n"
    "• подробно разобрать продукт/услугу;\n"
    "• провести анализ ЦА по JTBD.\n\n"
    "🔐 Подтверди согласие с "
    "[Политикой конфиденциальности](https://...) и "
    "[Договором‑офертой](https://...).\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА», чтобы начать."
)

INTERVIEW_Q = [  # 15 вопросов
    "1. Расскажи коротко о себе и своём профессиональном опыте.",
    "2. Какие ценности важны для тебя лично и в работе?",
    "3. Что тебя вдохновляет?",
    "4. Какие сильные стороны ты видишь у себя?",
    "5. В чём ты особенно компетентна?",
    "6. Какую основную проблему ты помогаешь решать?",
    "7. Что отличает тебя от других специалистов?",
    "8. Кто твоя идеальная аудитория?",
    "9. Какие достижения для тебя важны?",
    "10. Как тебя видят окружающие?",
    "11. Что ты хочешь, чтобы люди чувствовали, когда видят твои работы?",
    "12. Какие отзывы от клиентов тебе особенно дороги?",
    "13. Какие цели ты перед собой ставишь в работе?",
    "14. Что тебя останавливает сейчас?",
    "15. За что ты особенно гордишься?"
]

MAIN_MENU = [
    ("📌 Bio", "bio"),
    ("🎯 Продукт/Услуга", "product"),
    ("🔍 Анализ ЦА", "jtbd")
]

FINAL_MENU = [
    ("🪄 Получить доступ", "get_access"),
    ("✅ Уже в арсенале", "have"),
    ("⏳ Обращусь позже", "later")
]


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sessions[cid] = {"stage": "welcome", "answers": [], "positioning": "", "product": [], "ca": []}
    kb = [[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await ctx.bot.send_message(chat_id=cid, text=WELCOME, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    data = update.callback_query.data
    sess = sessions.get(cid)
    await update.callback_query.answer()
    if not sess:
        return

    stage = sess["stage"]

    if stage == "welcome" and data == "agree":
        sess["stage"] = "interview"
        await ctx.bot.send_message(chat_id=cid, text="✅ Спасибо за согласие!\nТеперь начнём распаковку личности.\nЯ задам тебе 15 вопросов — отвечай просто и честно 👇")
        await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[0])
        return

    if stage in ("welcome", "interview"):
        await ctx.bot.send_message(chat_id=cid, text="Сначала пройди распаковку, отвечая на вопросы.")
        return

    if stage == "done_interview" and data == "bio":
        prompt = "На основе этой распаковки напиши 5 вариантов короткого bio для Instagram (до 180 символов):\n" + "\n".join(sess["answers"])
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}])
        await ctx.bot.send_message(chat_id=cid, text="💡 Вот варианты Bio для Instagram:\n" + resp.choices[0].message.content)
        sess["stage"] = "done_bio"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU if c != "bio"]
        await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if stage in ("done_interview", "done_bio") and data == "product":
        sess["stage"] = "product"
        await ctx.bot.send_message(chat_id=cid, text="🎯 Отлично! Расскажи о своём продукте/услуге презентационно, как клиенту.")
        return

    if stage == "done_product" and data == "jtbd":
        sess["stage"] = "jtbd"
        await ctx.bot.send_message(chat_id=cid, text="🔍 Провожу анализ ЦА, жди результат...")
        # анализ JTBD по ответу сессии
        prompt = "Проанализируй целевую аудиторию по JTBD на основе:\n" + "\n".join(sess["product"])
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        await ctx.bot.send_message(chat_id=cid, text="📊 Основные сегменты ЦА:\n" + resp.choices[0].message.content)
        sess["stage"] = "done_jtbd"
        kb = [
            [InlineKeyboardButton("👍 Да, ещё неочевидные", callback_data="add_ca")],
            [InlineKeyboardButton("✅ Хватит, спасибо", callback_data="skip_ca")]
        ]
        await ctx.bot.send_message(chat_id=cid, text="Хочешь ещё 3 неочевидных сегмента?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if stage == "done_jtbd" and data == "add_ca":
        prompt = "Добавь 3 неочевидных сегмента ЦА по JTBD для этого продукта на основе предыдущей информации."
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        await ctx.bot.send_message(chat_id=cid, text="🌟 Неочевидные сегменты ЦА:\n" + resp.choices[0].message.content)
        sess["stage"] = "final"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in FINAL_MENU]
        await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if stage in ("done_jtbd", "final") and data in ("get_access", "have", "later"):
        texts = {
            "get_access": "🪄 Вот ссылка на оплату контент‑ассистента: https://your-link.com",
            "have": "✅ Замечательно! Ты не откладываешь развитие соцсетей — так держать!",
            "later": "⏳ Обращайся, когда будешь готов(а), я вернусь свежими идеями!"
        }
        await ctx.bot.send_message(chat_id=cid, text=texts[data])
        await ctx.bot.send_message(chat_id=cid, text="✅ Используй меню или пиши /start для начала заново.")
        return


async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    if not sess:
        return

    text = update.message.text.strip()

    if sess["stage"] == "interview":
        sess["answers"].append(text)
        idx = len(sess["answers"])
        if idx < len(INTERVIEW_Q):
            await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[idx])
        else:
            # итоговая распаковка + позиционирование
            prompt = "На основе этих ответов сведи их в структурированную распаковку личности и сформулируй позиционирование:"
            resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt + "\n" + "\n".join(sess["answers"])}])
            await ctx.bot.send_message(chat_id=cid, text="✅ Распаковка и позиционирование:\n" + resp.choices[0].message.content)
            sess["stage"] = "done_interview"
            kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU]
            await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

    elif sess["stage"] == "product":
        sess["product"].append(text)
        prompt = (
            "Проанализируй это описание продукта и дай 3–4 практических совета:\n" +
            "\n".join(sess["product"]) +
            "\n\nКак сделать презентацию более живой, ценной для клиента?"
        )
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}])
        await ctx.bot.send_message(chat_id=cid, text="🎯 Анализ продукта:\n" + resp.choices[0].message.content)
        sess["stage"] = "done_product"
        kb = [[InlineKeyboardButton(n, callback_data=c)] for n, c in MAIN_MENU if c != "product"]
        await ctx.bot.send_message(chat_id=cid, text="Что дальше?", reply_markup=InlineKeyboardMarkup(kb))

    else:
        await ctx.bot.send_message(chat_id=cid, text="Нажми кнопку из меню, чтобы продолжить.")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()


if __name__ == "__main__":
    main()
