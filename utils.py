from telegram import Update
from sqlalchemy.orm import Session
from models import User

def get_or_create_user(db: Session, tg_id: int, lang_code: str):
    user = db.query(User).filter_by(telegram_id=tg_id).first()
    if not user:
        user = User(
            telegram_id=tg_id,
            region=lang_code if lang_code else "global"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

def is_premium(user: User):
    return user.is_premium
