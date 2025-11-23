from dotenv import load_dotenv
import os
import pytz
import re
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
app = Application.builder().token(TOKEN).build()

scheduler = AsyncIOScheduler()
scheduler.configure(timezone=pytz.timezone("Europe/Rome"))
scheduler.start()

user_data = {}   # {user_id: {"name": "...", "reminders": [...]}}
user_state = {}  # {user_id: {"step": "...", "temp": {...}}}

async def manda_messaggio(chat_id: int, testo: str):
    await app.bot.send_message(chat_id=chat_id, text=testo)

async def manda_foto(chat_id: int, photo_id: str, caption: str):
    await app.bot.send_photo(chat_id=chat_id, photo=photo_id, caption=caption)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_data and user_data[user_id].get("name"):
        await mostra_menu(update, context)
        return
    await update.message.reply_text("Ciao! Come vuoi che ti chiami?\nScrivi il tuo nome (es. Rico Plus)")
    user_state[user_id] = {"step": "nome"}

async def salva_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_state.get(user_id, {}).get("step") != "nome":
        return
    nome = update.message.text.strip().split()[0].capitalize()
    user_data[user_id] = {"name": nome, "reminders": []}
    del user_state[user_id]
    await update.message.reply_text(
        f"Perfetto {nome}! Nome salvato 💾\nOra puoi usare il bot!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Apri menu", callback_data="menu")]])
    )

async def mostra_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nome = user_data.get(user_id, {}).get("name", "amico")
    keyboard = [
        [InlineKeyboardButton("Aggiungi reminder (testo)", callback_data="add_text")],
        [InlineKeyboardButton("Aggiungi reminder (con foto)", callback_data="add_photo")],
        [InlineKeyboardButton("Cancella reminder", callback_data="cancella")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    testo = f"Ciao {nome}! Cosa vuoi fare?"
    if update.message:
        await update.message.reply_text(testo, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(testo, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "menu":
        await mostra_menu(update, context)
        return

    if data in ["add_text", "add_photo"]:
        tipo = "text" if data == "add_text" else "photo"
        user_state[user_id] = {"step": "giorni", "tipo": tipo, "temp": {"giorni": []}}

        giorni = [
            ("Lunedì", "mon"), ("Martedì", "tue"), ("Mercoledì", "wed"),
            ("Giovedì", "thu"), ("Venerdì", "fri"), ("Sabato", "sat"), ("Domenica", "sun")
        ]
        keyboard = []
        for nome, cod in giorni:
            keyboard.append([InlineKeyboardButton(f"⬜ {nome}", callback_data=f"giorno_{cod}")])
        keyboard.append([InlineKeyboardButton("⬜ Ogni giorno", callback_data="giorno_*")])
        keyboard.append([InlineKeyboardButton("Invia", callback_data="giorni_ok")])

        await query.edit_message_text("Scegli i giorni (puoi selezionarne più di uno):", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("giorno_"):
        cod = data[7:]
        stato = user_state[user_id]
        giorni_selezionati = stato["temp"]["giorni"]

        if cod == "*":
            giorni_selezionati = ["*"] if "*" not in giorni_selezionati else []
        elif cod in giorni_selezionati:
            giorni_selezionati.remove(cod)
        else:
            if "*" in giorni_selezionati:
                giorni_selezionati.remove("*")
            giorni_selezionati.append(cod)

        stato["temp"]["giorni"] = giorni_selezionati

        tutti_giorni = ["mon","tue","wed","thu","fri","sat","sun"]
        keyboard = []
        for cod in tutti_giorni:
            nome = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"][tutti_giorni.index(cod)]
            spunta = "✅" if cod in giorni_selezionati else "⬜"
            keyboard.append([InlineKeyboardButton(f"{spunta} {nome}", callback_data=f"giorno_{cod}")])
        spunta_ogni = "✅" if "*" in giorni_selezionati else "⬜"
        keyboard.append([InlineKeyboardButton(f"{spunta_ogni} Ogni giorno", callback_data="giorno_*")])
        keyboard.append([InlineKeyboardButton("Invia", callback_data="giorni_ok")])

        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "giorni_ok":
        giorni = user_state[user_id]["temp"]["giorni"]
        if not giorni:
            await query.edit_message_text("Devi selezionare almeno un giorno!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Riprova", callback_data="add_" + user_state[user_id]["tipo"])]]))
            return
        user_state[user_id]["temp"]["giorni_cron"] = giorni
        user_state[user_id]["step"] = "ora"
        await query.edit_message_text("Scrivi l'orario (es. 22:30, 22.30, 7.5, 9)")

    elif data == "cancella":
        reminders = user_data.get(user_id, {}).get("reminders", [])
        if not reminders:
            await query.edit_message_text("Nessun reminder da cancellare", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Menu", callback_data="menu")]]))
            return
        kb = [[InlineKeyboardButton(f"{i+1}. {r['text']} → {r['time']}", callback_data=f"del_{i}")] for i, r in enumerate(reminders)]
        kb.append([InlineKeyboardButton("Menu", callback_data="menu")])
        await query.edit_message_text("Scegli cosa cancellare:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("del_"):
        idx = int(data.split("_")[1])
        job_id = user_data[user_id]["reminders"][idx]["id"]
        try:
            scheduler.remove_job(job_id)
        except:
            pass
        del user_data[user_id]["reminders"][idx]
        await query.edit_message_text("Cancellato!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Menu", callback_data="menu")]]))

async def gestisci_testo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    testo = update.message.text.strip()

    if user_state.get(user_id, {}).get("step") == "nome":
        await salva_nome(update, context)
        return

    stato = user_state.get(user_id)
    if not stato or stato["step"] not in ["ora", "messaggio"]:
        await mostra_menu(update, context)
        return

    if stato["step"] == "ora":
        match = re.search(r"(\d{1,2})[:\.]?(\d{0,2})", testo.lower())
        if not match:
            await update.message.reply_text("⚠️ Orario non valido!\nEsempi: 22:30, 22.30, 7.5, 9")
            return
        ore = int(match.group(1))
        minuti = int(match.group(2)) if match.group(2) else 0
        if ore > 23 or minuti > 59:
            await update.message.reply_text("⚠️ Orario non valido (max 23:59)")
            return

        stato["temp"]["ora"] = ore
        stato["temp"]["minuti"] = minuti
        stato["step"] = "messaggio"
        await update.message.reply_text("✏️ Cosa vuoi che ti ricordi?")

    elif stato["step"] == "messaggio":
        messaggio = testo.strip() or "Promemoria"
        giorni = stato["temp"]["giorni_cron"]
        ore = stato["temp"]["ora"]
        minuti = stato["temp"]["minuti"]
        tipo = stato["tipo"]

        chat_id = update.effective_chat.id

        for giorno in giorni:
            job_id = f"{user_id}_{giorno}_{ore}_{minuti}_{tipo}"
            if tipo == "text":
                scheduler.add_job(
                    manda_messaggio,
                    CronTrigger(day_of_week=giorno, hour=ore, minute=minuti),
                    args=[chat_id, f"⏰ {messaggio}"],
                    id=job_id,
                    replace_existing=True
                )
            else:
                context.user_data[user_id] = {
                    "chat_id": chat_id,
                    "caption": messaggio,
                    "giorni": giorni,
                    "ore": ore,
                    "minuti": minuti
                }
                await update.message.reply_text("📸 Mandami la foto per questo reminder")
                del user_state[user_id]
                return

        user_data.setdefault(user_id, {"reminders": []})["reminders"].append({
            "id": job_id,
            "text": messaggio,
            "time": f"{ore:02d}:{minuti:02d}",
            "type": tipo
        })

        await update.message.reply_text(
            f"✅ Reminder salvato!\n\"{messaggio}\"\nAlle {ore:02d}:{minuti:02d}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu")]])
        )
        del user_state[user_id]

async def gestisci_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in context.user_data:
        return

    dati = context.user_data[user_id]
    photo_id = update.message.photo[-1].file_id
    caption = update.message.caption.strip() if update.message.caption else dati["caption"]

    for giorno in dati["giorni"]:
        job_id = f"{user_id}_{giorno}_{dati['ore']}_{dati['minuti']}_photo"
        scheduler.add_job(
            manda_foto,
            CronTrigger(day_of_week=giorno, hour=dati["ore"], minute=dati["minuti"]),
            args=[dati["chat_id"], photo_id, f"⏰ {caption}"],
            id=job_id,
            replace_existing=True
        )

   user_data.setdefault(user_id, {"reminders": []})["reminders"].append({
        "id": job_id,
        "text": caption or "Foto",
        "time": f"{dati['ore']:02d}:{dati['minuti']:02d}",
        "type": "photo"
    })

   await update.message.reply_text(
        f"✅ Reminder con foto salvato!\n"
        f"\"{caption or 'Foto'}\"\n"
        f"Alle {dati['ore']:02d}:{dati['minuti']:02d} 📸",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu")]])
    )
    del context.user_data[user_id]

flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot Telegram attivo! (Port: {})".format(os.environ.get('PORT', 10000))

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.Regex(r"(?i)^(ciao|menu|hey|avvia)"), mostra_menu))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gestisci_testo))
app.add_handler(MessageHandler(filters.PHOTO, gestisci_foto))
app.add_handler(CallbackQueryHandler(button_handler))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Bot Telegram + Flask avviati! In ascolto...")
    app.run_polling()



