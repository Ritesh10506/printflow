# PrintFlow API — Backend Schema + APIs

Multi-tenant backend for the print-shop app: any shop owner signs up, sets their
own pricing and printers, and gets a QR/link their customers scan to upload,
configure, pay, and get auto-assigned to a free printer.

## Run it

```bash
python3 -m venv venv
./venv/bin/pip install -r .env
./venv/bin/uvicorn app.main:app --reload
```

Interactive API docs: http://127.0.0.1:8000/docs
Default DB: local SQLite file `printapp.db` (zero config). Set `DATABASE_URL`
env var to point at MySQL in production — nothing else changes.

`test_flow.py` is a full smoke test that walks the entire lifecycle
(signup → pricing → agent → upload → pay → auto-assign → print → done).
Run it against a live server: `./venv/bin/python test_flow.py`

## What's here

| Table | Purpose |
|---|---|
| `shops` | One row per printing-shop owner. `slug` is what the QR code encodes. |
| `printers` | Physical printers, scoped to a shop, reported by an agent. |
| `print_agents` | The installed app on a shop's PC. Owns an API key. |
| `pricing_rules` | Per-shop price per page by paper size + color mode. |
| `orders` | The core object: upload → options → quote → pay → print → done. |
| `payments` | 1:1 with an order, gateway-agnostic (stubbed for Razorpay). |

**Tenant isolation:** every shop-owner route resolves `shop_id` from the JWT
(`get_current_shop`), never from anything the client sends. Every public
customer route resolves the shop from the `slug` in the URL. Every agent
route resolves `shop_id`/`agent_id` from the API key (`get_current_agent`).
No endpoint accepts a bare `shop_id` in the body — this is what keeps one
shop's customer from ever touching another shop's data or printer.

## Customer flow (public, no login)

```
GET   /api/public/shops/{slug}                  shop lands after QR scan
POST  /api/public/shops/{slug}/orders            upload file -> order created
PATCH /api/public/orders/{id}/options             set color/duplex/copies/pages
GET   /api/public/orders/{id}/quote               server computes total price
POST  /api/public/payments/{id}/init              start payment
POST  /api/public/payments/{id}/verify            confirm payment -> auto-assign printer
GET   /api/public/orders/{id}                     poll status (queued/printing/done)
```

## Shop-owner dashboard (JWT auth: `Authorization: Bearer <token>`)

```
POST  /api/shops/signup | /api/shops/login
GET   /api/shops/me
GET   /api/printers                 DELETE /api/printers/{id}
GET/POST /api/pricing               DELETE /api/pricing/{id}
GET   /api/orders                   all orders for this shop
POST  /api/agents                   register a new print agent, returns its API key
```

## Print agent (API key auth: `X-API-Key: <key>`)

This is the piece that runs on the shop's PC and actually reaches the
printer. It:

```
POST  /api/agent/heartbeat          reports which printers are online + capabilities
GET   /api/agent/jobs               polls for jobs queued to this agent's printers
POST  /api/agent/jobs/{id}/status   reports printing / done / failed
```

Printer auto-assignment (`app/utils/assignment.py`) picks the first online,
capability-matching, not-currently-busy printer for the shop the moment
payment clears — or, if none is free yet, the next agent heartbeat retries
the backlog.

## Not built yet (next steps)

- **Print agent itself** — this backend exposes the API it needs; the actual
  Windows service (PyInstaller + win32print/SumatraPDF) is a separate piece.
- **Real file storage** — uploads currently save to local disk (`/uploads`);
  swap `save_file_and_get_url()` in `orders.py` for a Cloudinary call.
- **Real payment gateway** — `payments.py` has clearly marked `TODO`s for
  the actual Razorpay order-create call and signature verification.
- **DOCX→PDF conversion** — non-PDF uploads currently default to 1 page;
  LibreOffice headless plugs in where `count_pdf_pages()` is called.
- Customer web app and shop-owner dashboard UIs (this is API-only).
