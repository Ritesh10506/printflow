import os
import uuid
import shutil

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from PyPDF2 import PdfReader

from app.database import get_db
from app import models, schemas
from app.utils.pricing_engine import calculate_price
from app.utils.auth import get_current_shop

router = APIRouter(tags=["orders"])

# Local disk storage for the MVP. Swap this function's body for a Cloudinary
# upload call later -- nothing else in the app needs to change, since every
# order only ever stores/reads `file_url`.
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def save_file_and_get_url(upload: UploadFile) -> tuple[str, str]:
    ext = os.path.splitext(upload.filename)[1] or ".pdf"
    stored_name = f"{uuid.uuid4()}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, stored_name)
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    # In production this becomes the Cloudinary secure_url instead of a local path.
    url = f"/files/{stored_name}"
    return url, dest_path


def count_pdf_pages(path: str) -> int:
    try:
        reader = PdfReader(path)
        return len(reader.pages)
    except Exception:
        # Non-PDF upload (docx etc.) -- MVP assumes PDF; conversion step
        # (LibreOffice headless) plugs in right here before page counting.
        return 1


@router.post("/api/public/shops/{slug}/orders", response_model=schemas.OrderOut)
def create_order(
    slug: str,
    file: UploadFile = File(...),
    customer_phone: str = Form(None),
    db: Session = Depends(get_db),
):
    """Step 1 of the customer flow: upload a file right after scanning the QR."""
    shop = db.query(models.Shop).filter(models.Shop.slug == slug, models.Shop.is_active == True).first()  # noqa: E712
    if not shop:
        raise HTTPException(status_code=404, detail="This print shop link is invalid or inactive")

    url, path = save_file_and_get_url(file)
    page_count = count_pdf_pages(path)

    order = models.Order(
        shop_id=shop.id,
        customer_phone=customer_phone,
        file_url=url,
        original_filename=file.filename,
        page_count=page_count,
        status=models.OrderStatus.CART,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.get("/api/public/orders/{order_id}", response_model=schemas.OrderOut)
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.patch("/api/public/orders/{order_id}/options", response_model=schemas.OrderOut)
def update_options(order_id: str, payload: schemas.OrderOptionsUpdate, db: Session = Depends(get_db)):
    """Step 2: customer sets color/duplex/copies/page-range on the edit screen."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != models.OrderStatus.CART:
        raise HTTPException(status_code=400, detail="This order is already past the editing stage")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(order, field, value)
    db.commit()
    db.refresh(order)
    return order


@router.get("/api/public/orders/{order_id}/quote", response_model=schemas.PriceQuote)
def get_quote(order_id: str, db: Session = Depends(get_db)):
    """Step 3: show total price before payment. Recomputed server-side, never trusts the client."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        quote = calculate_price(
            db,
            shop_id=order.shop_id,
            total_pages=order.page_count,
            color_mode=order.color_mode,
            duplex=order.duplex,
            copies=order.copies,
            paper_size=order.paper_size,
            binding=order.binding,
            page_range=order.page_range,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    order.amount = quote["amount"]
    db.commit()
    return quote


# ---- Shop-owner dashboard: view orders for this shop ----
@router.get("/api/orders", response_model=list[schemas.OrderOut])
def list_shop_orders(
    db: Session = Depends(get_db),
    shop: models.Shop = Depends(get_current_shop),
):
    return (
        db.query(models.Order)
        .filter(models.Order.shop_id == shop.id)
        .order_by(models.Order.created_at.desc())
        .all()
    )
