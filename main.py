import json
import logging
import os
import re
import uuid

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    Filters,
)

logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "reminders.json"
TZ = pytz.timezone("Europe/Rome")

updater = None
bot = None

scheduler = BackgroundScheduler(timezone=TZ)
scheduler.start()

user_data = {}
user_state = {}


def load_data():
    """Load reminders and names from disk, best-effort."""
    global user_data
    if not os.path.exists(DATA_FILE):
        user_data = {}
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        user_data = {int(k): v for k, v in raw.items()}
    except Exception:
        logging.exception("Errore caricamento dati, avvio con dati vuoti.")
        user_data = {}


def save_data():
    """Persist reminders and names to disk."""
    try:
        serializable = {str(k): v for k, v in user_data.items()}
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception("Errore salvataggio dati.")


def manda_messaggio(chat_id: int, testo: str):
    if bot:
        bot.send_message(chat_id=chat_id, text=testo)


def manda_foto(chat_id: int, photo_id: str, caption: str):
    if bot:
        bot.send_photo(chat_id=chat_id, photo=photo_id, caption=caption)


def start(update, context):
    user_id = update.effective_user.id
    if user_id in user_data and user_data[user_id].get("name"):
        mostra_menu(update, context)
        return
    update.message.reply_text("Ciao! Come vuoi che ti chiami?\nScrivi il tuo nome (es. Rico Plus)")
    user_state[user_id] = {"step": "nome"}


def salva_nome(update, context):
    user_id = update.effective_user.id
    if user_state.get(user_id, {}).get("step") != "nome":
        return
    nome = update.message.text.strip().split()[0].capitalize()
    user_data[user_id] = {"name": nome, "reminders": []}
    save_data()
    del user_state[user_id]
    update.message.reply_text(
        f"Perfetto {nome}! Nome salvato.\nOra puoi usare il bot!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Apri menu", callback_data="menu")]])
    )


def mostra_menu(update, context):
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
        update.message.reply_text(testo, reply_markup=reply_markup)
    else:
        update.callback_query.edit_message_text(testo, reply_markup=reply_markup)


def button_handler(update, context):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "menu":
        mostra_menu(update, context)
        return

    if data in ["add_text", "add_photo"]:
        tipo = "text" if data == "add_text" else "photo"
        user_state[user_id] = {"step": "giorni", "tipo": tipo, "temp": {"giorni": []}}

        giorni = [
            ("Lunedi", "mon"), ("Martedi", "tue"), ("Mercoledi", "wed"),
            ("Giovedi", "thu"), ("Venerdi", "fri"), ("Sabato", "sat"), ("Domenica", "sun")
        ]
        keyboard = []
        for nome, cod in giorni:
            keyboard.append([InlineKeyboardButton(f"[ ] {nome}", callback_data=f"giorno_{cod}")])
        keyboard.append([InlineKeyboardButton("[ ] Ogni giorno", callback_data="giorno_*")])
        keyboard.append([InlineKeyboardButton("Invia", callback_data="giorni_ok")])

        query.edit_message_text("Scegli i giorni (puoi selezionarne piu di uno):", reply_markup=InlineKeyboardMarkup(keyboard))

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

        tutti_giorni = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        keyboard = []
        day_names = ["Lunedi", "Martedi", "Mercoledi", "Giovedi", "Venerdi", "Sabato", "Domenica"]
        for cod in tutti_giorni:
            nome = day_names[tutti_giorni.index(cod)]
            spunta = "[x]" if cod in giorni_selezionati else "[ ]"
            keyboard.append([InlineKeyboardButton(f"{spunta} {nome}", callback_data=f"giorno_{cod}")])
        spunta_ogni = "[x]" if "*" in giorni_selezionati else "[ ]"
        keyboard.append([InlineKeyboardButton(f"{spunta_ogni} Ogni giorno", callback_data="giorno_*")])
        keyboard.append([InlineKeyboardButton("Invia", callback_data="giorni_ok")])

        query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "giorni_ok":
        giorni = user_state[user_id]["temp"]["giorni"]
        if not giorni:
            query.edit_message_text(
                "Devi selezionare almeno un giorno!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Riprova", callback_data="add_" + user_state[user_id]["tipo"])]])
            )
            return
        user_state[user_id]["temp"]["giorni_cron"] = giorni
        user_state[user_id]["step"] = "ora"
        query.edit_message_text("Scrivi l'orario (es. 22:30, 22.30, 7.5, 9)")

    elif data == "cancella":
        reminders = user_data.get(user_id, {}).get("reminders", [])
        if not reminders:
            query.edit_message_text("Nessun reminder da cancellare", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Menu", callback_data="menu")]]))
            return
        kb = [[InlineKeyboardButton(f"{i+1}. {r['text']} - {r['time']}", callback_data=f"del_{i}")] for i, r in enumerate(reminders)]
        kb.append([InlineKeyboardButton("Menu", callback_data="menu")])
        query.edit_message_text("Scegli cosa cancellare:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("del_"):
        idx = int(data.split("_")[1])
        job_id = user_data[user_id]["reminders"][idx]["id"]
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
        del user_data[user_id]["reminders"][idx]
        save_data()
        query.edit_message_text("Cancellato!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Menu", callback_data="menu")]]))


def gestisci_testo(update, context):
    user_id = update.effective_user.id
    testo = update.message.text.strip()

    if user_state.get(user_id, {}).get("step") == "nome":
        salva_nome(update, context)
        return

    stato = user_state.get(user_id)
    if not stato or stato["step"] not in ["ora", "messaggio"]:
        mostra_menu(update, context)
        return

    if stato["step"] == "ora":
        match = re.search(r"(\d{1,2})[:\.]?(\d{0,2})", testo.lower())
        if not match:
            update.message.reply_text("Orario non valido!\nEsempi: 22:30, 22.30, 7.5, 9")
            return
        ore = int(match.group(1))
        minuti = int(match.group(2)) if match.group(2) else 0
        if ore > 23 or minuti > 59:
            update.message.reply_text("Orario non valido (max 23:59)")
            return

        stato["temp"]["ora"] = ore
        stato["temp"]["minuti"] = minuti
        stato["step"] = "messaggio"
        update.message.reply_text("Cosa vuoi che ti ricordi?")

    elif stato["step"] == "messaggio":
        messaggio = testo.strip() or "Promemoria"
        giorni = stato["temp"]["giorni_cron"]
        ore = stato["temp"]["ora"]
        minuti = stato["temp"]["minuti"]
        tipo = stato["tipo"]
        chat_id = update.effective_chat.id

        if tipo == "text":
            for giorno in giorni:
                job_id = f"{user_id}_{giorno}_{ore}_{minuti}_{tipo}_{uuid.uuid4().hex}"
                scheduler.add_job(
                    manda_messaggio,
                    CronTrigger(day_of_week=giorno, hour=ore, minute=minuti, timezone=TZ),
                    args=[chat_id, f"Reminder: {messaggio}"],
                    id=job_id,
                    replace_existing=True
                )

                base = user_data.get(user_id, {})
                user_data[user_id] = {
                    "name": base.get("name"),
                    "reminders": base.get("reminders", []),
                }
                user_data[user_id]["reminders"].append({
                    "id": job_id,
                    "text": messaggio,
                    "time": f"{ore:02d}:{minuti:02d}",
                    "type": tipo,
                    "day": giorno,
                    "chat_id": chat_id,
                })

            update.message.reply_text(
                f"Reminder salvato!\n\"{messaggio}\"\nAlle {ore:02d}:{minuti:02d}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Menu", callback_data="menu")]])
            )
            save_data()
            del user_state[user_id]

        else:
            context.user_data[user_id] = {
                "chat_id": chat_id,
                "caption": messaggio,
                "giorni": giorni,
                "ore": ore,
                "minuti": minuti
            }
            update.message.reply_text("Mandami la foto per questo reminder")
            del user_state[user_id]


def gestisci_foto(update, context):
    user_id = update.effective_user.id
    dati = context.user_data.get(user_id)
    stato = user_state.get(user_id)

    if not dati and stato and stato.get("step") == "messaggio" and stato.get("tipo") == "photo":
        dati = {
            "chat_id": update.effective_chat.id,
            "caption": (update.message.caption or "").strip() or "Promemoria",
            "giorni": stato["temp"]["giorni_cron"],
            "ore": stato["temp"]["ora"],
            "minuti": stato["temp"]["minuti"],
        }
        del user_state[user_id]
    elif not dati:
        update.message.reply_text("Per creare un reminder con foto, apri il menu e scegli giorni e ora prima di inviare la foto.")
        return

    photo_id = update.message.photo[-1].file_id
    caption = (update.message.caption or "").strip() or dati["caption"] or "Promemoria"

    for giorno in dati["giorni"]:
        job_id = f"{user_id}_{giorno}_{dati['ore']}_{dati['minuti']}_photo_{uuid.uuid4().hex}"
        scheduler.add_job(
            manda_foto,
            CronTrigger(day_of_week=giorno, hour=dati["ore"], minute=dati["minuti"], timezone=TZ),
            args=[dati["chat_id"], photo_id, f"Reminder: {caption}"],
            id=job_id,
            replace_existing=True
        )

        base = user_data.get(user_id, {})
        user_data[user_id] = {
            "name": base.get("name"),
            "reminders": base.get("reminders", []),
        }
        user_data[user_id]["reminders"].append({
            "id": job_id,
            "text": caption or "Foto",
            "time": f"{dati['ore']:02d}:{dati['minuti']:02d}",
            "type": "photo",
            "day": giorno,
            "chat_id": dati["chat_id"],
            "photo_id": photo_id,
        })

    day_names = ["Lunedi", "Martedi", "Mercoledi", "Giovedi", "Venerdi", "Sabato", "Domenica"]
    giorni_testo = ", ".join([
        "ogni giorno" if g == "*" else day_names[["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(g)]
        for g in dati["giorni"]
    ])

    update.message.reply_text(
        f"Reminder con foto salvato!\n"
        f"\"{caption or 'Foto'}\"\n"
        f"Giorni: {giorni_testo}\n"
        f"Alle {dati['ore']:02d}:{dati['minuti']:02d}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Menu", callback_data="menu")]])
    )
    if user_id in context.user_data:
        del context.user_data[user_id]
    save_data()


def ripristina_reminders():
    """Re-aggiunge i job da user_data a scheduler dopo un riavvio."""
    for uid, data in user_data.items():
        for rem in data.get("reminders", []):
            try:
                ore, minuti = rem["time"].split(":")
                ore = int(ore)
                minuti = int(minuti)
                giorno = rem.get("day", "*")
                if rem["type"] == "text":
                    scheduler.add_job(
                        manda_messaggio,
                        CronTrigger(day_of_week=giorno, hour=ore, minute=minuti, timezone=TZ),
                        args=[rem["chat_id"], f"Reminder: {rem['text']}"],
                        id=rem["id"],
                        replace_existing=True
                    )
                else:
                    scheduler.add_job(
                        manda_foto,
                        CronTrigger(day_of_week=giorno, hour=ore, minute=minuti, timezone=TZ),
                        args=[rem["chat_id"], rem["photo_id"], f"Reminder: {rem['text']}"],
                        id=rem["id"],
                        replace_existing=True
                    )
            except Exception:
                logging.exception("Errore ripristino reminder utente %s", uid)


def main():
    global updater, bot
    load_data()
    updater = Updater(TOKEN, use_context=True)
    bot = updater.bot

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.regex(r"(?i)^(ciao|menu|hey|avvia)"), mostra_menu))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, gestisci_testo))
    dp.add_handler(MessageHandler(Filters.photo, gestisci_foto))
    dp.add_handler(CallbackQueryHandler(button_handler))

    ripristina_reminders()

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()

    print("Bot Telegram con webhook avviato!")

