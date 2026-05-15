#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys


def analyze(path: str):
    if not os.path.exists(path):
        return {"compose_path": path, "error": f"file not found: {path}", "status": "fail"}
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    has_screening_mode = bool(re.search(r"\bSCREENING_MODE\b", text))
    app_port_match = re.search(r"APP_PORT\s*=\s*(\d+)", text)
    app_port = app_port_match.group(1) if app_port_match else None
    ports_5000 = bool(re.search(r"['\"]?5000:5000['\"]?", text))
    status = "pass" if (has_screening_mode and app_port == "5000" and ports_5000) else "fail"
    return {
        "compose_path": path,
        "has_SCREENING_MODE": has_screening_mode,
        "app_port": app_port,
        "ports_map_has_5000": ports_5000,
        "status": status,
    }


def main():
    ap = argparse.ArgumentParser(description="Validate docker-compose env and ports for the RSVP service")
    ap.add_argument("compose_path", nargs="?", default="input/docker-compose.yml")
    args = ap.parse_args()
    result = analyze(args.compose_path)
    json.dump(result, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
