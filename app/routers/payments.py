import os
import uuid
from datetime import datetime

import razorpay
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.utils.assignment import find_free_printer
from app.utils.auth import get_current_shop

router = APIRouter(tags=["payments"])

# Fallback only, used if a shop hasn't connected its own Razorpay account yet --
# lets the app stay testable without every shop needing keys immediately.
PLATFORM_RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
PLATFORM_RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")


def get_razorpay_client_for_shop(shop: models.Shop):
    """
    Every shop pays into ITS OWN Razorpay account -- the platform never
    touches customer money. Falls back to a platform-wide test account only
    if the shop hasn't connected one yet, and to no client at all (mock mode)
    if neither is configured.
    """
    key_id = shop.razorpay_key_id or PLATFORM_RAZORPAY_KEY_ID
    key_secret = shop.razorpay_key_secret or PLATFORM_RAZORPAY_KEY_SECRET
    if key_id and key_secret:
        return razorpay.Client(auth=(key_id, key_secret)), key_id
    return None, None


def try_assign_printer(db: Session, order: models.Order) -> bool:
    """Attempts to hand a PAID order to a free, capable printer. Returns True if assigned."""
    if order.status != models.OrderStatus.PAID:
        return False
    printer = find_free_printer(
        db,
        shop_id=order.shop_id,
        color_mode=order.color_mode,
        duplex=order.duplex,
        paper_size=order.paper_size,
    )
    if not printer:
        return False
    order.printer_id = printer.id
    order.assigned_agent_id = printer.agent_id
    order.status = models.OrderStatus.QUEUED
    db.commit()
    return True


@router.post("/api/public/payments/{order_id}/init", response_model=schemas.PaymentInitOut)
def init_payment(order_id: str, db: Session = Depends(get_db)):
    """
    Step 4: customer taps 'Pay'. Creates a real Razorpay order under the
    SHOP'S OWN account so money goes directly to them.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.amount <= 0:
        raise HTTPException(status_code=400, detail="Get a quote before paying")

    client, key_id = get_razorpay_client_for_shop(order.shop)

    if client:
        rp_order = client.order.create({
            "amount": int(round(order.amount * 100)),  # Razorpay wants paise, not rupees
            "currency": "INR",
            "receipt": order.id,
            "notes": {"order_id": order.id, "shop_id": order.shop_id},
        })
        gateway_order_ref = rp_order["id"]
    else:
        # No Razorpay keys configured for this shop or the platform -- falls
        # back to test mode so the rest of the app still works.
        gateway_order_ref = f"mock_order_{uuid.uuid4().hex[:12]}"

    payment = order.payment
    if not payment:
        payment = models.Payment(order_id=order.id, amount=order.amount)
        db.add(payment)
    payment.gateway_order_ref = gateway_order_ref
    payment.amount = order.amount
    payment.status = models.PaymentStatus.PENDING
    order.status = models.OrderStatus.AWAITING_PAYMENT
    db.commit()

    return schemas.PaymentInitOut(
        order_id=order.id,
        amount=order.amount,
        gateway=payment.gateway,
        gateway_order_ref=gateway_order_ref,
        razorpay_key_id=key_id,
    )


@router.post("/api/public/payments/{order_id}/verify", response_model=schemas.OrderOut)
def verify_payment(order_id: str, payload: schemas.PaymentVerifyIn, db: Session = Depends(get_db)):
    """
    Step 5: called after Razorpay's checkout popup confirms payment.
    Verifies the cryptographic signature using the SAME shop-specific
    credentials the order was created with.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not order.payment:
        raise HTTPException(status_code=400, detail="No payment was initiated for this order")

    client, _ = get_razorpay_client_for_shop(order.shop)

    if client:
        if not payload.signature:
            raise HTTPException(status_code=400, detail="Missing payment signature")
        try:
            client.utility.verify_payment_signature({
                "razorpay_order_id": order.payment.gateway_order_ref,
                "razorpay_payment_id": payload.gateway_payment_ref,
                "razorpay_signature": payload.signature,
            })
        except razorpay.errors.SignatureVerificationError:
            order.payment.status = models.PaymentStatus.FAILED
            db.commit()
            raise HTTPException(status_code=400, detail="Payment signature verification failed")

    order.payment.gateway_payment_ref = payload.gateway_payment_ref
    order.payment.status = models.PaymentStatus.SUCCESS
    order.status = models.OrderStatus.PAID
    order.paid_at = datetime.utcnow()
    db.commit()

    try_assign_printer(db, order)
    db.refresh(order)
    return order


# ---- Shop-owner dashboard: connect their own Razorpay account ----
@router.get("/api/payments/settings", response_model=schemas.PaymentSettingsOut)
def get_payment_settings(shop: models.Shop = Depends(get_current_shop)):
    return schemas.PaymentSettingsOut(
        razorpay_key_id=shop.razorpay_key_id,
        is_configured=bool(shop.razorpay_key_id and shop.razorpay_key_secret),
    )


@router.post("/api/payments/settings", response_model=schemas.PaymentSettingsOut)
def set_payment_settings(
    payload: schemas.PaymentSettingsIn,
    db: Session = Depends(get_db),
    shop: models.Shop = Depends(get_current_shop),
):
    shop.razorpay_key_id = payload.razorpay_key_id.strip()
    shop.razorpay_key_secret = payload.razorpay_key_secret.strip()
    db.commit()
    return schemas.PaymentSettingsOut(razorpay_key_id=shop.razorpay_key_id, is_configured=True)


@router.delete("/api/payments/settings")
def clear_payment_settings(db: Session = Depends(get_db), shop: models.Shop = Depends(get_current_shop)):
    shop.razorpay_key_id = None
    shop.razorpay_key_secret = None
    db.commit()
    return {"ok": True}