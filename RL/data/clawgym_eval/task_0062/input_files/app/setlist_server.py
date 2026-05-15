#!/usr/bin/env python3
import argparse
import json
import sys
import time
import http.server
import socketserver

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/settings.json")
    args = parser.parse_args()

    try:
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"ERROR: could not read config {args.config}: {e}", file=sys.stderr)
        sys.exit(2)

    host = cfg.get("host", "127.0.0.1")
    try:
        port = int(cfg.get("port", 8080))
    except Exception:
        print("ERROR: invalid port in config", file=sys.stderr)
        sys.exit(2)

    # Deterministic incident simulation: if port is 8080, pretend the address is in use
    if port == 8080:
        print(f"OSError: [Errno 98] Address already in use: ('{host}', {port})", file=sys.stderr)
        sys.exit(1)

    handler = http.server.SimpleHTTPRequestHandler

    try:
        with socketserver.TCPServer((host, port), handler) as httpd:
            httpd.timeout = 0.2
            print(f"Serving setlist viewer on http://{host}:{port} (will exit after ~1s)")
            sys.stdout.flush()
            start = time.time()
            while time.time() - start < 1.0:
                httpd.handle_request()
            print("Setlist viewer exited cleanly.")
    except OSError as e:
        print(f"OSError while starting server: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
