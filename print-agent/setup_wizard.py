"""
PrintFlow Print Agent -- first-run setup wizard (NSSM-based)
==============================================================
Shop owners are not developers. The only thing anyone at the shop has to
do is:
  1. Copy the API key shown on the dashboard's "Print Agents" tab
  2. Double-click "Setup PrintFlow.exe" once and paste it in when asked

Everything else -- finding or downloading SumatraPDF, writing config.json,
registering the background service -- happens automatically.

WHY NSSM INSTEAD OF A PYTHON WINDOWS-SERVICE CLASS:
An earlier version of this used pywin32's ServiceFramework (agent_service.py)
packaged with PyInstaller --onedir. On real hardware that build started fine
in "debug" mode but consistently hung and timed out when launched for real
by the Windows Service Control Manager, with no crash logged anywhere --
confirmed after ruling out config issues, DLL registration, DLL bundling,
and hidden imports. NSSM sidesteps the problem entirely: it is a small,
widely-used tool that wraps ANY ordinary program as a service without that
program needing to know anything about Windows service internals. It
installed and started successfully on the first real attempt.
"""
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import requests

# The backend URL is fixed -- a shop owner should never need to know or
# type this, unlike api_key which is unique per shop.
DEFAULT_API_BASE = "https://printflow-cfg0.onrender.com"

SUMATRA_DOWNLOAD_URL = (
    "https://www.sumatrapdfreader.org/dl/rel/3.5.2/SumatraPDF-3.5.2-64.zip"
)

SERVICE_NAME = "PrintFlowAgent"

# Everything -- the frozen agent, nssm.exe, this wizard's own exe, and
# config.json once written -- ships flat, side by side, in one folder.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "config.json"
AGENT_EXE = BASE_DIR / "PrintFlowAgentCore.exe"
NSSM_EXE = BASE_DIR / "nssm.exe"


def find_existing_sumatra():
    """Check the usual install spots before asking the owner anything."""
    already_downloaded = list(BASE_DIR.glob("SumatraPDF*.exe"))
    if already_downloaded:
        return str(already_downloaded[0])

    candidates = [
        Path(r"C:\Program Files\SumatraPDF\SumatraPDF.exe"),
        Path(r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe"),
        Path.home() / "AppData" / "Local" / "SumatraPDF" / "SumatraPDF.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def download_sumatra():
    """No SumatraPDF found -- fetch the portable build next to this exe."""
    print("SumatraPDF not found on this PC -- downloading it now (one-time, ~10MB)...")
    resp = requests.get(SUMATRA_DOWNLOAD_URL, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(BASE_DIR)

    # The portable zip's exe is named with its version baked in (e.g.
    # SumatraPDF-3.5.2-64.exe), not a plain "SumatraPDF.exe" -- confirmed
    # by testing the real download. Find whatever .exe actually landed
    # here and use it directly rather than assuming a fixed name.
    candidates = list(BASE_DIR.glob("SumatraPDF*.exe"))
    if not candidates:
        raise RuntimeError("Download finished but no SumatraPDF*.exe was found afterward.")
    exe_path = candidates[0]
    print(f"Done -- installed at {exe_path}")
    return str(exe_path)


def collect_settings():
    """Asks the owner for their API key, resolves SumatraPDF, writes config.json."""
    print("=" * 60)
    print("PrintFlow Print Agent -- first-time setup")
    print("=" * 60)
    print()
    print("You'll need the API key from your PrintFlow dashboard:")
    print("  Dashboard -> 'Print Agents' tab -> Create Agent")
    print()

    api_key = input("Paste your Print Agent API key here, then press Enter: ").strip()
    while not api_key:
        api_key = input("That looked empty -- please paste the key: ").strip()

    sumatra_path = find_existing_sumatra()
    if sumatra_path:
        print(f"Found SumatraPDF already on this PC at: {sumatra_path}")
    else:
        try:
            sumatra_path = download_sumatra()
        except Exception as e:
            print(f"Could not auto-download SumatraPDF ({e}).")
            sumatra_path = input(
                "Install it from sumatrapdfreader.org and paste its .exe path here: "
            ).strip()

    config = {
        "api_base": DEFAULT_API_BASE,
        "api_key": api_key,
        "sumatra_path": sumatra_path,
        "heartbeat_interval_seconds": 20,
        "poll_interval_seconds": 5,
    }
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nSaved settings to {CONFIG_PATH}")
    return True


def install_service_with_nssm():
    """
    Registers PrintFlowAgentCore.exe as a Windows service via NSSM, exactly
    the same commands proven to work manually:
      nssm install <name> <exe>
      nssm set <name> AppDirectory <folder>
      nssm set <name> Start SERVICE_AUTO_START
      nssm start <name>
    """
    if not NSSM_EXE.exists():
        print(f"ERROR: nssm.exe not found at {NSSM_EXE}.")
        print("Setup PrintFlow.exe, PrintFlowAgentCore.exe, and nssm.exe must all be in the same folder.")
        return False

    if not AGENT_EXE.exists():
        print(f"ERROR: {AGENT_EXE} not found.")
        print("Setup PrintFlow.exe, PrintFlowAgentCore.exe, and nssm.exe must all be in the same folder.")
        return False

    def run_nssm(*args):
        result = subprocess.run(
            [str(NSSM_EXE), *args], capture_output=True
        )
        # nssm.exe prints its status messages as UTF-16LE on Windows;
        # decoding as UTF-8 (subprocess's default with text=True) leaves a
        # stray space between every letter. Confirmed by testing the real
        # output: decode as utf-16-le explicitly instead.
        raw = (result.stdout or b"") + (result.stderr or b"")
        try:
            output = raw.decode("utf-16-le")
        except UnicodeDecodeError:
            output = raw.decode("utf-8", errors="replace")
        print(output.strip())
        return result.returncode == 0

    print("\nInstalling background service...")
    # A previous install (e.g. a re-run of setup) needs removing first, or
    # nssm install will fail complaining the service already exists.
    subprocess.run([str(NSSM_EXE), "stop", SERVICE_NAME], capture_output=True)
    subprocess.run([str(NSSM_EXE), "remove", SERVICE_NAME, "confirm"], capture_output=True)

    if not run_nssm("install", SERVICE_NAME, str(AGENT_EXE)):
        return False
    run_nssm("set", SERVICE_NAME, "AppDirectory", str(BASE_DIR))
    run_nssm("set", SERVICE_NAME, "Start", "SERVICE_AUTO_START")

    print("Starting it now...")
    if not run_nssm("start", SERVICE_NAME):
        return False

    return True


def run_setup_wizard():
    """Full flow: collect settings, then install + start the service."""
    if not collect_settings():
        return False
    return install_service_with_nssm()