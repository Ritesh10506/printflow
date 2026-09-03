# PrintFlow — Multi-Tenant Print Shop Platform

A complete SaaS platform for print shops: any shop owner signs up, sets
their own pricing and connects their own printers and payment account, and
gets a QR code their customers scan to upload a document, configure it,
pay, and have it auto-assigned to a free printer and printed automatically.

**This is live and deployed, not just a local demo:**

| Piece | Live URL |
|---|---|
| Backend API | https://printflow-cfg0.onrender.com |
| Customer app | https://printflow-customer.vercel.app |
| Shop dashboard | https://printflow-shop.vercel.app |
| API docs | https://printflow-cfg0.onrender.com/docs |

## Run it locally

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn app.main:app --reload
```

Interactive API docs: http://127.0.0.1:8000/docs

Default DB: local SQLite file `printapp.db` (zero config). Set
`DATABASE_URL` to point at Postgres in production — nothing else changes
(the code auto-fixes Render's `postgres://` scheme to `postgresql://`).

Copy `.env.example` to `.env` and fill in a real `JWT_SECRET` — the server
refuses to start without one. `test_flow.py` is a full smoke test that
walks the whole lifecycle (signup → pricing → agent → upload → pay →
auto-assign → print → done) against a running server:
`./venv/bin/python test_flow.py`

## Project layout

```
app/                  FastAPI backend (this is what's deployed to Render)
customer-app/         Customer web app: upload/configure/pay/track (Vercel)
shop-dashboard/       Shop owner dashboard: pricing/printers/agents/orders (Vercel)
print-agent/          The Windows program that runs on a shop's PC and prints
qr-generator.html     Generates a QR code from a shop's customer link
```

## What's here

| Table | Purpose |
|---|---|
| `shops` | One row per printing-shop owner. `slug` is what the QR code encodes. Also stores each shop's own `razorpay_key_id`/`razorpay_key_secret`. |
| `printers` | Physical printers, scoped to a shop, reported by an agent. |
| `print_agents` | The installed app on a shop's PC. Owns an API key. |
| `pricing_rules` | Per-shop price per page by paper size + color mode. |
| `orders` | The core object: upload → options → quote → pay → print → done. |
| `payments` | 1:1 with an order, routed through the owning shop's own Razorpay account. |

**Tenant isolation:** every shop-owner route resolves `shop_id` from the JWT
(`get_current_shop`), never from anything the client sends. Every public
customer route resolves the shop from the `slug` in the URL. Every agent
route resolves `shop_id`/`agent_id` from the API key (`get_current_agent`).
No endpoint accepts a bare `shop_id` in the body — this is what keeps one
shop's customer from ever touching another shop's data or printer.

**Payments:** each shop connects its own Razorpay account from its
dashboard (Payment Settings tab) — customer money goes directly to the shop
owner, the platform never touches it. A shop with no keys configured falls
back to a mock test-mode payment so the rest of the app stays usable while
they're setting up.

## Customer flow (public, no login)

```
GET   /api/public/shops/{slug}                  shop lands after QR scan
POST  /api/public/shops/{slug}/orders            upload file -> order created
PATCH /api/public/orders/{id}/options             set color/duplex/copies/pages
GET   /api/public/orders/{id}/quote               server computes total price
POST  /api/public/payments/{id}/init              creates a real Razorpay order under the shop's own account
POST  /api/public/payments/{id}/verify            verifies signature -> marks paid -> auto-assigns printer
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
GET/POST/DELETE /api/payments/settings   connect/view/disconnect this shop's own Razorpay account
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

Two ways to run the agent — see `print-agent/README.md` for full details:
- `agent.py` — plain script, good for testing, needs a terminal kept open
- `agent_service.py` — installs as a real Windows Service: auto-starts on
  boot, runs invisibly, survives restarts. This is the production version
  to hand to a real shop owner. **Important:** install it with
  `python agent_service.py install --startup auto` — without the
  `--startup auto` flag it defaults to Manual and won't survive a reboot.

## Deployment notes

- **Backend (Render):** free tier spins down after 15 min of inactivity —
  first request after that can take 30-60s to wake up. Fine for testing,
  worth upgrading before handling real unattended customer traffic.
- **Database (Render Postgres, free tier):** free databases expire after 30
  days — upgrade before relying on this for real customer data.
- **Frontends (Vercel):** `customer-app` and `shop-dashboard` are each
  deployed as their own Vercel project with Root Directory set to that
  folder. Their `API_BASE` is hardcoded to the live Render URL (not
  auto-detected from the hostname) since frontend and backend now live on
  different domains.

## Not built yet (next steps)

- **File cleanup / retention** — uploaded files currently sit on disk
  indefinitely. Worth adding auto-delete once an order reaches `done` or
  `failed`, plus a cleanup pass for abandoned/unpaid carts, and restricting
  file access to only the assigned agent's API key instead of any bearer
  of the URL.
- **Real cloud file storage** — uploads currently save to local disk
  (`uploads/`), which doesn't survive Render restarts. Swap
  `save_file_and_get_url()` in `orders.py` for a Cloudinary/S3 call.
- **DOCX→PDF conversion** — non-PDF uploads currently default to 1 page;
  LibreOffice headless plugs in where `count_pdf_pages()` is called.
- **Packaging the agent as a single .exe** — via PyInstaller, so a shop
  owner never needs Python installed at all.
