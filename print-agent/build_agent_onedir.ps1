# PrintFlow print-agent: build the NSSM-based shop-owner package.
#
# Produces one folder containing:
#   PrintFlowAgentCore.exe  <- agent.py frozen as a plain program (no
#                              Windows-service code needed at all -- NSSM
#                              handles that part)
#   Setup PrintFlow.exe     <- the ONLY file the shop owner ever double-clicks
#   nssm.exe                <- bundled; the tool that actually registers
#                              PrintFlowAgentCore.exe as a background service
#
# NOTE: this replaces the earlier agent_service.py / pywin32 approach,
# which was confirmed on real hardware to hang under the real Windows
# Service Control Manager with no discoverable root cause after
# ruling out config, DLL registration/bundling, hidden imports, and
# argument-order issues. NSSM installed and started successfully on the
# first real attempt and is now the supported path.
#
# Run from an ELEVATED (Run as Administrator) PowerShell terminal.

$ErrorActionPreference = "Stop"
$ProjectDir = "print-agent"     # adjust if your folder name differs
$FinalDir   = "dist\PrintFlowAgentCore"
$NssmUrl    = "https://nssm.cc/release/nssm-2.24.zip"

Set-Location $ProjectDir

Write-Host "=== 1. Clean previous build artifacts ===" -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist, "*.spec" -ErrorAction SilentlyContinue

Write-Host "=== 2. Build PrintFlowAgentCore.exe from agent.py (--onedir) ===" -ForegroundColor Cyan
# No Windows-service code involved here at all -- this is just agent.py
# frozen as an ordinary standalone program. NSSM will be the one telling
# Windows to treat it as a service.
pyinstaller `
    --onedir `
    --name PrintFlowAgentCore `
    agent.py

Write-Host "=== 3. Build 'Setup PrintFlow.exe' from setup_main.py (--onedir) ===" -ForegroundColor Cyan
# --uac-admin: shows the normal Windows elevation prompt automatically on
# double-click, since registering a service needs admin rights and a shop
# owner won't know to right-click -> Run as Administrator otherwise.
pyinstaller `
    --onedir `
    --name "Setup PrintFlow" `
    --uac-admin `
    setup_main.py

Write-Host "=== 4. Download NSSM if not already cached locally ===" -ForegroundColor Cyan
$nssmCacheDir = "$env:TEMP\nssm_cache"
if (-not (Test-Path "$nssmCacheDir\nssm-2.24\win64\nssm.exe")) {
    New-Item -ItemType Directory -Path $nssmCacheDir -Force | Out-Null
    Invoke-WebRequest -Uri $NssmUrl -OutFile "$nssmCacheDir\nssm.zip"
    Expand-Archive -Path "$nssmCacheDir\nssm.zip" -DestinationPath $nssmCacheDir -Force
}

Write-Host "=== 5. Merge everything into one folder ===" -ForegroundColor Cyan
Copy-Item -Path "dist\Setup PrintFlow\*" -Destination $FinalDir -Recurse -Force
Copy-Item -Path "$nssmCacheDir\nssm-2.24\win64\nssm.exe" -Destination $FinalDir -Force

$required = @("PrintFlowAgentCore.exe", "Setup PrintFlow.exe", "nssm.exe")
foreach ($f in $required) {
    if (-not (Test-Path "$FinalDir\$f")) {
        Write-Error "Merge failed -- $f is missing from $FinalDir. Check the build output above."
        exit 1
    }
}

Write-Host ""
Write-Host "=== Build complete ===" -ForegroundColor Green
Write-Host "Folder to zip and hand to a shop owner: $FinalDir"
Write-Host "Their only instruction: double-click 'Setup PrintFlow.exe', paste the"
Write-Host "API key from their dashboard, press Enter."
Write-Host ""

Write-Host "=== Optional: smoke-test the service yourself right now ===" -ForegroundColor Cyan
$doTest = Read-Host "Run install/start smoke test now, bypassing the wizard's prompts? (y/n)"
if ($doTest -eq "y") {
    if (-not (Test-Path "$FinalDir\config.json")) {
        @{
            api_base = "https://printflow-cfg0.onrender.com"
            api_key = "test-key-for-smoke-test"
            sumatra_path = "C:\PlaceholderPath\SumatraPDF.exe"
            heartbeat_interval_seconds = 20
            poll_interval_seconds = 5
        } | ConvertTo-Json | Set-Content "$FinalDir\config.json"
        Write-Host "Wrote a placeholder config.json for this test run."
    }

    $nssm = "$FinalDir\nssm.exe"
    & $nssm stop PrintFlowAgent 2>$null | Out-Null
    & $nssm remove PrintFlowAgent confirm 2>$null | Out-Null

    & $nssm install PrintFlowAgent "$FinalDir\PrintFlowAgentCore.exe"
    & $nssm set PrintFlowAgent AppDirectory $FinalDir
    & $nssm set PrintFlowAgent Start SERVICE_AUTO_START
    & $nssm start PrintFlowAgent
    Start-Sleep -Seconds 3

    # sc.exe (typed explicitly -- PowerShell aliases `sc` to Set-Content)
    # is the authoritative check; nssm's own messages can be misleading.
    sc.exe query PrintFlowAgent

    Write-Host ""
    Write-Host "Confirm STATE reads RUNNING above, then reboot this machine and"
    Write-Host "re-run 'sc.exe query PrintFlowAgent' to confirm it auto-starts."
}