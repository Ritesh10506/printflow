import enum
import uuid
import secrets
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, Enum
)
from sqlalchemy.orm import relationship

from app.database import Base


def gen_id():
    return str(uuid.uuid4())


class OrderStatus(str, enum.Enum):
    CART = "cart"                  # file uploaded, still configuring
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    QUEUED = "queued"               # assigned to a printer, waiting for agent
    PRINTING = "printing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class PrinterStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    ERROR = "error"


class Shop(Base):
    __tablename__ = "shops"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)   # used in QR: yourapp.com/s/{slug}
    owner_email = Column(String, nullable=False)
    owner_password_hash = Column(String, nullable=False)
    plan = Column(String, default="trial")            # trial / basic / pro
    razorpay_key_id = Column(String, nullable=True)       # this shop's own Razorpay key id (public)
    razorpay_key_secret = Column(String, nullable=True)   # this shop's own Razorpay key secret — encrypt at rest before production
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    printers = relationship("Printer", back_populates="shop", cascade="all, delete-orphan")
    agents = relationship("PrintAgent", back_populates="shop", cascade="all, delete-orphan")
    pricing_rules = relationship("PricingRule", back_populates="shop", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="shop", cascade="all, delete-orphan")


class Printer(Base):
    __tablename__ = "printers"

    id = Column(String, primary_key=True, default=gen_id)
    shop_id = Column(String, ForeignKey("shops.id"), nullable=False, index=True)
    agent_id = Column(String, ForeignKey("print_agents.id"), nullable=True)
    name = Column(String, nullable=False)              # e.g. "HP LaserJet - Counter 1"
    os_printer_name = Column(String, nullable=False)    # exact name as seen by the agent/OS
    supports_color = Column(Boolean, default=True)
    supports_duplex = Column(Boolean, default=True)
    max_paper_size = Column(String, default="A4")       # A4 / A3 / Letter
    status = Column(Enum(PrinterStatus), default=PrinterStatus.OFFLINE)
    last_seen = Column(DateTime, nullable=True)

    shop = relationship("Shop", back_populates="printers")


class PrintAgent(Base):
    """One installed agent app per shop PC. A shop can have >1 agent (>1 PC)."""
    __tablename__ = "print_agents"

    id = Column(String, primary_key=True, default=gen_id)
    shop_id = Column(String, ForeignKey("shops.id"), nullable=False, index=True)
    name = Column(String, default="Print Agent")
    api_key = Column(String, unique=True, default=lambda: secrets.token_urlsafe(32), index=True)
    last_heartbeat = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    shop = relationship("Shop", back_populates="agents")


class PricingRule(Base):
    __tablename__ = "pricing_rules"

    id = Column(String, primary_key=True, default=gen_id)
    shop_id = Column(String, ForeignKey("shops.id"), nullable=False, index=True)
    paper_size = Column(String, default="A4")
    color_mode = Column(String, default="bw")           # bw / color
    price_per_page = Column(Float, nullable=False)
    duplex_discount_pct = Column(Float, default=0.0)     # % off per-page price if duplex
    binding_price = Column(Float, default=0.0)           # flat add-on if binding selected

    shop = relationship("Shop", back_populates="pricing_rules")


class Order(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True, default=gen_id)
    shop_id = Column(String, ForeignKey("shops.id"), nullable=False, index=True)
    customer_phone = Column(String, nullable=True)
    file_url = Column(String, nullable=True)             # storage URL (Cloudinary etc.)
    original_filename = Column(String, nullable=True)
    page_count = Column(Integer, default=0)

    # print options chosen by customer
    color_mode = Column(String, default="bw")             # bw / color
    duplex = Column(Boolean, default=False)
    copies = Column(Integer, default=1)
    paper_size = Column(String, default="A4")
    binding = Column(Boolean, default=False)
    page_range = Column(String, nullable=True)            # e.g. "1-5,8,10-12"; null = all pages

    amount = Column(Float, default=0.0)
    status = Column(Enum(OrderStatus), default=OrderStatus.CART)

    printer_id = Column(String, ForeignKey("printers.id"), nullable=True)
    assigned_agent_id = Column(String, ForeignKey("print_agents.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    failure_reason = Column(Text, nullable=True)

    shop = relationship("Shop", back_populates="orders")
    payment = relationship("Payment", back_populates="order", uselist=False, cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String, primary_key=True, default=gen_id)
    order_id = Column(String, ForeignKey("orders.id"), nullable=False, unique=True, index=True)
    gateway = Column(String, default="razorpay")
    gateway_order_ref = Column(String, nullable=True)     # id created at gateway before payment
    gateway_payment_ref = Column(String, nullable=True)   # id returned after successful payment
    amount = Column(Float, nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    order = relationship("Order", back_populates="payment")