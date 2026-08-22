from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models import Printer, PrinterStatus, Order, OrderStatus

# If an agent hasn't sent a heartbeat in this long, treat its printers as offline
# even if their stored status still says "online".
STALE_HEARTBEAT_SECONDS = 90


def find_free_printer(db: Session, shop_id: str, color_mode: str, duplex: bool, paper_size: str):
    """
    Pick the first printer that:
      - belongs to this shop
      - is online and recently seen (agent heartbeat is fresh)
      - is not currently mid-job (no order assigned to it with status QUEUED/PRINTING)
      - supports the requested capabilities
    Returns the Printer row, or None if nothing is free/capable right now.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=STALE_HEARTBEAT_SECONDS)

    candidates = (
        db.query(Printer)
        .filter(
            Printer.shop_id == shop_id,
            Printer.status == PrinterStatus.ONLINE,
            Printer.last_seen.isnot(None),
            Printer.last_seen >= cutoff,
            Printer.max_paper_size == paper_size,
        )
        .all()
    )

    if color_mode == "color":
        candidates = [p for p in candidates if p.supports_color]
    if duplex:
        candidates = [p for p in candidates if p.supports_duplex]

    busy_printer_ids = {
        o.printer_id
        for o in db.query(Order)
        .filter(Order.shop_id == shop_id, Order.status.in_([OrderStatus.QUEUED, OrderStatus.PRINTING]))
        .all()
        if o.printer_id
    }

    for printer in candidates:
        if printer.id not in busy_printer_ids:
            return printer
    return None
