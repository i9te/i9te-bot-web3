from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from db import get_db
from models import User

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok", "msg": "Mini DApp API is running!"}

@app.get("/users/{tg_id}")
def get_user(tg_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(telegram_id=tg_id).first()
    if not user:
        return {"error": "User not found"}
    return {
        "telegram_id": user.telegram_id,
        "region": user.region,
        "premium": user.is_premium
    }
