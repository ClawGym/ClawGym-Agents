import json
import os
import sys

# Ensure repo root on path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from crypto_lib import encrypt, decrypt  # noqa: E402


def main():
    cfg_path = os.path.join(ROOT, "config", "security.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    allowed = cfg.get("allowed_algorithms", [])
    result = {"total": 1, "passed": 0, "failed": 0, "algorithm": None}
    try:
        if not allowed:
            raise AssertionError("allowed_algorithms is empty")
        algo = allowed[0]
        result["algorithm"] = algo
        msg = "hello secure world"
        key = "local-dev-key"
        token = encrypt(algo, key, msg)
        out = decrypt(algo, key, token)
        if out != msg:
            raise AssertionError("Round-trip mismatch")
        result["passed"] = 1
    except Exception as e:
        result["failed"] = 1
        result["error"] = str(e)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
