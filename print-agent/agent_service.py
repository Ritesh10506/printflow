"""
PrintFlow Print Agent -- Windows Service version
===================================================
This wraps the exact same logic as agent.py, but runs it as a real Windows
Service instead of a terminal window you have to keep open. Once installed:
  - It starts automatically when the PC boots (even before anyone logs in)
  - It runs invisibly in the background -- no window, nothing to accidentally close
  - Windows restarts it automatically if it ever crashes

This is the version to hand to a real shop owner. agent.py (the plain
script) is still useful for your own testing and development.
"""
import time

import servicemanager
import win32event
import win32service
import win32serviceutil

# Reuse every bit of logic from the plain script version -- printer
# discovery, heartbeat, job polling, printing -- nothing is duplicated.
import agent


class PrintFlowAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "PrintFlowAgent"
    _svc_display_name_ = "PrintFlow Print Agent"
    _svc_description_ = (
        "Watches for paid PrintFlow orders and sends them to this PC's "
        "printers automatically. Safe to leave running at all times."
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.running = True

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.running = False
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self.main_loop()

    def main_loop(self):
        last_heartbeat = 0
        while self.running:
            try:
                now = time.time()
                if now - last_heartbeat >= agent.HEARTBEAT_INTERVAL:
                    agent.send_heartbeat()
                    last_heartbeat = now

                jobs = agent.poll_jobs()
                for job in jobs:
                    agent.print_job(job)

            except Exception:
                servicemanager.LogErrorMsg("PrintFlow Agent: unexpected error in main loop")

            rc = win32event.WaitForSingleObject(self.stop_event, agent.POLL_INTERVAL * 1000)
            if rc == win32event.WAIT_OBJECT_0:
                break


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(PrintFlowAgentService)