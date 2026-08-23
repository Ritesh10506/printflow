import os
import uuid
from datetime import datetime

import razorpay
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.utils.assignment import find_free_printer

router = APIRouter(prefix="/api/public/payments", tags=["payments"])

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
razorpay_client = (
    razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET
    else None
)


def try_assign_printer(db: Session, order: models.Order) -> bool:
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


@router.post("/{order_id}/init", response_model=schemas.PaymentInitOut)
def init_payment(order_id: str, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.amount <= 0:
        raise HTTPException(status_code=400, detail="Get a quote before paying")

    if razorpay_client:
        rp_order = razorpay_client.order.create({
            "amount": int(round(order.amount * 100)),
            "currency": "INR",
            "receipt": order.id,
            "notes": {"order_id": order.id, "shop_id": order.shop_id},
        })
        gateway_order_ref = rp_order["id"]
    else:
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
        razorpay_key_id=RAZORPAY_KEY_ID,
    )


@router.post("/{order_id}/verify", response_model=schemas.OrderOut)
def verify_payment(order_id: str, payload: schemas.PaymentVerifyIn, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not order.payment:
        raise HTTPException(status_code=400, detail="No payment was initiated for this order")

    if razorpay_client:
        if not payload.signature:
            raise HTTPException(status_code=400, detail="Missing payment signature")
        try:
            razorpay_client.utility.verify_payment_signature({
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