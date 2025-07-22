# bot.py — обновлённый

import os
import sys
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

if "RUNNING_BOT" in os.environ:
    print("❌ Бот уже запущен. Останови другой процесс, чтобы избежать конфликта.")
    sys.exit(1)
os.environ["RUNNING_BOT"] = "1"

sessions = {}

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

WELCOME = (
    "\U0001F44B Привет! Ты в боте «Твоя распаковка и анализ ЦА» — он поможет:\n"
    "• распаковать твою экспертную личность;\n"
    "• сформировать позиционирование и BIO;\n"
    "• подробно разобрать продукт/услугу;\n"
    "• провести анализ ЦА по JTBD.\n\n"
    "\U0001F510 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности](https://docs.google.com/…) и "
    "[Договором‑офертой](https://docs.google.com/…).\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!"
)

async def message_handler(update, ctx):
    cid = update.effective_chat.id
    sess = sessions.get(cid)
    text = update.message.text.strip()
    if not sess:
        return

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
            await ctx.bot.send_message(chat_id=cid, text="⚠️ Не удалось получить комментарий. Продолжим 👇")
            print("Ошибка комментария:", e)

        idx = len(sess["answers"])
        if idx < len(INTERVIEW_Q):
            await ctx.bot.send_message(chat_id=cid, text=INTERVIEW_Q[idx])
        else:
            sess["stage"] = "done_interview"
            answers = "
".join(sess["answers"])
            unpack = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "На основе ответов сделай глубокую распаковку личности: ценности, убеждения, сильные стороны, сообщения для аудитории."},
                    {"role": "user", "content": answers}
                ]
            )
            unpacking_text = unpack.choices[0].message.content
            sess["unpacking"] = unpacking_text
            await ctx.bot.send_message(chat_id=cid, text="✅ Твоя распаковка:

" + unpacking_text)

            pos = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "На основе распаковки личности сформулируй чёткое позиционирование в следующем формате:

"
                            "1. Кто ты (1–2 предложения от первого лица)
"
                            "**Детализация:**
"
                            "2. Направления развития
"
                            "3. Ценности
"
                            "4. Сильные стороны
"
                            "5. Сообщение для аудитории
"
                            "6. Цели и стремления
"
                            "7. Лозунг
"
                            "8. Цель сообщества (если релевантно)
"
                            "9. Миссия
"
                            "10. Значение идеи
"
                            "11. Призыв к действию

"
                            "Оформляй с подзаголовками и маркированными списками, как в примере. Стиль — вдохновляющий, но конкретный. Без повторов. Формат Markdown."
                        )
                    },
                    {"role": "user", "content": unpacking_text}
                ]
            )
            positioning_text = pos.choices[0].message.content
            sess["positioning"] = positioning_text
            await ctx.bot.send_message(chat_id=cid, text=positioning_text)

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
        "Сформулируй 3–4 основных сегмента ЦА по методу JTBD на основании распаковки, позиционирования и продукта. "
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
        "Добавь ещё 3 неочевидных сегмента ЦА по JTBD в том же формате также на основании распаковки, позиционирования и продукта. "
        "(Job, потребности, боли, триггеры, барьеры, альтернативы):\n\n" + ctx_text
    )
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                        messages=[{"role": "user", "content": prompt}])
    await ctx.bot.send_message(chat_id=cid,
                               text="🔍 Дополнительные сегменты:\n\n" + resp.choices[0].message.content)
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
    main()
