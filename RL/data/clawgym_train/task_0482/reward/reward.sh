#!/usr/bin/env bash
set -euo pipefail

python3 /root/.openclaw/workspace/reward/check.py /root/.openclaw/workspace | python3 -c 'import json, sys; raw = sys.stdin.read().strip(); data = json.loads(raw); print(sum(float(v) for v in data.values()) / len(data) if isinstance(data, dict) and data else float(data) if isinstance(data, (int, float)) else 0.0)'
