#!/usr/bin/env python3
import argparse

parser = argparse.ArgumentParser(description="Mock diagnostics for streaming readiness")
parser.add_argument("--profile", choices=["1080p60", "720p60"], required=True)
args = parser.parse_args()

if args.profile == "1080p60":
    lines = [
        "[CHECK] Profile: 1080p60",
        "[CHECK] CPU logical cores: 4",
        "[CHECK] CPU baseline score: 3500",
        "[CHECK] GPU acceleration: available",
        "[CHECK] Video decode h264: supported",
        "[CHECK] Network bandwidth Mbps: 28",
        "[CHECK] Network jitter ms: 18",
        "[WARN] Dropped frames in 60fps test: 7",
        "[ERROR] Render queue underruns: 2",
        "[INFO] End of diagnostics",
    ]
else:  # 720p60
    lines = [
        "[CHECK] Profile: 720p60",
        "[CHECK] CPU logical cores: 4",
        "[CHECK] CPU baseline score: 3500",
        "[CHECK] GPU acceleration: available",
        "[CHECK] Video decode h264: supported",
        "[CHECK] Network bandwidth Mbps: 28",
        "[CHECK] Network jitter ms: 18",
        "[WARN] Dropped frames in 60fps test: 2",
        "[INFO] End of diagnostics",
    ]

for line in lines:
    print(line)
