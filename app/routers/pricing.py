from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.utils.auth import get_current_shop

router = APIRouter(prefix="/api/pricing", tags=["pricing"])


@router.get("", response_model=list[schemas.PricingRuleOut])
def list_rules(
    db: Session = Depends(get_db),
    shop: models.Shop = Depends(get_current_shop),
):
    return db.query(models.PricingRule).filter(models.PricingRule.shop_id == shop.id).all()


@router.post("", response_model=schemas.PricingRuleOut)
def upsert_rule(
    payload: schemas.PricingRuleCreate,
    db: Session = Depends(get_db),
    shop: models.Shop = Depends(get_current_shop),
):
    existing = (
        db.query(models.PricingRule)
        .filter(
            models.PricingRule.shop_id == shop.id,
            models.PricingRule.paper_size == payload.paper_size,
            models.PricingRule.color_mode == payload.color_mode,
        )
        .first()
    )
    if existing:
        for field, value in payload.model_dump().items():
            setattr(existing, field, value)
        db.commit()
        db.refresh(existing)
        return existing

    rule = models.PricingRule(shop_id=shop.id, **payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    shop: models.Shop = Depends(get_current_shop),
):
    rule = (
        db.query(models.PricingRule)
        .filter(models.PricingRule.id == rule_id, models.PricingRule.shop_id == shop.id)
        .first()
    )
    if rule:
        db.delete(rule)
        db.commit()
    return {"ok": True}
