"""
"Setup PrintFlow.exe" -- the ONLY file a shop owner ever double-clicks.

Collects the API key and SumatraPDF location, writes config.json, then
registers PrintFlowAgentCore.exe as a background service via the bundled
nssm.exe. All the real logic lives in setup_wizard.py -- this file just
gives it a clean, dedicated double-clickable entry point, separate from
PrintFlowAgentCore.exe itself so there's never any ambiguity between
"a human double-clicked this" and "the service was launched normally."
"""
from setup_wizard import run_setup_wizard


def main():
    if run_setup_wizard():
        print()
        print("All set. PrintFlow is now running in the background and will")
        print("start automatically every time this PC turns on.")
        print("You should see this PC's printers appear in your dashboard shortly.")
    else:
        print()
        print("Setup did not complete successfully -- see the messages above.")
    input("Press Enter to close this window.")


if __name__ == "__main__":
    main()