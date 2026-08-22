from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.utils.auth import hash_password, verify_password, create_access_token, get_current_shop

router = APIRouter(tags=["shops"])


@router.post("/api/shops/signup", response_model=schemas.ShopOut)
def signup(payload: schemas.ShopCreate, db: Session = Depends(get_db)):
    if db.query(models.Shop).filter(models.Shop.slug == payload.slug).first():
        raise HTTPException(status_code=400, detail="Slug already taken -- pick another")
    shop = models.Shop(
        name=payload.name,
        slug=payload.slug,
        owner_email=payload.owner_email,
        owner_password_hash=hash_password(payload.owner_password),
    )
    db.add(shop)
    db.commit()
    db.refresh(shop)
    return shop


@router.post("/api/shops/login")
def login(payload: schemas.ShopLogin, db: Session = Depends(get_db)):
    shop = db.query(models.Shop).filter(models.Shop.owner_email == payload.owner_email).first()
    if not shop or not verify_password(payload.owner_password, shop.owner_password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(shop.id)
    return {"access_token": token, "token_type": "bearer", "shop": schemas.ShopOut.model_validate(shop)}


@router.get("/api/shops/me", response_model=schemas.ShopOut)
def me(shop: models.Shop = Depends(get_current_shop)):
    return shop


# ---- Public, unauthenticated: what the QR code points to ----
@router.get("/api/public/shops/{slug}", response_model=schemas.ShopOut)
def public_shop_info(slug: str, db: Session = Depends(get_db)):
    """Called by the customer web app right after scanning the QR."""
    shop = db.query(models.Shop).filter(models.Shop.slug == slug, models.Shop.is_active == True).first()  # noqa: E712
    if not shop:
        raise HTTPException(status_code=404, detail="This print shop link is invalid or inactive")
    return shop
