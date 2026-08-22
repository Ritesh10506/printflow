from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.utils.auth import get_current_shop

router = APIRouter(prefix="/api/printers", tags=["printers"])


@router.get("", response_model=list[schemas.PrinterOut])
def list_printers(
    db: Session = Depends(get_db),
    shop: models.Shop = Depends(get_current_shop),
):
    return db.query(models.Printer).filter(models.Printer.shop_id == shop.id).all()


@router.delete("/{printer_id}")
def remove_printer(
    printer_id: str,
    db: Session = Depends(get_db),
    shop: models.Shop = Depends(get_current_shop),
):
    printer = (
        db.query(models.Printer)
        .filter(models.Printer.id == printer_id, models.Printer.shop_id == shop.id)
        .first()
    )
    if printer:
        db.delete(printer)
        db.commit()
    return {"ok": True}
