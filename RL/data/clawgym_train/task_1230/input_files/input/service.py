import random
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Simulated downstream service base URL
DOWNSTREAM_BASE = "http://inventory-service.local"

# NOTE: This module intentionally has weak error handling and flaky behavior.
# The goal is to refactor it in output/app.py following requirements.md.


def downstream_get_item(item_id):
    """
    Naively fetches an item from the downstream service.
    Simulates flakiness via random timeouts/connection errors.
    """
    # Randomly sleep a bit to simulate network jitter
    if random.random() < 0.2:
        time.sleep(0.8)  # longer than the timeout used below

    # Random transient failure simulations
    if random.random() < 0.1:
        raise requests.exceptions.ConnectTimeout("Simulated connect timeout")
    if random.random() < 0.1:
        raise requests.exceptions.ConnectionError("Simulated connection reset by peer")

    url = f"{DOWNSTREAM_BASE}/items/{item_id}"
    resp = requests.get(url, timeout=0.5)  # very short timeout
    # Naive handling — will raise for 4xx/5xx
    if resp.status_code >= 400:
        # Return downstream body directly (unsafe)
        raise requests.exceptions.HTTPError(f"Downstream returned {resp.status_code}: {resp.text}")
    try:
        return resp.json()
    except Exception as e:
        # Malformed JSON — return raw text
        return {"raw": resp.text, "parse_error": str(e)}


@app.route("/v1/items/<item_id>", methods=["GET"])
def get_item(item_id):
    # Weak validation and error handling
    if not item_id:
        return "missing id", 400

    try:
        data = downstream_get_item(item_id)
        return jsonify({"item": data}), 200
    except requests.exceptions.Timeout as e:
        # Return raw error text from downstream (unsafe)
        return jsonify({"error": str(e)}), 504
    except requests.exceptions.RequestException as e:
        # Propagate downstream message directly (unsafe)
        # Sometimes expose internal messages
        return jsonify({"error": str(e), "type": e.__class__.__name__}), 500
    except Exception as e:
        # Generic catch-all — exposes error details (unsafe)
        print("Unhandled error:", e)  # not structured
        return jsonify({"error": str(e), "type": e.__class__.__name__}), 500


@app.route("/v1/items", methods=["POST"])
def create_item():
    # Minimal validation
    body = request.get_json(silent=True) or {}
    if "id" not in body:
        return "invalid body: 'id' required", 400

    # Simulate flakiness in create path too
    if random.random() < 0.15:
        return "downstream unavailable", 503

    try:
        url = f"{DOWNSTREAM_BASE}/items"
        resp = requests.post(url, json=body, timeout=0.5)
        if resp.status_code >= 400:
            # Return downstream body directly (unsafe)
            return resp.text, resp.status_code
        return resp.json(), 201
    except Exception as e:
        # Catch-all, exposes details
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    # Debug server (no production settings)
    app.run(host="0.0.0.0", port=8080, debug=True)