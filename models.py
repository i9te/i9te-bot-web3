from sqlalchemy import Column, Integer, String, Boolean
from db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True)
    region = Column(String, default="global")
    is_premium = Column(Boolean, default=False)
    is_busy = Column(Boolean, default=False)
    partner_id = Column(Integer, nullable=True)
