#!/usr/bin/env python3
"""
demo-repo CLI

A minimal command-line tool with three subcommands:
- start
- stop
- status

Cross-file expectations for audits:
- README should document all three commands (start, stop, status).
- requirements.txt must include both requests and pyyaml if yaml is imported.
- env.example.txt should provide API_KEY= placeholder.
- gitignore.txt should include __pycache__/.
"""

import argparse
import os
import sys

# Imported to drive cross-file checks (dependencies vs imports)
import requests  # noqa: F401
import yaml      # noqa: F401


def load_demo_yaml():
    """Demonstrate YAML usage so the import is real."""
    doc = """
    service:
      name: demo
      enabled: true
    """
    try:
        cfg = yaml.safe_load(doc)
        return cfg
    except Exception as e:
        print(f"YAML parse error: {e}", file=sys.stderr)
        return {}


def start_service(args):
    api_key = os.getenv("API_KEY")
    cfg = load_demo_yaml()
    service_name = cfg.get("service", {}).get("name", "unknown")
    if not api_key:
        print("Warning: API_KEY not set; proceeding in demo mode.")
    print(f"Starting service '{service_name}'...")
    print("Service started.")


def stop_service(args):
    cfg = load_demo_yaml()
    service_name = cfg.get("service", {}).get("name", "unknown")
    print(f"Stopping service '{service_name}'...")
    print("Service stopped.")


def status_service(args):
    cfg = load_demo_yaml()
    service_name = cfg.get("service", {}).get("name", "unknown")
    # For demo purposes, we don't persist state; just print a static status.
    print(f"Service '{service_name}' status: unknown (demo).")


def build_parser():
    parser = argparse.ArgumentParser(
        description="demo-repo CLI — start, stop, and check status of a demo service"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="Start the demo service")
    p_start.set_defaults(func=start_service)

    p_stop = sub.add_parser("stop", help="Stop the demo service")
    p_stop.set_defaults(func=stop_service)

    p_status = sub.add_parser("status", help="Show service status")
    p_status.set_defaults(func=status_service)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())