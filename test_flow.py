"""
Simulates the entire lifecycle: shop signup -> agent registers a printer ->
customer scans QR -> uploads -> configures -> quote -> pay -> auto-assign ->
agent polls the job -> agent reports done.
"""
import requests

BASE = "http://127.0.0.1:8000"


def check(label, resp, expect=200):
    ok = resp.status_code == expect
    print(f"{'OK ' if ok else 'FAIL'} {label} [{resp.status_code}]")
    if not ok:
        print("   ", resp.text)
    return resp.json() if ok else None


# 1. Shop owner signs up
r = check("shop signup", requests.post(f"{BASE}/api/shops/signup", json={
    "name": "Sharma Xerox & Printing",
    "slug": "sharma-xerox",
    "owner_email": "owner@sharmaxerox.example.com",
    "owner_password": "Sup3rSecret!",
}))

r = check("shop login", requests.post(f"{BASE}/api/shops/login", json={
    "owner_email": "owner@sharmaxerox.example.com",
    "owner_password": "Sup3rSecret!",
}))
token = r["access_token"]
auth = {"Authorization": f"Bearer {token}"}

# 2. Shop owner sets pricing (BW A4 and Color A4)
check("pricing bw", requests.post(f"{BASE}/api/pricing", headers=auth, json={
    "paper_size": "A4", "color_mode": "bw", "price_per_page": 2.0, "duplex_discount_pct": 10, "binding_price": 20
}))
check("pricing color", requests.post(f"{BASE}/api/pricing", headers=auth, json={
    "paper_size": "A4", "color_mode": "color", "price_per_page": 8.0, "binding_price": 20
}))

# 3. Shop owner registers a print agent, gets an API key for the shop PC
r = check("create agent", requests.post(f"{BASE}/api/agents", headers=auth, params={"name": "Front Desk PC"}))
agent_key = r["api_key"]
agent_headers = {"X-API-Key": agent_key}

# 4. The agent app (running on the shop PC) sends a heartbeat reporting its printers
check("agent heartbeat", requests.post(f"{BASE}/api/agent/heartbeat", headers=agent_headers, json={
    "printers": [{
        "name": "HP LaserJet - Counter 1",
        "os_printer_name": "HP_LaserJet_M126",
        "supports_color": False,
        "supports_duplex": True,
        "max_paper_size": "A4",
    }]
}))

# 5. Customer scans the QR -> lands on the shop's public page
r = check("public shop info", requests.get(f"{BASE}/api/public/shops/sharma-xerox"))

# 6. Customer uploads a PDF
with open("sample.pdf", "rb") as f:
    r = check("create order (upload)", requests.post(
        f"{BASE}/api/public/shops/sharma-xerox/orders",
        files={"file": ("resume.pdf", f, "application/pdf")},
        data={"customer_phone": "9999999999"},
    ))
order_id = r["id"]
print("   pages detected:", r["page_count"])

# 7. Customer sets print options (the "edit" screen)
r = check("update options", requests.patch(f"{BASE}/api/public/orders/{order_id}/options", json={
    "color_mode": "bw", "duplex": True, "copies": 2, "paper_size": "A4", "binding": False
}))

# 8. Customer sees total price
r = check("get quote", requests.get(f"{BASE}/api/public/orders/{order_id}/quote"))
print("   quoted amount:", r["amount"])

# 9. Customer pays
r = check("init payment", requests.post(f"{BASE}/api/public/payments/{order_id}/init"))
gw_ref = r["gateway_order_ref"]
razorpay_configured = bool(r.get("razorpay_key_id"))

if razorpay_configured:
    # Real Razorpay keys are set on the backend, so it correctly REQUIRES a
    # signed payment from an actual checkout -- this script can't fake that
    # from the command line (that's the whole point of the security check).
    # Everything up to here (signup, pricing, upload, quote, payment-init)
    # is still fully proven. Test the actual payment step through the
    # browser with Razorpay's test card instead: 4111 1111 1111 1111.
    print("SKIP payment verification — real Razorpay keys are configured,")
    print("     so a signed payment is required. Test this step manually")
    print("     through the customer app in your browser instead.")
    print("\nBackend verified up through payment-init. Full loop complete")
    print("(remaining steps require a real browser-based Razorpay payment).")
    raise SystemExit(0)

r = check("verify payment", requests.post(f"{BASE}/api/public/payments/{order_id}/verify", json={
    "order_id": order_id, "gateway_payment_ref": f"pay_{gw_ref}"
}))
print("   order status after payment:", r["status"], "| printer_id:", r["printer_id"])

# 10. The print agent polls for jobs and finds this one queued
r = check("agent polls jobs", requests.get(f"{BASE}/api/agent/jobs", headers=agent_headers))
print("   jobs for agent:", r)

# 11. Agent reports it started, then finished, printing
check("agent: job -> printing", requests.post(
    f"{BASE}/api/agent/jobs/{order_id}/status", headers=agent_headers, json={"status": "printing"}
))
check("agent: job -> done", requests.post(
    f"{BASE}/api/agent/jobs/{order_id}/status", headers=agent_headers, json={"status": "done"}
))

r = check("final order state", requests.get(f"{BASE}/api/public/orders/{order_id}"))
print("   final status:", r["status"])

print("\nFull loop complete.")
