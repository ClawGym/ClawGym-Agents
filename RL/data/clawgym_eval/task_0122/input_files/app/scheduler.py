"""
Simple scheduler excerpt for auto-posting.

CONFIG KEYS (expected by this code):
- retries.max_attempts (int)
- network.backoff_seconds (int)
- network.jitter (bool)
- safety.dedup_enabled (bool)
- publisher.id_key_prefix (str)

Defaults are conservative but can cause retries without idempotency if keys are missing:
- max attempts default: 5
- backoff_seconds default: 5
- jitter default: False
- dedup_enabled default: False (no deduplication/idempotency key)
- id_key_prefix default: "" (omit idempotency header)
"""
from typing import Dict, Any
import time


def load_yaml(path: str) -> Dict[str, Any]:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


cfg = load_yaml("config/post_scheduler.yaml")

MAX_ATTEMPTS = int(cfg.get("retries", {}).get("max_attempts", 5))
BACKOFF_SECONDS = int(cfg.get("network", {}).get("backoff_seconds", 5))
JITTER = bool(cfg.get("network", {}).get("jitter", False))
DEDUP_ENABLED = bool(cfg.get("safety", {}).get("dedup_enabled", False))
ID_PREFIX = cfg.get("publisher", {}).get("id_key_prefix", "")


def build_idempotency_key(post_id: str) -> str:
    # Use a stable idempotency key if prefix configured; otherwise return empty string (disabled)
    return f"{ID_PREFIX}{post_id}" if ID_PREFIX else ""


def send_with_retries(post_id: str, payload: Dict[str, Any], send_fn):
    attempt = 0
    while attempt < MAX_ATTEMPTS:
        attempt += 1
        key = build_idempotency_key(post_id) if DEDUP_ENABLED else ""
        try:
            # If key is empty, downstream may treat each retry as a new publish
            resp = send_fn(payload, idempotency_key=key)
            if 200 <= resp.status_code < 300:
                return True
        except TimeoutError:
            pass
        # basic backoff with optional jitter
        delay = BACKOFF_SECONDS
        if JITTER:
            import random
            delay += random.uniform(0, BACKOFF_SECONDS / 2)
        time.sleep(delay)
    return False

# Note: If config keys are misnamed, defaults apply (no dedup, more retries), increasing the chance of duplicates on timeouts.
