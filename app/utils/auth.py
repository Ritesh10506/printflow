import os
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status, Header
import bcrypt
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Shop, PrintAgent

load_dotenv()

SECRET_KEY = os.environ.get("JWT_SECRET")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET is not set. Create a .env file (see .env.example) with a "
        "random JWT_SECRET value before starting the server."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(shop_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": shop_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_shop(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Shop:
    """
    Shop-owner dashboard auth. Expects: Authorization: Bearer <jwt>
    Every dashboard-facing route depends on this so shop_id NEVER comes from
    the client's request body/query params -- it's derived from the token.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        shop_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop or not shop.is_active:
        raise HTTPException(status_code=401, detail="Shop not found or inactive")
    return shop


def get_current_agent(
    x_api_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> PrintAgent:
    """
    Print-agent auth. Expects: X-API-Key: <agent api key>
    The agent's shop_id is derived from the key -- an agent can never poll
    or act on another shop's jobs, even if it tried to.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    agent = db.query(PrintAgent).filter(
        PrintAgent.api_key == x_api_key, PrintAgent.is_active == True  # noqa: E712
    ).first()
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return agent