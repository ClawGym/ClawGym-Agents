import json
import os
import sys
from collections import OrderedDict

def read_nonempty_lines(path):
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s:
                    lines.append(s)
    except Exception:
        return None
    return lines

def approx_equal(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = OrderedDict()

    # Paths
    ev_results_path = os.path.join(output_dir, "ev_results.jsonl")
    summary_path = os.path.join(output_dir, "summary.json")
    recs_path = os.path.join(output_dir, "recommendations.md")

    # Initialize checks (all False by default)
    checks["ev_results_exists"] = False
    checks["summary_exists"] = False
    checks["recommendations_exists"] = False
    checks["ev_results_has_9_lines"] = False
    checks["ev_results_ids_in_order"] = False
    # Per-ID checks will be added below
    # Summary checks
    checks["summary_values_match"] = False
    # Recommendation content checks
    checks["recs_mentions_top3_ids"] = False
    checks["recs_has_not_financial_advice"] = False
    checks["recs_has_fees"] = False
    checks["recs_has_slippage"] = False
    checks["recs_has_sample_size"] = False

    # Expected data
    expected_order = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A10"]
    expected_records = {
        "A1": {
            "type": "basic",
            "ev_value": 0.1550,
            "ev_percentage": 15.50,
            "verdict": "positive",
            "kelly_fraction_half": 0.0705,
        },
        "A2": {
            "type": "basic",
            "ev_value": -0.0400,
            "ev_percentage": -4.00,
            "verdict": "negative",
            "kelly_fraction_half": 0.0000,
        },
        "A3": {
            "type": "polymarket",
            "edge": 0.2000,
            "ev_per_dollar": 0.5000,
            "ev_value": 0.2000,
            "ev_percentage": 20.00,
            "verdict": "positive",
        },
        "A4": {
            "type": "polymarket",
            "edge": -0.0500,
            "ev_per_dollar": -0.1000,
            "ev_value": -0.0500,
            "ev_percentage": -5.00,
            "verdict": "negative",
        },
        "A5": {
            "type": "ratio",
            "ev_value": 0.7360,
            "ev_percentage": 73.60,
            "verdict": "positive",
            "kelly_fraction_half": 0.2044,
        },
        "A6": {
            "type": "ratio",
            "ev_value": -0.0800,
            "ev_percentage": -8.00,
            "verdict": "negative",
            "kelly_fraction_half": 0.0000,
        },
        "A7": {
            "type": "basic",
            "ev_value": 0.5000,
            "ev_percentage": 16.67,
            "verdict": "positive",
            "kelly_fraction_half": 0.1250,
        },
        "A8": {
            "type": "polymarket",
            "edge": 0.0300,
            "ev_per_dollar": 0.0577,
            "ev_value": 0.0300,
            "ev_percentage": 3.00,
            "verdict": "positive",
        },
        "A10": {
            "type": "ratio",
            "ev_value": 0.0000,
            "ev_percentage": 0.00,
            "verdict": "break-even",
            "kelly_fraction_half": 0.0000,
        },
    }

    # Add per-record validation placeholders
    for rid in expected_order:
        checks[f"ev_record_{rid}_valid"] = False

    # Check existence
    if os.path.isfile(ev_results_path):
        checks["ev_results_exists"] = True
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
    if os.path.isfile(recs_path):
        checks["recommendations_exists"] = True

    # Process ev_results.jsonl
    if checks["ev_results_exists"]:
        lines = read_nonempty_lines(ev_results_path)
        if lines is not None and len(lines) == 9:
            checks["ev_results_has_9_lines"] = True

            # Parse and validate order
            ids = []
            parsed = []
            parse_ok = True
            for idx, line in enumerate(lines):
                try:
                    obj = json.loads(line)
                except Exception:
                    parse_ok = False
                    obj = None
                parsed.append(obj)
                if obj and isinstance(obj, dict) and "id" in obj:
                    ids.append(obj.get("id"))
                else:
                    ids.append(None)
            if parse_ok and ids == expected_order:
                checks["ev_results_ids_in_order"] = True

            # Validate each record content
            if parse_ok:
                # Field tolerances
                tol_4dp = 1e-4
                tol_pct = 1e-2

                for obj in parsed:
                    if not isinstance(obj, dict):
                        continue
                    rid = obj.get("id")
                    if rid not in expected_records:
                        continue
                    exp = expected_records[rid]
                    rtype = exp["type"]
                    # Required key sets
                    if rtype in ("basic", "ratio"):
                        expected_keys = {"id", "type", "ev_value", "ev_percentage", "verdict", "kelly_fraction_half"}
                    elif rtype == "polymarket":
                        expected_keys = {"id", "type", "ev_value", "ev_percentage", "verdict", "edge", "ev_per_dollar"}
                    else:
                        expected_keys = set()

                    # Ensure keys exactly match expected (no extras, no missing)
                    keys_ok = set(obj.keys()) == expected_keys

                    # Type match
                    type_ok = (obj.get("type") == rtype)

                    # Verdict match
                    verdict_ok = (obj.get("verdict") == exp["verdict"])

                    # Numeric checks
                    nums_ok = True

                    # ev_value and ev_percentage always present
                    nums_ok = nums_ok and approx_equal(obj.get("ev_value"), exp["ev_value"], tol_4dp)
                    nums_ok = nums_ok and approx_equal(obj.get("ev_percentage"), exp["ev_percentage"], tol_pct)

                    if rtype in ("basic", "ratio"):
                        nums_ok = nums_ok and approx_equal(obj.get("kelly_fraction_half"), exp["kelly_fraction_half"], tol_4dp)
                    if rtype == "polymarket":
                        nums_ok = nums_ok and approx_equal(obj.get("edge"), exp["edge"], tol_4dp)
                        nums_ok = nums_ok and approx_equal(obj.get("ev_per_dollar"), exp["ev_per_dollar"], tol_4dp)

                    if keys_ok and type_ok and verdict_ok and nums_ok:
                        checks[f"ev_record_{rid}_valid"] = True

    # Validate summary.json
    if checks["summary_exists"]:
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_obj = json.load(f)
            expected_summary = {
                "total_input": 10,
                "processed": 9,
                "positives": 5,
                "negatives": 3,
                "break_even": 1,
                "top3_ids": ["A5", "A7", "A3"],
            }
            # Ensure exact fields and values
            fields_match = set(summary_obj.keys()) == set(expected_summary.keys())
            values_match = (
                summary_obj.get("total_input") == expected_summary["total_input"]
                and summary_obj.get("processed") == expected_summary["processed"]
                and summary_obj.get("positives") == expected_summary["positives"]
                and summary_obj.get("negatives") == expected_summary["negatives"]
                and summary_obj.get("break_even") == expected_summary["break_even"]
                and summary_obj.get("top3_ids") == expected_summary["top3_ids"]
            )
            if fields_match and values_match:
                checks["summary_values_match"] = True
        except Exception:
            pass

    # Validate recommendations.md content
    if checks["recommendations_exists"]:
        try:
            with open(recs_path, "r", encoding="utf-8") as f:
                recs_text = f.read()
            # Top 3 IDs mentioned
            ids_present = all(x in recs_text for x in ["A5", "A7", "A3"])
            checks["recs_mentions_top3_ids"] = ids_present

            low = recs_text.lower()
            checks["recs_has_not_financial_advice"] = ("not financial advice" in low)
            checks["recs_has_fees"] = ("fees" in low)
            checks["recs_has_slippage"] = ("slippage" in low)
            checks["recs_has_sample_size"] = ("sample size" in low)
        except Exception:
            pass

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure reward between 0 and 1
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    # Print single JSON line with reward first
    out = OrderedDict()
    out["reward"] = reward
    for k, v in checks.items():
        out[k] = v
    print(json.dumps(out))

if __name__ == "__main__":
    main()