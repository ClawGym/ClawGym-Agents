import os, sys

mode = os.getenv("SCREENING_MODE")
if not mode:
    raise SystemExit("Environment variable SCREENING_MODE is required")

allowed = {"theatrical", "hybrid", "streaming"}
if mode not in allowed:
    raise SystemExit(f"Invalid SCREENING_MODE: {mode}. Allowed: theatrical, hybrid, streaming")

port = int(os.getenv("APP_PORT", "5000"))
print(f"Running RSVP service in {mode} mode on port {port}")
# Sample app stub; no server start in this example.
sys.exit(0)
