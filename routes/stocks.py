from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import schemas
from auth.auth_utils import get_current_user, get_db
from models import FavoriteStockDB, UserDB
from services.psx_service import PSXServiceError, get_kmi30_index, get_kmi30_stocks, get_stock_detail

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/kmi30-index")
def kmi30_index_summary(current_user: UserDB = Depends(get_current_user)):
    del current_user
    try:
        return get_kmi30_index()
    except PSXServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/kmi30", response_model=list[schemas.StockListItem])
def list_kmi30_stocks(current_user: UserDB = Depends(get_current_user)):
    del current_user
    try:
        return get_kmi30_stocks()
    except PSXServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/favorites", response_model=schemas.FavoriteStocksResponse)
def list_favorite_stocks(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        all_stocks = get_kmi30_stocks()
    except PSXServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    favorite_symbols = sorted(
        {
            favorite.symbol
            for favorite in db.query(FavoriteStockDB)
            .filter(FavoriteStockDB.user_id == current_user.id)
            .all()
        }
    )
    favorite_symbol_set = set(favorite_symbols)
    favorite_stocks = [stock for stock in all_stocks if stock["symbol"].split()[0].upper() in favorite_symbol_set]
    return {"symbols": favorite_symbols, "stocks": favorite_stocks}


@router.post("/favorites/{symbol}")
def add_favorite_stock(
    symbol: str,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_symbol = symbol.split()[0].strip().upper()
    existing = (
        db.query(FavoriteStockDB)
        .filter(FavoriteStockDB.user_id == current_user.id, FavoriteStockDB.symbol == normalized_symbol)
        .first()
    )
    if existing:
        return {"message": "Already in favorites", "symbol": normalized_symbol}

    favorite = FavoriteStockDB(user_id=current_user.id, symbol=normalized_symbol)
    db.add(favorite)
    db.commit()
    return {"message": "Added to favorites", "symbol": normalized_symbol}


@router.delete("/favorites/{symbol}")
def remove_favorite_stock(
    symbol: str,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_symbol = symbol.split()[0].strip().upper()
    favorite = (
        db.query(FavoriteStockDB)
        .filter(FavoriteStockDB.user_id == current_user.id, FavoriteStockDB.symbol == normalized_symbol)
        .first()
    )
    if favorite is None:
        return {"message": "Favorite not found", "symbol": normalized_symbol}

    db.delete(favorite)
    db.commit()
    return {"message": "Removed from favorites", "symbol": normalized_symbol}


@router.get("/{symbol}", response_model=schemas.StockDetail)
def read_stock_detail(symbol: str, current_user: UserDB = Depends(get_current_user)):
    del current_user
    try:
        return get_stock_detail(symbol.upper())
    except PSXServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
