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

INTERVIEW_Q = [f"{i+1}. Здесь твой вопрос №{i+1}." for i in range(15)]
MAIN_MENU = [("📱 BIO","bio"),("🎯 Продукт / Услуга","product"),("🔍 Анализ ЦА","jtbd")]
FINAL_MENU = [("🪄 Получить доступ","get_access"),("✅ Уже в арсенале","have"),("⏳ Обращусь позже","later")]

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    sessions[cid] = {"stage":"welcome","answers":[],"product_answers":[], "positioning":""}
    kb = [[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА",callback_data="agree")]]
    await ctx.bot.send_message(cid, WELCOME, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id; query = update.callback_query; data = query.data
    sess = sessions.get(cid); await query.answer()
    if not sess: return

    if sess["stage"]=="welcome" and data=="agree":
        sess["stage"]="interview"; sess["answers"]=[]
        await ctx.bot.send_message(cid, "✅ Спасибо за согласие!\n\nТеперь начнём распаковку личности.\nЯ задам тебе 15 вопросов — отвечай просто и честно 👇")
        await ctx.bot.send_message(cid, INTERVIEW_Q[0])
        return

    if sess["stage"]=="done_interview" and data=="bio":
        sess["stage"]="bio"; await generate_bio(cid,sess,ctx); return

    if sess["stage"] in ("done_interview","done_bio") and data=="product":
        sess["stage"]="product_ask"; sess["product_answers"]=[]
        await ctx.bot.send_message(cid, "Расскажи о своём продукте/услуге — ярко и живо, как если бы презентовала его потенциальному клиенту.")
        return

    if sess["stage"] in ("done_interview","done_bio","done_product") and data=="jtbd":
        await start_jtbd(cid,sess,ctx); return

    if data=="jtbd_more" and sess["stage"]=="jtbd_first":
        await handle_more_jtbd(update,ctx); return
    if data=="jtbd_done" and sess["stage"]=="jtbd_first":
        await handle_skip_jtbd(update,ctx); return

async def generate_bio(cid,sess,ctx):
    prompt = ("На основе позиционирования сформулируй 5 вариантов короткого BIO для Instagram (до 180 символов)."
              "\nПозиционирование:\n" + sess["positioning"])
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                        messages=[{"role":"user","content":prompt}])
    await ctx.bot.send_message(cid, resp.choices[0].message.content)
    sess["stage"]="done_bio"
    kb = [[InlineKeyboardButton(n,callback_data=c)] for n,c in MAIN_MENU if c!="bio"]
    await ctx.bot.send_message(cid,"Что дальше?",reply_markup=InlineKeyboardMarkup(kb))

async def start_jtbd(cid,sess,ctx):
    prompt = ("Основываясь на распаковке, позиционировании и описании продукта, "
              "сформулируй 3–4 основных сегмента ЦА по JTBD.\n"
              "В формате:\n"
              "Название сегмента:\n"
              "- Job-to-be-done\n- Потребности\n- Боли\n- Триггеры/Барьеры\n- Альтернативы\n")
    window = "\n".join(sess["answers"]+sess["product_answers"])
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                        messages=[{"role":"user","content":prompt+"\n"+window}])
    await ctx.bot.send_message(cid, "🎯 Основные сегменты ЦА:\n\n" + resp.choices[0].message.content,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Хочу дополнительные сегменты",callback_data="jtbd_more")],
            [InlineKeyboardButton("Хватит, благодарю",callback_data="jtbd_done")]
        ]))
    sess["stage"]="jtbd_first"

async def handle_more_jtbd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    resp = openai.ChatCompletion.create(model="gpt-3.5-turbo",
               messages=[{"role":"user","content":(
                   "Добавь ещё 3 неочевидных сегмента ЦА в том же формате (название, JTBD, потребности, боли, триггеры/барьеры, альтернативы)."
               )}])
    await ctx.bot.send_message(cid, resp.choices[0].message.content)
    await ctx.bot.send_message(cid,
        "У меня есть контент‑ассистент — он умеет создавать контент‑стратегии, посты и сценарии.\nЧто дальше?",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(n,callback_data=c)] for n,c in FINAL_MENU]))
    sessions[cid]["stage"]="done_jtbd"

async def handle_skip_jtbd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await ctx.bot.send_message(cid,
        "Поняла! У меня есть контент‑ассистент — он умеет создавать контент‑стратегии, посты и сценарии.\nЧто дальше?",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(n,callback_data=c)] for n,c in FINAL_MENU]))
    sessions[cid]["stage"]="done_jtbd"

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id; sess = sessions.get(cid); text = update.message.text.strip()
    if not sess:
        return await ctx.bot.send_message(cid, "Нажми /start")

    if sess["stage"]=="interview":
        sess["answers"].append(text)
        cmpt = openai.ChatCompletion.create(model="gpt-3.5-turbo",
            messages=[{"role":"system","content":"Ты — дружелюбный эксперт, поддержи ответом до 2 фраз на «ты»."},
                      {"role":"user","content":text}])
        await ctx.bot.send_message(cid, cmpt.choices[0].message.content)
        idx = len(sess["answers"])
        if idx < len(INTERVIEW_Q):
            await ctx.bot.send_message(cid, INTERVIEW_Q[idx])
        else:
            sess["stage"]="done_interview"
            full = "\n".join(sess["answers"])
            resp = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                messages=[{"role":"system","content":"Ты — стратег‑психолог. Сделай глубокую распаковку: Ценности; Мотивация; Сильные стороны; Позиционирование; Ядро сообщений."},
                          {"role":"user","content":full}])
            summary = resp.choices[0].message.content
            await ctx.bot.send_message(cid, "✅ Твоя распаковка:\n\n" + summary)
            resp2 = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                messages=[{"role":"system","content":"Выдай чёткое позиционирование: ниша; ценность; отличие; формат: абзац + буллеты."},
                          {"role":"user","content":summary}])
            sess["positioning"] = resp2.choices[0].message.content
            await ctx.bot.send_message(cid, sess["positioning"])
            kb = [[InlineKeyboardButton(n,callback_data=c)] for n,c in MAIN_MENU]
            await ctx.bot.send_message(cid, "Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess["stage"]=="product_ask":
        sess["product_answers"].append(text)
        prompt = "🔎 Вот анализ твоего продукта — 3 точки + рекомендации:\n"
        resp = openai.ChatCompletion.create(model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt + "\n".join(sess["product_answers"])}])
        await ctx.bot.send_message(cid, resp.choices[0].message.content)
        sess["stage"]="done_product"
        kb = [[InlineKeyboardButton(n,callback_data=c)] for n,c in MAIN_MENU if c!="product"]
        await ctx.bot.send_message(cid, "Что дальше?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if sess["stage"]=="done_jtbd" and text.lower().replace(" ","_") in ["get_access","have","later"]:
        msgs = {
            "get_access":"👉 Ссылка на оплату: https://your-link.com",
            "have":"👏 Отлично, продолжай!",
            "later":"🚀 Обратись, когда будешь готов(а)."
        }
        await ctx.bot.send_message(cid, msgs[text.lower().replace(" ","_")])
        return

    await ctx.bot.send_message(cid, "Нажми /start или используй кнопки меню.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,message_handler))
    app.run_polling()

if __name__=="__main__":
    main()
