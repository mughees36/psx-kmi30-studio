from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal
import schemas
from auth.auth_service import create_user, authenticate_user
from auth.auth_utils import create_token, get_current_user
from models import UserDB

router = APIRouter(prefix="/auth")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/signup", response_model=schemas.UserPublic)
def signup(user: schemas.UserCreate, db: Session = Depends(get_db)):
    return create_user(db, user.email, user.password, user.phone)

@router.post("/login", response_model=schemas.Token)
def login(user: schemas.UserLogin, db: Session = Depends(get_db)):
    db_user = authenticate_user(db, user.email, user.password)
    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token({"user_id": db_user.id})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=schemas.UserProfile)
def get_profile(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    del db
    return {
        "id": current_user.id,
        "email": current_user.email,
        "phone": current_user.phone or "",
    }
