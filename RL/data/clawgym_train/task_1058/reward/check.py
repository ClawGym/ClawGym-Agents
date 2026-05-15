import json
import os
import sys
from typing import Any, Dict

def read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def approx_equal(a: float, b: float, tol: float = 1e-3) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def to_float(val: Any) -> float:
    try:
        return float(val)
    except Exception:
        return float("nan")

def mask_account(account_id: str) -> str:
    if not isinstance(account_id, str):
        return ""
    last4 = account_id[-4:] if len(account_id) >= 4 else account_id
    stars = "*" * (len(account_id) - len(last4))
    return f"{stars}{last4}"

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    trade_request_path = os.path.join(input_dir, "trade_request.json")
    quote_context_path = os.path.join(input_dir, "quote_context.json")
    ticket_path = os.path.join(output_dir, "trade", "ticket.json")
    checklist_path = os.path.join(output_dir, "trade", "trade_checklist.md")

    # Load inputs for expected values
    trade_request = read_json(trade_request_path) or {}
    quote_context = read_json(quote_context_path) or {}

    expected = {}
    try:
        acct = trade_request.get("account_id", "")
        expected["account_id"] = acct
        expected["masked_account"] = mask_account(acct)
        expected["environment"] = str(trade_request.get("environment", "")).lower() or "live"
        expected["symbol_upper"] = str(trade_request.get("symbol", "")).upper()
        expected["side"] = str(trade_request.get("side", "")).lower()
        expected["quantity"] = int(trade_request.get("quantity")) if "quantity" in trade_request else None
        expected["order_type"] = str(trade_request.get("order_type", "")).lower()
        expected["tif"] = str(trade_request.get("tif", "")).lower()
        expected["limit_price"] = to_float(trade_request.get("limit_price"))
        expected["stop_price"] = trade_request.get("stop_price", None)
        expected["risk_cap_usd"] = to_float(trade_request.get("risk_cap_usd"))
        expected["notes"] = trade_request.get("notes", None)

        yprice = to_float(quote_context.get("yahoo_price"))
        qt_last = to_float(quote_context.get("questrade_last"))
        max_drift = to_float(quote_context.get("max_price_drift_pct"))
        data_age = quote_context.get("data_age_seconds", None)
        max_data_age = quote_context.get("max_data_age_seconds", None)

        # Compute observed drift
        observed_drift = None
        if yprice == 0 or (yprice != yprice):  # NaN check
            observed_drift = None
        else:
            try:
                observed_drift = ((qt_last - yprice) / yprice) * 100.0
            except Exception:
                observed_drift = None

        expected["observed_price_drift_pct"] = observed_drift
        expected["max_price_drift_pct"] = max_drift
        expected["data_age_seconds"] = data_age
        expected["max_data_age_seconds"] = max_data_age
        # Estimated notional
        if expected["limit_price"] == expected["limit_price"] and expected["quantity"] is not None:
            expected["estimated_notional"] = float(expected["limit_price"]) * int(expected["quantity"])
        else:
            expected["estimated_notional"] = None
    except Exception:
        # If parsing fails, expected remains partially filled; dependent checks will fail.
        pass

    checks: Dict[str, bool] = {
        # Existence and basic parsing
        "output_ticket_exists": False,
        "output_checklist_exists": False,
        "ticket_json_valid": False,
        # JSON field checks
        "created_at_present": False,
        "environment_live": False,
        "symbol_upper_matches": False,
        "side_matches": False,
        "quantity_matches": False,
        "order_type_limit": False,
        "tif_matches": False,
        "limit_price_matches": False,
        "stop_price_null_or_absent": False,
        "estimated_notional_correct": False,
        "risk_cap_matches": False,
        "notes_present": False,
        # Safety block checks
        "safety_status_pass": False,
        "safety_confirmations_true": False,
        "safety_data_age_matches": False,
        "safety_drift_max_matches": False,
        "safety_drift_observed_matches": False,
        "safety_risk_cap_matches": False,
        # Privacy checks
        "account_masking_correct": False,
        "raw_account_not_leaked": False,
        # Markdown content checks
        "checklist_header_present": False,
        "checklist_special_safety_section_mentions": False,
        "checklist_environment_line": False,
        "checklist_account_masked_line": False,
        "checklist_limit_price_line": False,
        "checklist_tif_line": False,
        "checklist_pre_trade_section": False,
        "checklist_machine_readable_section": False,
    }

    # Check for artifact existence
    if os.path.isfile(ticket_path):
        checks["output_ticket_exists"] = True
    if os.path.isfile(checklist_path):
        checks["output_checklist_exists"] = True

    # Load outputs
    ticket = None
    if checks["output_ticket_exists"]:
        ticket = read_json(ticket_path)
        if isinstance(ticket, dict):
            checks["ticket_json_valid"] = True

    # JSON checks
    if checks["ticket_json_valid"]:
        # created_at_utc present and string
        if isinstance(ticket.get("created_at_utc"), str) and ticket.get("created_at_utc"):
            checks["created_at_present"] = True

        # environment
        env = ticket.get("environment")
        if isinstance(env, str) and env.lower() == "live" and expected.get("environment") == "live":
            checks["environment_live"] = True

        # symbol uppercase
        sym = ticket.get("symbol")
        if isinstance(sym, str) and sym.upper() == expected.get("symbol_upper"):
            checks["symbol_upper_matches"] = True

        # side
        if ticket.get("side") == expected.get("side"):
            checks["side_matches"] = True

        # quantity
        if isinstance(ticket.get("quantity"), int) and ticket.get("quantity") == expected.get("quantity"):
            checks["quantity_matches"] = True

        # order type
        if isinstance(ticket.get("order_type"), str) and ticket.get("order_type").lower() == "limit" == expected.get("order_type"):
            checks["order_type_limit"] = True

        # time in force
        tif = ticket.get("time_in_force")
        exp_tif = expected.get("tif")
        if isinstance(tif, str) and isinstance(exp_tif, str) and tif.lower() == exp_tif.lower():
            checks["tif_matches"] = True

        # limit price
        t_lim = ticket.get("limit_price")
        if t_lim is not None and approx_equal(to_float(t_lim), to_float(expected.get("limit_price")), tol=1e-6):
            checks["limit_price_matches"] = True

        # stop price null or absent
        if "stop_price" not in ticket or ticket.get("stop_price") in (None, "null"):
            checks["stop_price_null_or_absent"] = True

        # estimated notional
        t_notional = ticket.get("estimated_notional")
        exp_notional = expected.get("estimated_notional")
        if t_notional is not None and exp_notional is not None and approx_equal(to_float(t_notional), to_float(exp_notional), tol=1e-2):
            checks["estimated_notional_correct"] = True

        # risk cap
        t_risk = ticket.get("risk_cap_usd")
        if t_risk is not None and approx_equal(to_float(t_risk), to_float(expected.get("risk_cap_usd")), tol=1e-6):
            checks["risk_cap_matches"] = True

        # notes present (allow empty string but key must exist)
        if "notes" in ticket and isinstance(ticket.get("notes"), (str, type(None))):
            checks["notes_present"] = True

        # Safety block
        ssc = ticket.get("special_safety_check")
        if isinstance(ssc, dict):
            if ssc.get("status") == "pass":
                checks["safety_status_pass"] = True
            # Confirmations
            if (
                ssc.get("policy_acknowledged") is True
                and ssc.get("user_authorized") is True
                and ssc.get("manual_execution_confirmed") is True
                and ssc.get("no_secrets_shared_confirmed") is True
            ):
                checks["safety_confirmations_true"] = True
            # Data age
            if (
                ssc.get("data_age_seconds") == expected.get("data_age_seconds")
                and ssc.get("max_data_age_seconds") == expected.get("max_data_age_seconds")
            ):
                checks["safety_data_age_matches"] = True
            # Drift max
            if ssc.get("max_price_drift_pct") is not None and approx_equal(
                to_float(ssc.get("max_price_drift_pct")), to_float(expected.get("max_price_drift_pct")), tol=1e-6
            ):
                checks["safety_drift_max_matches"] = True
            # Drift observed
            if expected.get("observed_price_drift_pct") is not None and ssc.get("observed_price_drift_pct") is not None:
                if approx_equal(
                    to_float(ssc.get("observed_price_drift_pct")),
                    to_float(expected.get("observed_price_drift_pct")),
                    tol=1e-3,
                ):
                    checks["safety_drift_observed_matches"] = True
            # Risk cap in safety block matches
            if ssc.get("risk_cap_usd") is not None and approx_equal(
                to_float(ssc.get("risk_cap_usd")), to_float(expected.get("risk_cap_usd")), tol=1e-6
            ):
                checks["safety_risk_cap_matches"] = True

        # Account masking correctness (both account_id and account_id_masked)
        masked_expected = expected.get("masked_account", "")
        acc_out = ticket.get("account_id")
        acc_masked_out = ticket.get("account_id_masked")
        def is_masked_correct(val: Any) -> bool:
            if not isinstance(val, str):
                return False
            # Only last 4 visible, preceding are asterisks, and length matches original
            return val == masked_expected and (len(expected.get("account_id","")) == len(val))
        if is_masked_correct(acc_out) and is_masked_correct(acc_masked_out):
            checks["account_masking_correct"] = True

    # Markdown checks
    checklist_text = ""
    if checks["output_checklist_exists"]:
        checklist_text = read_text(checklist_path)
        # Header presence
        if "Trade Checklist" in checklist_text:
            checks["checklist_header_present"] = True
        # Special safety check mentions data age and drift
        if ("Special Safety Check" in checklist_text) and (("data age" in checklist_text.lower()) or ("data age check" in checklist_text.lower())) and ("drift" in checklist_text.lower()):
            checks["checklist_special_safety_section_mentions"] = True
        # Environment: LIVE
        if "Environment: LIVE" in checklist_text:
            checks["checklist_environment_line"] = True
        # Account masked line includes masked value
        masked_expected = expected.get("masked_account", "")
        if masked_expected and ("Account:" in checklist_text) and (masked_expected in checklist_text):
            checks["checklist_account_masked_line"] = True
        # Limit price line
        try:
            lp_str = f"Limit price: {float(expected.get('limit_price'))}"
            # To match formatting like 412.35 without trailing zeros issues, format with up to 6 decimals but simple str may suffice.
            # We'll check inclusive of lp_str with normalized formatting to avoid mismatch due to float default repr.
            if f"Limit price: {format(float(expected.get('limit_price')),'g')}" in checklist_text or lp_str in checklist_text:
                checks["checklist_limit_price_line"] = True
        except Exception:
            pass
        # Time in force: GTC
        tif_upper = str(expected.get("tif","")).upper()
        if tif_upper and f"Time in force: {tif_upper}" in checklist_text:
            checks["checklist_tif_line"] = True
        # Pre-Trade Hard Checks section
        if "Pre-Trade Hard Checks" in checklist_text:
            checks["checklist_pre_trade_section"] = True
        # Machine-Readable Ticket section
        if "Machine-Readable Ticket" in checklist_text:
            checks["checklist_machine_readable_section"] = True

    # Privacy: Ensure raw account id does not appear anywhere in outputs
    raw_acct = expected.get("account_id", "")
    raw_not_present = True
    if raw_acct:
        if checks["output_ticket_exists"]:
            try:
                ticket_text = read_text(ticket_path)
            except Exception:
                ticket_text = ""
            if raw_acct in ticket_text:
                raw_not_present = False
        if checks["output_checklist_exists"]:
            if raw_acct in checklist_text:
                raw_not_present = False
    checks["raw_account_not_leaked"] = raw_not_present

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure baseline 0 if both required artifacts are missing
    if not checks["output_ticket_exists"] and not checks["output_checklist_exists"]:
        reward = 0.0

    # Print final JSON (single line)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()