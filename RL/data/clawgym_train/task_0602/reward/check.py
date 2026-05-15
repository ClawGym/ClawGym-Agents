import json
import os
import sys
import re
from typing import Any, Dict, Tuple, Optional

def load_json_file(path: str) -> Tuple[bool, Optional[Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def is_non_empty_string(v: Any) -> bool:
    return isinstance(v, str) and len(v.strip()) > 0

def main() -> None:
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir is not used for checking but may be useful for future
    # reward_dir = os.path.join(workspace_root, "reward")

    listing_out_path = os.path.join(output_dir, "listing.json")
    order_out_path = os.path.join(output_dir, "order.json")
    log_out_path = os.path.join(output_dir, "log.md")

    listing_spec_path = os.path.join(input_dir, "listing_spec.json")
    order_req_path = os.path.join(input_dir, "order_request.json")

    checks: Dict[str, bool] = {}

    applicable_keys = []

    # Always attempt to load inputs (reference only; do not contribute positive reward by themselves)
    listing_spec_ok, listing_spec = load_json_file(listing_spec_path)
    order_req_ok, order_req = load_json_file(order_req_path)

    # 1) listing.json checks
    key = "listing_json_exists"
    checks[key] = os.path.isfile(listing_out_path)
    applicable_keys.append(key)

    listing_json_ok = False
    listing_data: Dict[str, Any] = {}
    key = "listing_json_valid"
    if checks["listing_json_exists"]:
        ok, data = load_json_file(listing_out_path)
        listing_json_ok = ok and isinstance(data, dict)
        if listing_json_ok:
            listing_data = data  # type: ignore[assignment]
        checks[key] = listing_json_ok
    else:
        checks[key] = False
    applicable_keys.append(key)

    key = "listing_has_required_top_level_keys"
    checks[key] = False
    if listing_json_ok:
        has_service = isinstance(listing_data.get("service"), dict)
        service_id_top = listing_data.get("service_id")
        has_service_id = is_non_empty_string(service_id_top)
        checks[key] = has_service and has_service_id
    applicable_keys.append(key)

    key = "listing_service_id_non_empty"
    checks[key] = False
    if listing_json_ok:
        checks[key] = is_non_empty_string(listing_data.get("service_id"))
    applicable_keys.append(key)

    key = "listing_service_service_id_matches_top"
    checks[key] = False
    if listing_json_ok:
        svc = listing_data.get("service")
        top_id = listing_data.get("service_id")
        if isinstance(svc, dict) and is_non_empty_string(top_id):
            checks[key] = svc.get("service_id") == top_id
    applicable_keys.append(key)

    key = "listing_supplier_wallet_matches_input"
    checks[key] = False
    if listing_json_ok and listing_spec_ok and isinstance(listing_spec, dict):
        svc = listing_data.get("service")
        if isinstance(svc, dict):
            out_wallet = svc.get("supplier_wallet")
            in_wallet = listing_spec.get("supplier_wallet")
            if is_non_empty_string(out_wallet) and is_non_empty_string(in_wallet):
                checks[key] = (out_wallet == in_wallet)
    applicable_keys.append(key)

    # Conditional: If input sets is_active true, require service.is_active true
    if listing_spec_ok and isinstance(listing_spec, dict) and listing_spec.get("is_active") is True:
        key = "listing_active_true_when_requested"
        checks[key] = False
        if listing_json_ok:
            svc = listing_data.get("service")
            if isinstance(svc, dict):
                checks[key] = (svc.get("is_active") is True)
        applicable_keys.append(key)

    # 2) order.json checks
    key = "order_json_exists"
    checks[key] = os.path.isfile(order_out_path)
    applicable_keys.append(key)

    order_json_ok = False
    order_data: Dict[str, Any] = {}
    key = "order_json_valid"
    if checks["order_json_exists"]:
        ok, data = load_json_file(order_out_path)
        order_json_ok = ok and isinstance(data, dict)
        if order_json_ok:
            order_data = data  # type: ignore[assignment]
        checks[key] = order_json_ok
    else:
        checks[key] = False
    applicable_keys.append(key)

    key = "order_has_required_keys"
    checks[key] = False
    if order_json_ok:
        has_purchase = isinstance(order_data.get("purchase"), dict)
        has_selected = is_non_empty_string(order_data.get("selected_listing_id"))
        has_prep = isinstance(order_data.get("payment_preparation"), dict)
        checks[key] = has_purchase and has_selected and has_prep
    applicable_keys.append(key)

    key = "order_purchase_id_non_empty"
    checks[key] = False
    if order_json_ok:
        purchase = order_data.get("purchase")
        if isinstance(purchase, dict):
            checks[key] = is_non_empty_string(purchase.get("purchase_id"))
    applicable_keys.append(key)

    # selected_listing_id correctness
    # If order_request.json listing-id is null, must equal listing.json top-level service_id
    # If listing-id is non-null, must equal that value
    key = "order_selected_listing_id_correct"
    checks[key] = False
    if order_json_ok and order_req_ok and isinstance(order_req, dict):
        selected_listing_id = order_data.get("selected_listing_id")
        listing_id_from_order_req = order_req.get("listing-id")
        if listing_id_from_order_req is None:
            # Need to compare with listing.json top-level service_id
            if listing_json_ok and is_non_empty_string(listing_data.get("service_id")) and is_non_empty_string(selected_listing_id):
                checks[key] = (selected_listing_id == listing_data.get("service_id"))
        else:
            # listing-id provided must match selected_listing_id
            if is_non_empty_string(listing_id_from_order_req) and is_non_empty_string(selected_listing_id):
                checks[key] = (selected_listing_id == listing_id_from_order_req)
    applicable_keys.append(key)

    # payment_preparation must include all keys with non-empty strings
    key = "payment_preparation_has_required_fields"
    checks[key] = False
    if order_json_ok:
        prep = order_data.get("payment_preparation")
        required_fields = [
            "purchase_id_hex",
            "listing_id_hex",
            "supplier_wallet",
            "token_address",
            "amount_atomic",
            "payment_router_address",
        ]
        if isinstance(prep, dict):
            all_ok = True
            for rf in required_fields:
                if not is_non_empty_string(prep.get(rf)):
                    all_ok = False
                    break
            checks[key] = all_ok
    applicable_keys.append(key)

    # Conditional: if wait=true in order_request, final_state must be present as object
    if order_req_ok and isinstance(order_req, dict) and order_req.get("wait") is True:
        key = "order_final_state_present_if_wait"
        checks[key] = False
        if order_json_ok:
            final_state = order_data.get("final_state")
            checks[key] = isinstance(final_state, dict)
        applicable_keys.append(key)

    # 3) log.md checks
    key = "log_md_exists"
    checks[key] = os.path.isfile(log_out_path)
    applicable_keys.append(key)

    # Parse required labeled lines
    log_text = ""
    if checks["log_md_exists"]:
        try:
            with open(log_out_path, "r", encoding="utf-8") as f:
                log_text = f.read()
        except Exception:
            log_text = ""

    def has_label_with_value(text: str, label: str) -> bool:
        # Must contain a line starting with exact label and a non-empty value after colon
        for line in text.splitlines():
            if line.startswith(label):
                value = line.split(":", 1)[1] if ":" in line else ""
                if is_non_empty_string(value):
                    return True
        return False

    key = "log_has_listing_id_line"
    checks[key] = False
    if checks.get("log_md_exists", False):
        checks[key] = has_label_with_value(log_text, "Listing ID:")
    applicable_keys.append(key)

    key = "log_has_purchase_id_line"
    checks[key] = False
    if checks.get("log_md_exists", False):
        checks[key] = has_label_with_value(log_text, "Purchase ID:")
    applicable_keys.append(key)

    key = "log_has_status_line"
    checks[key] = False
    if checks.get("log_md_exists", False):
        checks[key] = has_label_with_value(log_text, "Status:")
    applicable_keys.append(key)

    # Compute reward as fraction of applicable checks passed
    total = len(applicable_keys)
    passed = sum(1 for k in applicable_keys if checks.get(k, False))
    reward = 0.0
    if total > 0:
        reward = passed / total
        # clamp
        if reward < 0.0:
            reward = 0.0
        if reward > 1.0:
            reward = 1.0

    # Print single JSON line
    result = {"reward": reward}
    # Merge checks
    result.update({k: bool(checks[k]) for k in checks})
    print(json.dumps(result))

if __name__ == "__main__":
    main()