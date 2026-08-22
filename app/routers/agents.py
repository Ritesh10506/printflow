from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.utils.auth import get_current_shop, get_current_agent
from app.routers.payments import try_assign_printer

router = APIRouter(tags=["agents"])


# ---- Shop owner creates an agent registration from the dashboard, gets an
#      API key, pastes it into the installer on the shop PC ----
@router.post("/api/agents", response_model=schemas.AgentRegisterOut)
def create_agent(
    name: str = "Print Agent",
    db: Session = Depends(get_db),
    shop: models.Shop = Depends(get_current_shop),
):
    agent = models.PrintAgent(shop_id=shop.id, name=name)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


# ---- Agent app calls this every ~20-30s: "here's what I see, here's who's alive" ----
@router.post("/api/agent/heartbeat")
def heartbeat(
    payload: schemas.AgentHeartbeatIn,
    db: Session = Depends(get_db),
    agent: models.PrintAgent = Depends(get_current_agent),
):
    agent.last_heartbeat = datetime.utcnow()

    seen_names = set()
    for p in payload.printers:
        seen_names.add(p.os_printer_name)
        printer = (
            db.query(models.Printer)
            .filter(models.Printer.shop_id == agent.shop_id, models.Printer.os_printer_name == p.os_printer_name)
            .first()
        )
        if not printer:
            printer = models.Printer(shop_id=agent.shop_id, os_printer_name=p.os_printer_name)
            db.add(printer)
        printer.agent_id = agent.id
        printer.name = p.name
        printer.supports_color = p.supports_color
        printer.supports_duplex = p.supports_duplex
        printer.max_paper_size = p.max_paper_size
        printer.status = models.PrinterStatus.ONLINE
        printer.last_seen = datetime.utcnow()

    # any printer this agent previously reported but didn't include now = gone offline
    stale = (
        db.query(models.Printer)
        .filter(models.Printer.agent_id == agent.id, ~models.Printer.os_printer_name.in_(seen_names))
        .all()
        if seen_names
        else []
    )
    for p in stale:
        p.status = models.PrinterStatus.OFFLINE

    db.commit()

    # a printer just came online -- try to clear any paid-but-unassigned backlog
    backlog = db.query(models.Order).filter(
        models.Order.shop_id == agent.shop_id, models.Order.status == models.OrderStatus.PAID
    ).all()
    for order in backlog:
        try_assign_printer(db, order)

    return {"ok": True}


# ---- Agent polls this to pick up work assigned to its printers ----
@router.get("/api/agent/jobs", response_model=list[schemas.PrintJobOut])
def poll_jobs(
    db: Session = Depends(get_db),
    agent: models.PrintAgent = Depends(get_current_agent),
):
    orders = (
        db.query(models.Order)
        .filter(models.Order.assigned_agent_id == agent.id, models.Order.status == models.OrderStatus.QUEUED)
        .all()
    )
    jobs = []
    for o in orders:
        printer = db.query(models.Printer).filter(models.Printer.id == o.printer_id).first()
        jobs.append(
            schemas.PrintJobOut(
                order_id=o.id,
                file_url=o.file_url,
                printer_os_name=printer.os_printer_name if printer else "",
                color_mode=o.color_mode,
                duplex=o.duplex,
                copies=o.copies,
                paper_size=o.paper_size,
                page_range=o.page_range,
            )
        )
    return jobs


# ---- Agent reports progress/completion/failure for a job it picked up ----
@router.post("/api/agent/jobs/{order_id}/status")
def update_job_status(
    order_id: str,
    payload: schemas.JobStatusUpdate,
    db: Session = Depends(get_db),
    agent: models.PrintAgent = Depends(get_current_agent),
):
    order = (
        db.query(models.Order)
        .filter(models.Order.id == order_id, models.Order.assigned_agent_id == agent.id)
        .first()
    )
    if not order:
        return {"ok": False, "detail": "Job not found for this agent"}

    status_map = {
        "printing": models.OrderStatus.PRINTING,
        "done": models.OrderStatus.DONE,
        "failed": models.OrderStatus.FAILED,
    }
    order.status = status_map.get(payload.status, order.status)
    if payload.status == "done":
        order.completed_at = datetime.utcnow()
    if payload.status == "failed":
        order.failure_reason = payload.failure_reason

    db.commit()
    return {"ok": True}
