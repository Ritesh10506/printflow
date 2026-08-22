import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.utils.assignment import find_free_printer

router = APIRouter(prefix="/api/public/payments", tags=["payments"])


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


@router.post("/{order_id}/init", response_model=schemas.PaymentInitOut)
def init_payment(order_id: str, db: Session = Depends(get_db)):
    """
    Step 4: customer taps 'Pay'. Creates a payment record and (in production)
    a Razorpay order via their Orders API. Wire the real SDK call in where noted --
    everything downstream (verify, queueing) doesn't care which gateway you use.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.amount <= 0:
        raise HTTPException(status_code=400, detail="Get a quote before paying")

    # TODO: replace with a real Razorpay order creation call:
    #   client.order.create({"amount": int(order.amount * 100), "currency": "INR"})
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
    )


@router.post("/{order_id}/verify", response_model=schemas.OrderOut)
def verify_payment(order_id: str, payload: schemas.PaymentVerifyIn, db: Session = Depends(get_db)):
    """
    Step 5: called after the gateway confirms payment (from client callback,
    or better -- a server-to-server webhook, which is what you should use in
    production so a customer can't fake a successful payment by just calling
    this endpoint directly). TODO: verify Razorpay's HMAC signature here.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not order.payment:
        raise HTTPException(status_code=400, detail="No payment was initiated for this order")

    # TODO: real signature check, e.g.
    #   expected = hmac_sha256(order.payment.gateway_order_ref + "|" + payload.gateway_payment_ref, secret)
    #   if expected != payload.signature: raise HTTPException(400, "Signature mismatch")

    order.payment.gateway_payment_ref = payload.gateway_payment_ref
    order.payment.status = models.PaymentStatus.SUCCESS
    order.status = models.OrderStatus.PAID
    order.paid_at = datetime.utcnow()
    db.commit()

    try_assign_printer(db, order)
    db.refresh(order)
    return order
