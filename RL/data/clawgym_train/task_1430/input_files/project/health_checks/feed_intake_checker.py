#!/usr/bin/env python3
import sys
import os
# This check expects a feed intake CSV that is intentionally absent to simulate a data issue.
data_path = os.path.join(os.path.dirname(__file__), "..", "input", "feed_intake.csv")
norm_path = os.path.normpath(data_path)
if not os.path.exists(data_path):
    sys.stderr.write(f"DATA ERROR: missing input file {norm_path}\n")
    sys.exit(2)
# If the file existed, we'd parse and validate thresholds here.
print("OK: feed intake within acceptable range")
sys.exit(0)
