from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, ConfigDict


# ---------- Shop ----------
class ShopCreate(BaseModel):
    name: str
    slug: str
    owner_email: EmailStr
    owner_password: str


class ShopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    slug: str
    plan: str
    is_active: bool


class ShopLogin(BaseModel):
    owner_email: EmailStr
    owner_password: str


# ---------- Printer ----------
class PrinterCreate(BaseModel):
    name: str
    os_printer_name: str
    supports_color: bool = True
    supports_duplex: bool = True
    max_paper_size: str = "A4"


class PrinterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    status: str
    supports_color: bool
    supports_duplex: bool
    max_paper_size: str
    last_seen: Optional[datetime] = None


# ---------- Pricing ----------
class PricingRuleCreate(BaseModel):
    paper_size: str = "A4"
    color_mode: str = "bw"          # bw | color
    price_per_page: float
    duplex_discount_pct: float = 0.0
    binding_price: float = 0.0


class PricingRuleOut(PricingRuleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


# ---------- Print Agent ----------
class AgentRegisterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    api_key: str
    name: str


class AgentHeartbeatIn(BaseModel):
    printers: list[PrinterCreate] = []   # agent reports what printers it currently sees


# ---------- Order ----------
class OrderOptionsUpdate(BaseModel):
    color_mode: Optional[str] = None
    duplex: Optional[bool] = None
    copies: Optional[int] = None
    paper_size: Optional[str] = None
    binding: Optional[bool] = None
    page_range: Optional[str] = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    shop_id: str
    status: str
    page_count: int
    color_mode: str
    duplex: bool
    copies: int
    paper_size: str
    binding: bool
    page_range: Optional[str]
    amount: float
    file_url: Optional[str]
    original_filename: Optional[str]
    printer_id: Optional[str]
    created_at: datetime


class PriceQuote(BaseModel):
    amount: float
    price_per_page: float
    page_count: int
    copies: int
    breakdown: dict


# ---------- Payment ----------
class PaymentInitOut(BaseModel):
    order_id: str
    amount: float
    gateway: str
    gateway_order_ref: str
    razorpay_key_id: Optional[str] = None


class PaymentVerifyIn(BaseModel):
    order_id: str
    gateway_payment_ref: str
    signature: Optional[str] = None   # for real Razorpay signature verification


# ---------- Print job (agent-facing) ----------
class PrintJobOut(BaseModel):
    order_id: str
    file_url: str
    printer_os_name: str
    color_mode: str
    duplex: bool
    copies: int
    paper_size: str
    page_range: Optional[str]


class JobStatusUpdate(BaseModel):
    status: str          # printing | done | failed
    failure_reason: Optional[str] = None
