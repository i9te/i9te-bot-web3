# ==============================================
# file: models.py
# ==============================================
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    region = Column(String(32), default=None, index=True)
    premium = Column(Boolean, default=False, nullable=False)
    partner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    partner = relationship("User", remote_side=[id], uselist=False)

class Wallet(Base):
    __tablename__ = "wallets"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    phrase_base = Column(String(64), nullable=True)  # masked base only (not full secret)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_wallet_user"),
    )

# ==============================================
# file: utils.py
# ==============================================
from __future__ import annotations
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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
    # placeholder for future mini-app
    rows.append([InlineKeyboardButton("🧩 Mini App", url="https://example.com")])
    return InlineKeyboardMarkup(rows)

# ==============================================
# file: db.py
# ==============================================
from __future__ import annotations
import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL env var is required")

# Why pool_pre_ping: keep connections healthy on Render
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

# ==============================================
# file: bot.py
# ==============================================
from __future__ import annotations
import logging
import os
from typing import Optional

from telegram import Update
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
from utils import infer_region, main_menu, CONTINENTS

logging.basicConfig(level=os.getenv("LOGLEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN env var is required")

# Initialize schema
Base.metadata.create_all(bind=engine)

# ---------------- Helpers ----------------

def get_user(telegram_id: int, language_code: Optional[str]) -> User:
    with session_scope() as s:
        user: Optional[User] = s.execute(select(User).where(User.telegram_id == telegram_id)).scalar_one_or_none()
        if user:
            return user
        region = infer_region(language_code)
        user = User(telegram_id=telegram_id, region=region, premium=False)
        s.add(user)
        # committed by context manager
        return user

# ---------------- Handlers ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    user = get_user(update.effective_user.id, update.effective_user.language_code)
    await update.message.reply_text(
        f"Welcome {update.effective_user.first_name}!\nRegion: {user.region}\nUse buttons below.",
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
        # Try to find a partner in same region without partner
        with session_scope() as s:
            me: User = s.merge(user)
            if me.partner_id:
                await query.message.reply_text("You are already connected.")
                return
            partner: Optional[User] = (
                s.query(User)
                .filter(User.partner_id.is_(None), User.telegram_id != me.telegram_id, User.region == me.region)
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
                    # If delivery fails, detach partner
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
        # Stop current and immediately find again
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
        # Reuse find
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

    # Region change flow (premium)
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

    # Normal chat forwarding
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

# --------------- main ---------------
def main() -> None:
    token = BOT_TOKEN
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()

# ==============================================
# file: web.py
# ==============================================
from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from db import session_scope, engine
from models import Base, User, Wallet

app = FastAPI(title="AnonBot Web API")
Base.metadata.create_all(bind=engine)

class WalletInitIn(BaseModel):
    telegram_id: int
    action: str = Field(pattern="^(generate|import)$")
    phrase: str | None = None

class WalletOut(BaseModel):
    user_id: int
    phrase_base: str | None

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/wallet/init", response_model=WalletOut)
def wallet_init(body: WalletInitIn):
    # Note: demo only; do not store real seed securely here.
    with session_scope() as s:
        user = s.execute(select(User).where(User.telegram_id == body.telegram_id)).scalar_one_or_none()
        if not user:
            user = User(telegram_id=body.telegram_id)
            s.add(user)
            s.flush()
        wallet = s.execute(select(Wallet).where(Wallet.user_id == user.id)).scalar_one_or_none()
        if not wallet:
            wallet = Wallet(user_id=user.id)
            s.add(wallet)
        if body.action == "generate":
            # Keep only masked base (first 8 chars of a fake phrase)
            import secrets
            fake = secrets.token_hex(16)
            wallet.phrase_base = fake[:8]
        elif body.action == "import":
            if not body.phrase:
                raise HTTPException(400, "phrase required for import")
            wallet.phrase_base = body.phrase.strip()[:8]
        return WalletOut(user_id=user.id, phrase_base=wallet.phrase_base)

# To run on Render Web Service, set Start Command:
# uvicorn web:app --host 0.0.0.0 --port 10000

# ==============================================
# file: requirements.txt
# ==============================================
python-telegram-bot==20.6
SQLAlchemy==2.0.23
psycopg2-binary==2.9.9
fastapi==0.115.2
uvicorn[standard]==0.30.6

# ==============================================
# file: Procfile
# ==============================================
worker: python bot.py
web: uvicorn web:app --host 0.0.0.0 --port 10000

# ==============================================
# file: README.md
# ==============================================
# Telegram Anonymous Chat (Hybrid)

- Worker: Telegram bot (polling) with inline buttons and DB pairing.
- Web: FastAPI for future Mini DApps (wallet stub included).

## Env Vars
- `BOT_TOKEN`: Telegram BotFather token
- `DATABASE_URL`: Postgres URL (Render Internal URL recommended)

## Deploy (Render)
1. Create **Postgres** → copy Internal Database URL → set as `DATABASE_URL`.
2. Create **Background Worker** (repo) → Start Command uses `Procfile` entry `worker`.
3. Create **Web Service** (repo) → Start Command uses `Procfile` entry `web`.

## Notes
- Region is auto-set from `language_code` at first start.
- `/setregion` available for premium users only (button shown if `premium=True`).
- Free tier supports text-only; media/AI can be added later via new handlers.
