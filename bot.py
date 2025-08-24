# ==============================================
# file: bot.py
# ==============================================
from __future__ import annotations
import logging
import os
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from sqlalchemy import select

from db import session_scope, engine
from models import Base, User

# ---------------- Logging ----------------
logging.basicConfig(
    level=os.getenv("LOGLEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN env var is required")

# Initialize schema
Base.metadata.create_all(bind=engine)

# ---------------- Region helpers ----------------
LANG_REGION_MAP = {
    "id": "Asia", "ms": "Asia", "zh": "Asia", "ja": "Asia",
    "en": "NorthAmerica", "en-US": "NorthAmerica", "en-GB": "Europe",
    "es": "SouthAmerica", "es-ES": "Europe", "pt-BR": "SouthAmerica",
    "fr": "Europe", "de": "Europe", "ru": "Europe",
}
CONTINENTS = ["Africa", "Asia", "Europe", "NorthAmerica", "SouthAmerica", "Oceania"]

def infer_region(language_code: str | None) -> str:
    if not language_code:
        return "Europe"
    return LANG_REGION_MAP.get(language_code, LANG_REGION_MAP.get(language_code.split("-")[0], "Europe"))

def main_menu(premium: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🟢 Find Partner", callback_data="find")],
        [InlineKeyboardButton("🔄 Next Partner", callback_data="next")],
        [InlineKeyboardButton("🔴 Stop Chat", callback_data="stop")],
    ]
    if premium:
        rows.append([InlineKeyboardButton("🌍 Set Region", callback_data="setregion")])
    rows.append([InlineKeyboardButton("🧩 Mini App", url="https://example.com")])
    return InlineKeyboardMarkup(rows)

# ---------------- DB helper ----------------
def get_user(telegram_id: int, language_code: Optional[str]) -> User:
    with session_scope() as s:
        user: Optional[User] = (
            s.execute(select(User).where(User.telegram_id == telegram_id))
            .scalar_one_or_none()
        )
        if user:
            return user
        region = infer_region(language_code)
        user = User(telegram_id=telegram_id, region=region, premium=False)
        s.add(user)
        return user

# ---------------- Handlers ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    user = get_user(update.effective_user.id, update.effective_user.language_code)
    await update.message.reply_text(
        f"Welcome {update.effective_user.first_name}!\n"
        f"Region: {user.region}\nUse buttons below.",
        reply_markup=main_menu(user.premium),
    )

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    tg_id = query.from_user.id
    user = get_user(tg_id, query.from_user.language_code)

    if query.data == "find":
        with session_scope() as s:
            me: User = s.merge(user)
            if me.partner_id:
                await query.message.reply_text("You are already connected.")
                return
            partner: Optional[User] = (
                s.query(User)
                .filter(User.partner_id.is_(None),
                        User.telegram_id != me.telegram_id,
                        User.region == me.region)
                .order_by(User.updated_at.asc())
                .first()
            )
            if partner:
                me.partner_id = partner.id
                partner.partner_id = me.id
                await query.message.reply_text("✅ Partner found! Start chatting.")
                try:
                    await context.bot.send_message(partner.telegram_id, "✅ Partner found! Start chatting.")
                except Exception:
                    partner.partner_id = None
                    me.partner_id = None
                    await query.message.reply_text("Partner unreachable. Try again.")
            else:
                await query.message.reply_text("⏳ Waiting for a partner in your region…")

    elif query.data == "stop":
        with session_scope() as s:
            me: User = s.merge(user)
            if not me.partner_id:
                await query.message.reply_text("You are not in a chat.")
            else:
                partner: Optional[User] = s.query(User).get(me.partner_id)
                me.partner_id = None
                if partner and partner.partner_id == me.id:
                    partner.partner_id = None
                    try:
                        await context.bot.send_message(partner.telegram_id, "❌ Your partner left.")
                    except Exception:
                        pass
                await query.message.reply_text("❌ Left chat.", reply_markup=main_menu(me.premium))

    elif query.data == "next":
        with session_scope() as s:
            me: User = s.merge(user)
            partner: Optional[User] = s.query(User).get(me.partner_id) if me.partner_id else None
            me.partner_id = None
            if partner and partner.partner_id == me.id:
                partner.partner_id = None
                try:
                    await context.bot.send_message(partner.telegram_id, "🔄 Your partner skipped you.")
                except Exception:
                    pass
        await query.message.reply_text("🔎 Searching new partner…")
        query.data = "find"
        await on_button(update, context)

    elif query.data == "setregion":
        if not user.premium:
            await query.message.reply_text("⚠️ Premium only.")
        else:
            context.user_data["await_region"] = True
            await query.message.reply_text(
                "Send the region name from: " + ", ".join(CONTINENTS)
            )

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    tg_id = update.effective_user.id
    txt = update.message.text
    user = get_user(tg_id, update.effective_user.language_code)

    if context.user_data.get("await_region") and user.premium:
        new_region = (txt or "").strip()
        if new_region not in CONTINENTS:
            await update.message.reply_text("Invalid region. Options: " + ", ".join(CONTINENTS))
            return
        with session_scope() as s:
            me = s.merge(user)
            me.region = new_region
        context.user_data["await_region"] = False
        await update.message.reply_text(f"✅ Region updated to {new_region}", reply_markup=main_menu(user.premium))
        return

    if user.partner_id:
        with session_scope() as s:
            partner = s.query(User).get(user.partner_id)
            if partner:
                try:
                    await context.bot.send_message(partner.telegram_id, txt)
                except Exception:
                    await update.message.reply_text("Delivery failed. Try Next.")
            else:
                await update.message.reply_text("Partner missing. Press Find.")
    else:
        await update.message.reply_text("Use the buttons to find a partner.", reply_markup=main_menu(user.premium))

# ---------------- Main ----------------
def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()
