from sqlalchemy.orm import Session
from fastapi import HTTPException
from models import UserDB
from passlib.hash import bcrypt

def create_user(db: Session, email: str, password: str, phone: str):
    existing_user = db.query(UserDB).filter(UserDB.email == email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    if not phone.strip():
        raise HTTPException(status_code=400, detail="Phone number is required")

    hashed = bcrypt.hash(password)
    user = UserDB(email=email, password=hashed, phone=phone.strip())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def authenticate_user(db: Session, email: str, password: str):
    user = db.query(UserDB).filter(UserDB.email == email).first()
    if not user:
        return None
    if not bcrypt.verify(password, user.password):
        return None
    return user
