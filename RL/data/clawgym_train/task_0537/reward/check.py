import json
import os
import sys
from typing import Any, Dict, List, Tuple

def is_number(x):
    return (isinstance(x, (int, float)) and not isinstance(x, bool))

def load_jsonl(path: str) -> Tuple[bool, List[Dict[str, Any]], str]:
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    items.append(obj)
                except Exception as e:
                    return False, [], f"Invalid JSONL line: {e}"
        return True, items, ""
    except Exception as e:
        return False, [], f"Error reading results.jsonl: {e}"

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "results_exists_nonempty": False,
        "results_valid_jsonl": False,
        "results_required_keys_exact": False,
        "results_input_type_allowed": False,
        "results_risk_level_allowed": False,
        "results_checks_run_nonempty": False,
        "results_mode_allowed": False,
        "results_raw_is_object": False,
        "results_risk_score_range": False,
        "results_timestamp_nonempty": False,
        "results_normalized_unique": False,
        "summary_exists": False,
        "summary_schema_valid": False,
        "summary_counts_match": False,
        "summary_top_risks_valid": False,
        "executive_exists": False,
        "executive_contains_keywords": False,
        "executive_under_word_limit": False,
    }

    expected_keys = {
        "input_type",
        "input_value",
        "normalized_value",
        "checks_run",
        "risk_score",
        "risk_level",
        "mode",
        "raw",
        "timestamp",
    }
    allowed_types = {"domain", "ip", "email", "url", "password_sha1", "password_prefix"}
    allowed_levels = {"low", "medium", "high", "critical"}
    allowed_modes = {"demo", "paid"}

    # Validate results.jsonl
    results_path = os.path.join(output_dir, "results.jsonl")
    results_items: List[Dict[str, Any]] = []
    if os.path.isfile(results_path):
        # Check non-empty file with at least one item
        try:
            # Quick check for any non-whitespace content
            with open(results_path, "r", encoding="utf-8") as f:
                content = f.read()
            if content.strip():
                # parse JSONL
                ok, items, _ = load_jsonl(results_path)
                if ok and len(items) > 0:
                    checks["results_exists_nonempty"] = True
                    results_items = items
                else:
                    checks["results_exists_nonempty"] = False
            else:
                checks["results_exists_nonempty"] = False
        except Exception:
            checks["results_exists_nonempty"] = False

    # If we have items, validate structure
    if checks["results_exists_nonempty"]:
        # Valid JSONL already implied by successful parsing
        checks["results_valid_jsonl"] = True

        # Validate exact required keys for each object
        keys_ok = True
        types_ok = True
        levels_ok = True
        checks_run_ok = True
        mode_ok = True
        raw_ok = True
        score_ok = True
        ts_ok = True

        for obj in results_items:
            # exact keys
            if set(obj.keys()) != expected_keys:
                keys_ok = False
                break

        if keys_ok:
            checks["results_required_keys_exact"] = True

            # Validate fields only if keys are correct
            for obj in results_items:
                # input_type allowed
                itype = obj.get("input_type")
                if itype not in allowed_types:
                    types_ok = False
                    break

                # risk_level allowed
                rlevel = obj.get("risk_level")
                if rlevel not in allowed_levels:
                    levels_ok = False
                    break

                # checks_run non-empty array of strings
                cr = obj.get("checks_run")
                if not isinstance(cr, list) or len(cr) == 0 or not all(isinstance(x, str) for x in cr):
                    checks_run_ok = False
                    break

                # mode allowed
                mode = obj.get("mode")
                if mode not in allowed_modes:
                    mode_ok = False
                    break

                # raw is object
                raw = obj.get("raw")
                if not isinstance(raw, dict):
                    raw_ok = False
                    break

                # risk_score 0-100 inclusive
                rs = obj.get("risk_score")
                if not is_number(rs) or rs < 0 or rs > 100:
                    score_ok = False
                    break

                # timestamp non-empty string
                ts = obj.get("timestamp")
                if not isinstance(ts, str) or len(ts.strip()) == 0:
                    ts_ok = False
                    break

        checks["results_input_type_allowed"] = types_ok and keys_ok
        checks["results_risk_level_allowed"] = levels_ok and keys_ok
        checks["results_checks_run_nonempty"] = checks_run_ok and keys_ok
        checks["results_mode_allowed"] = mode_ok and keys_ok
        checks["results_raw_is_object"] = raw_ok and keys_ok
        checks["results_risk_score_range"] = score_ok and keys_ok
        checks["results_timestamp_nonempty"] = ts_ok and keys_ok

        # Uniqueness per (input_type, normalized_value)
        if keys_ok:
            seen = set()
            unique = True
            for obj in results_items:
                key = (obj.get("input_type"), obj.get("normalized_value"))
                if key in seen:
                    unique = False
                    break
                seen.add(key)
            checks["results_normalized_unique"] = unique

    # Validate summary.json
    summary_path = os.path.join(output_dir, "summary.json")
    summary_obj: Dict[str, Any] = {}
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_obj = json.load(f)
        except Exception:
            checks["summary_schema_valid"] = False
            summary_obj = {}
        else:
            # Schema validation
            required_summary_keys = {"generated_at", "total", "by_type", "by_risk_level", "top_risks"}
            schema_ok = (
                isinstance(summary_obj, dict)
                and required_summary_keys.issubset(set(summary_obj.keys()))
                and isinstance(summary_obj.get("generated_at"), str)
                and isinstance(summary_obj.get("total"), int)
                and isinstance(summary_obj.get("by_type"), dict)
                and isinstance(summary_obj.get("by_risk_level"), dict)
                and isinstance(summary_obj.get("top_risks"), list)
            )
            checks["summary_schema_valid"] = schema_ok

            # Counts match only if results are valid and schema ok
            if schema_ok and checks["results_exists_nonempty"] and checks["results_valid_jsonl"]:
                total = summary_obj.get("total")
                n_results = len(results_items)

                by_type = summary_obj.get("by_type", {})
                by_risk = summary_obj.get("by_risk_level", {})

                # Sum ints in by_type and by_risk
                def sum_ints(d):
                    s = 0
                    for v in d.values():
                        if isinstance(v, int):
                            s += v
                        else:
                            return None
                    return s

                sum_by_type = sum_ints(by_type)
                sum_by_risk = sum_ints(by_risk)

                counts_ok = (
                    isinstance(total, int)
                    and total == n_results
                    and sum_by_type is not None
                    and sum_by_risk is not None
                    and sum_by_type == total
                    and sum_by_risk == total
                )
                checks["summary_counts_match"] = counts_ok

            # top_risks validation
            if schema_ok:
                tr = summary_obj.get("top_risks", [])
                tr_ok = True
                # length <= 5
                if not isinstance(tr, list) or len(tr) > 5:
                    tr_ok = False
                else:
                    prev = None
                    for item in tr:
                        if not isinstance(item, dict):
                            tr_ok = False
                            break
                        # required keys for each item
                        if not all(k in item for k in ("input_type", "input_value", "risk_level", "risk_score")):
                            tr_ok = False
                            break
                        if item.get("input_type") not in allowed_types:
                            tr_ok = False
                            break
                        if item.get("risk_level") not in allowed_levels:
                            tr_ok = False
                            break
                        rs = item.get("risk_score")
                        if not is_number(rs) or rs < 0 or rs > 100:
                            tr_ok = False
                            break
                        # sorting non-increasing by risk_score
                        if prev is not None and rs > prev:
                            tr_ok = False
                            break
                        prev = rs
                checks["summary_top_risks_valid"] = tr_ok

    # Validate executive_summary.md
    exec_path = os.path.join(output_dir, "executive_summary.md")
    if os.path.isfile(exec_path):
        checks["executive_exists"] = True
        try:
            with open(exec_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            text = ""
        # contains "recommend" and "risk" (case-insensitive)
        lowered = text.lower()
        if "recommend" in lowered and "risk" in lowered:
            checks["executive_contains_keywords"] = True
        # <= 300 words
        words = text.split()
        if len(words) <= 300:
            checks["executive_under_word_limit"] = True

    # Compute reward
    # If the primary required artifact (results.jsonl) is missing or empty, overall reward must be 0.0
    if not checks["results_exists_nonempty"]:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Reward is fraction of passed checks
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result_obj = {"reward": reward}
    result_obj.update(checks)
    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()