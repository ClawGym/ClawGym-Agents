from pathlib import Path
import json
import time

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "config.json"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def sync_with_partner(simulate_down: bool = False):
    """
    Simulates a call to a partner API. If simulate_down is True, it will wait
    for dependency_timeout_ms per retry and eventually raise RuntimeError after
    max_retries attempts.
    """
    cfg = load_config()
    timeout_ms = int(cfg["timeouts"]["dependency_timeout_ms"])  # per attempt
    retries = int(cfg["timeouts"]["max_retries"])              # number of attempts

    if not simulate_down:
        return "ok"

    # Simulate an outage: each attempt waits the timeout, then fails.
    for _ in range(retries):
        time.sleep(timeout_ms / 1000.0)
    raise RuntimeError("partner API unavailable after retries")


if __name__ == "__main__":
    # Simple manual check
    try:
        sync_with_partner(simulate_down=True)
    except RuntimeError as e:
        print(str(e))
