import os, logging
from datetime import datetime
from contextlib import contextmanager
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")  # ambil dari env
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")  # default sqlite

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN required")

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("bot")

# ---------------- DATABASE ----------------
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()

# ---------------- MODELS ----------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    region = Column(String, nullable=False)
    premium = Column(Boolean, default=False)
    partner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    partner = relationship("User", remote_side=[id], uselist=False)

# Create tables
Base.metadata.create_all(bind=engine)

# ---------------- REGION ----------------
LANG_REGION_MAP = {
    "id":"Asia","ms":"Asia","zh":"Asia","ja":"Asia",
    "en":"NorthAmerica","en-US":"NorthAmerica","en-GB":"Europe",
    "es":"SouthAmerica","es-ES":"Europe","pt-BR":"SouthAmerica",
    "fr":"Europe","de":"Europe","ru":"Europe"
}
CONTINENTS = ["Africa","Asia","Europe","NorthAmerica","SouthAmerica","Oceania"]

def infer_region(language_code):
    if not language_code:
        return "Europe"
    return LANG_REGION_MAP.get(language_code, LANG_REGION_MAP.get(language_code.split("-")[0], "Europe"))

def main_menu(premium):
    buttons = [
        [InlineKeyboardButton("🟢 Find Partner", callback_data="find")],
        [InlineKeyboardButton("🔄 Next Partner", callback_data="next")],
        [InlineKeyboardButton("🔴 Stop Chat", callback_data="stop")]
    ]
    if premium:
        buttons.append([InlineKeyboardButton("🌍 Set Region", callback_data="setregion")])
    buttons.append([InlineKeyboardButton("🧩 Mini App", url="https://example.com")])
    return InlineKeyboardMarkup(buttons)

# ---------------- HELPERS ----------------
def get_user(telegram_id, language_code):
    with session_scope() as s:
        user = s.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            return user
        region = infer_region(language_code)
        user = User(telegram_id=telegram_id, region=region, premium=False)
        s.add(user)
        try:
            s.commit()
        except:
            s.rollback()
            user = s.query(User).filter_by(telegram_id=telegram_id).first()
        return user

# ---------------- HANDLERS ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id, update.effective_user.language_code)
    await update.message.reply_text(
        f"Welcome {update.effective_user.first_name}!\nRegion: {user.region}",
        reply_markup=main_menu(user.premium)
    )

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query: return
    await query.answer()
    tg_id = query.from_user.id
    user = get_user(tg_id, query.from_user.language_code)

    if query.data == "find":
        with session_scope() as s:
            me = s.merge(user)
            if me.partner_id:
                await query.message.reply_text("You are already connected.")
                return
            partner = s.query(User).filter(User.partner_id.is_(None), User.telegram_id!=me.telegram_id, User.region==me.region).order_by(User.updated_at.asc()).first()
            if partner:
                me.partner_id = partner.id
                partner.partner_id = me.id
                await query.message.reply_text("✅ Partner found! Start chatting.")
                try:
                    await context.bot.send_message(partner.telegram_id,"✅ Partner found! Start chatting.")
                except:
                    me.partner_id = None
                    partner.partner_id = None
                    await query.message.reply_text("Partner unreachable.")
            else:
                await query.message.reply_text("⏳ Waiting for a partner...")

    elif query.data == "stop":
        with session_scope() as s:
            me = s.merge(user)
            if not me.partner_id:
                await query.message.reply_text("You are not in a chat.")
                return
            partner = s.query(User).get(me.partner_id)
            me.partner_id = None
            if partner and partner.partner_id == me.id:
                partner.partner_id = None
                try:
                    await context.bot.send_message(partner.telegram_id,"❌ Your partner left.")
                except: pass
            await query.message.reply_text("❌ Left chat.", reply_markup=main_menu(me.premium))

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    txt = update.message.text
    user = get_user(tg_id, update.effective_user.language_code)
    if user.partner_id:
        with session_scope() as s:
            partner = s.query(User).get(user.partner_id)
            if partner:
                try:
                    await context.bot.send_message(partner.telegram_id, txt)
                except:
                    await update.message.reply_text("Delivery failed. Try Next.")
            else:
                await update.message.reply_text("Partner missing. Press Find.")
    else:
        await update.message.reply_text("Use the buttons to find a partner.", reply_markup=main_menu(user.premium))

# ---------------- MAIN ----------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()