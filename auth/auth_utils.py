import os

from jose import JWTError, jwt
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from database import SessionLocal
from models import UserDB

SECRET_KEY = os.environ.get("SECRET_KEY", "secret123")
ALGORITHM = "HS256"
security = HTTPBearer()

def create_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return user
