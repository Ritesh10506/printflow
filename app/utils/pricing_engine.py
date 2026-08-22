"""
Pure pricing calculation -- no DB writes here, just math, so it's easy to
unit test and easy to reuse for both the "show me a quote" endpoint and the
final amount locked in at payment time.
"""
from typing import Optional
from sqlalchemy.orm import Session

from app.models import PricingRule


def count_selected_pages(total_pages: int, page_range: Optional[str]) -> int:
    """Parse a range string like '1-5,8,10-12' against a known total page count."""
    if not page_range or not page_range.strip():
        return total_pages

    selected = set()
    for part in page_range.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-")
            start, end = int(start), int(end)
            for p in range(start, end + 1):
                if 1 <= p <= total_pages:
                    selected.add(p)
        else:
            p = int(part)
            if 1 <= p <= total_pages:
                selected.add(p)
    return len(selected) if selected else total_pages


def calculate_price(
    db: Session,
    shop_id: str,
    total_pages: int,
    color_mode: str,
    duplex: bool,
    copies: int,
    paper_size: str,
    binding: bool,
    page_range: Optional[str],
) -> dict:
    rule = (
        db.query(PricingRule)
        .filter(
            PricingRule.shop_id == shop_id,
            PricingRule.color_mode == color_mode,
            PricingRule.paper_size == paper_size,
        )
        .first()
    )
    if not rule:
        # fall back to any rule for this shop so a quote never hard-fails
        rule = db.query(PricingRule).filter(PricingRule.shop_id == shop_id).first()
    if not rule:
        raise ValueError("This shop has no pricing configured yet")

    pages_to_print = count_selected_pages(total_pages, page_range)

    price_per_page = rule.price_per_page
    if duplex:
        price_per_page = price_per_page * (1 - rule.duplex_discount_pct / 100)

    subtotal = price_per_page * pages_to_print * max(copies, 1)
    binding_cost = rule.binding_price * copies if binding else 0.0
    total = round(subtotal + binding_cost, 2)

    return {
        "amount": total,
        "price_per_page": round(price_per_page, 2),
        "page_count": pages_to_print,
        "copies": copies,
        "breakdown": {
            "subtotal": round(subtotal, 2),
            "binding_cost": round(binding_cost, 2),
            "pages_per_copy": pages_to_print,
        },
    }
