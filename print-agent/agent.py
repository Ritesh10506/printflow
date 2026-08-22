"""
PrintFlow Print Agent
======================
Runs on the PC connected to your printers. It:
  1. Reports which printers are installed on this PC (heartbeat)
  2. Polls the backend for jobs assigned to this shop
  3. Downloads the PDF and sends it to the right printer with the right settings
  4. Reports back: printing -> done / failed

Requirements on this Windows PC:
  - Python 3.10+ installed
  - pip install -r .env   (pywin32, requests)
  - SumatraPDF (portable) downloaded -- this is what actually talks to the
    printer with duplex/color/copies control. Free, no install needed:
    https://www.sumatrapdfreader.org/download-free-pdf-viewer
    Download the 64-bit portable .exe and note its path for config.json.

Setup:
  1. Copy config.example.json to config.json
  2. Fill in api_key (from the shop dashboard's "Print Agents" tab)
     and sumatra_path (where you saved SumatraPDF.exe)
  3. Run: python agent.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import requests

try:
    import win32print
except ImportError:
    win32print = None  # allows the script to at least start on non-Windows for review/testing

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        print(f"ERROR: config.json not found at {CONFIG_PATH}")
        print("Copy config.example.json to config.json and fill in your details.")
        sys.exit(1)
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


CONFIG = load_config()
API_BASE = CONFIG["api_base"].rstrip("/")
API_KEY = CONFIG["api_key"]
SUMATRA_PATH = CONFIG["sumatra_path"]
HEARTBEAT_INTERVAL = CONFIG.get("heartbeat_interval_seconds", 20)
POLL_INTERVAL = CONFIG.get("poll_interval_seconds", 5)

HEADERS = {"X-API-Key": API_KEY}


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ---------------------------------------------------------------------------
# Printer discovery
# ---------------------------------------------------------------------------
def list_local_printers():
    """
    Returns printers installed on this Windows PC. Capability detection
    (color/duplex support) is approximated as True/True for MVP simplicity --
    Windows' DeviceCapabilities API can report this more precisely per model,
    but printer drivers report it inconsistently enough that starting with
    "assume capable, let the shop owner correct it" is the safer default.
    """
    if win32print is None:
        log("WARNING: pywin32 not installed -- cannot detect real printers. "
            "Run: pip install pywin32")
        return []

    printers = []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    for _, _, name, _ in win32print.EnumPrinters(flags):
        printers.append({
            "name": name,
            "os_printer_name": name,
            "supports_color": True,
            "supports_duplex": True,
            "max_paper_size": "A4",
        })
    return printers


# ---------------------------------------------------------------------------
# Backend calls
# ---------------------------------------------------------------------------
def send_heartbeat():
    printers = list_local_printers()
    try:
        resp = requests.post(
            f"{API_BASE}/api/agent/heartbeat",
            headers=HEADERS,
            json={"printers": printers},
            timeout=10,
        )
        resp.raise_for_status()
        log(f"Heartbeat OK — reporting {len(printers)} printer(s): "
            f"{', '.join(p['name'] for p in printers) or '(none found)'}")
    except requests.RequestException as e:
        log(f"Heartbeat failed: {e}")


def poll_jobs():
    try:
        resp = requests.get(f"{API_BASE}/api/agent/jobs", headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log(f"Poll failed: {e}")
        return []


def report_status(order_id, status, failure_reason=None):
    try:
        requests.post(
            f"{API_BASE}/api/agent/jobs/{order_id}/status",
            headers=HEADERS,
            json={"status": status, "failure_reason": failure_reason},
            timeout=10,
        )
    except requests.RequestException as e:
        log(f"Failed to report status '{status}' for {order_id}: {e}")


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------
def download_file(file_url, dest_path):
    url = file_url if file_url.startswith("http") else f"{API_BASE}{file_url}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)


def build_print_settings(job):
    settings = ["duplex" if job["duplex"] else "simplex"]
    settings.append("color" if job["color_mode"] == "color" else "monochrome")
    if job.get("page_range"):
        settings.append(job["page_range"])
    copies = max(1, job.get("copies", 1))
    settings.append(f"{copies}x")
    return ",".join(settings)


def print_job(job):
    order_id = job["order_id"]
    tmp_dir = tempfile.gettempdir()
    file_path = os.path.join(tmp_dir, f"printflow_{order_id}.pdf")

    try:
        log(f"Job {order_id}: downloading file…")
        download_file(job["file_url"], file_path)

        printer_name = job["printer_os_name"]
        settings = build_print_settings(job)
        log(f"Job {order_id}: sending to '{printer_name}' with settings [{settings}]")

        report_status(order_id, "printing")

        cmd = [
            SUMATRA_PATH,
            "-print-to", printer_name,
            "-print-settings", settings,
            "-silent",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "SumatraPDF exited with a non-zero status")
        log(f"Job {order_id}: sent to printer successfully.")
        report_status(order_id, "done")
    except Exception as e:
        # Anything going wrong here -- a missing file, a bad printer name,
        # SumatraPDF failing -- gets reported as "failed" so the order isn't
        # retried forever and the customer/shop owner sees it stalled out.
        log(f"Job {order_id}: FAILED — {e}")
        report_status(order_id, "failed", failure_reason=str(e))
    finally:
        try:
            os.remove(file_path)
        except OSError:
            pass

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    log("PrintFlow Agent starting…")
    log(f"Backend: {API_BASE}")
    if not os.path.exists(SUMATRA_PATH):
        log(f"WARNING: SumatraPDF not found at '{SUMATRA_PATH}'. "
            "Printing will fail until this path is correct in config.json.")

    last_heartbeat = 0
    while True:
        try:
            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                send_heartbeat()
                last_heartbeat = now

            jobs = poll_jobs()
            for job in jobs:
                print_job(job)

        except Exception:
            log("Unexpected error in main loop:")
            traceback.print_exc()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped by user.")