import json
import os
import sys
import re
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, InvalidOperation

def read_text_exact(path):
    # Read text preserving newline characters as-is
    with open(path, 'r', encoding='utf-8', newline='') as f:
        return f.read()

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def to_decimal(value):
    # Safely convert numeric to Decimal via string to avoid float artifacts
    return Decimal(str(value))

def fmt_set_decimal(value: Decimal, places: int):
    # Return a set of acceptable string formats for given decimal value and places
    q = Decimal('1').scaleb(-places)  # 10^-places
    s_up = str(value.quantize(q, rounding=ROUND_HALF_UP))
    s_even = str(value.quantize(q, rounding=ROUND_HALF_EVEN))
    # Ensure exactly N decimal places (could be missing trailing zeros in some contexts)
    def ensure_places(s):
        if '.' not in s:
            return s + ('.' + '0' * places if places > 0 else '')
        whole, frac = s.split('.', 1)
        if len(frac) < places:
            frac = frac + ('0' * (places - len(frac)))
        elif len(frac) > places:
            # Should not happen after quantize, but guard anyway
            frac = frac[:places]
        return whole + ('.' + frac if places > 0 else '')
    return {ensure_places(s_up), ensure_places(s_even)}

def is_int_like(value):
    return isinstance(value, int) and not isinstance(value, bool)

def validate_decimal_string(s, places):
    pattern = r"^-?\d+\.\d{%d}$" % places if places > 0 else r"^-?\d+$"
    return isinstance(s, str) and re.fullmatch(pattern, s) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (artifact-dependent only)
    checks = {
        "analysis_file_exists": False,
        "analysis_entries_order": False,
        "analysis_alpha_correct": False,
        "analysis_beta_correct": False,
        "analysis_gamma_correct": False,
        "analysis_totals_correct": False,
        "summary_file_exists": False,
        "summary_header_correct": False,
        "summary_rows_order_and_values_correct": False,
    }

    # Prepare expected calculations from inputs (no positive reward from this alone)
    files_order = ["alpha.txt", "beta.txt", "gamma.txt"]
    prompt_paths = {
        "alpha.txt": os.path.join(input_dir, "prompts", "alpha.txt"),
        "beta.txt": os.path.join(input_dir, "prompts", "beta.txt"),
        "gamma.txt": os.path.join(input_dir, "prompts", "gamma.txt"),
    }
    budget_path = os.path.join(input_dir, "budget_config.json")
    gt_tokens_path = os.path.join(input_dir, "ground_truth_tokens.json")

    # Load inputs; if any missing or invalid, later checks depending on outputs will fail naturally
    try:
        budget = load_json(budget_path)
        max_tokens = int(budget["max_tokens"])
        cost_per_million = to_decimal(budget["cost_per_million"])
    except Exception:
        max_tokens = None
        cost_per_million = None

    try:
        gt_tokens_map = load_json(gt_tokens_path)
    except Exception:
        gt_tokens_map = {}

    expected = {}
    # Build expected values per file
    for fname in files_order:
        char_count = None
        tokens = None
        try:
            content = read_text_exact(prompt_paths[fname])
            char_count = len(content)
        except Exception:
            char_count = None
        try:
            tk = gt_tokens_map.get(fname, None)
            if tk is not None:
                tokens = int(tk)
        except Exception:
            tokens = None

        # Compute expected strings if possible
        avg_set = None
        cost_set = None
        exceeds = None
        total_cost_unrounded = None
        if tokens is not None and tokens != 0 and char_count is not None:
            try:
                avg_val = Decimal(char_count) / Decimal(tokens)
                avg_set = fmt_set_decimal(avg_val, 2)
            except (InvalidOperation, ZeroDivisionError):
                avg_set = fmt_set_decimal(Decimal(0), 2)
        elif tokens == 0 and char_count is not None:
            avg_set = fmt_set_decimal(Decimal(0), 2)

        if tokens is not None and cost_per_million is not None:
            try:
                cost_val = (Decimal(tokens) * cost_per_million) / Decimal(1000000)
                cost_set = fmt_set_decimal(cost_val, 6)
                total_cost_unrounded = cost_val
            except (InvalidOperation, ZeroDivisionError):
                cost_set = fmt_set_decimal(Decimal(0), 6)
                total_cost_unrounded = Decimal(0)

        if tokens is not None and max_tokens is not None:
            exceeds = bool(tokens > max_tokens)

        expected[fname] = {
            "characters": char_count,
            "tokens": tokens,
            "avg_set": avg_set,
            "cost_set": cost_set,
            "exceeds": exceeds,
            "cost_unrounded": total_cost_unrounded,
        }

    # Validate output/prompt_analysis.json
    analysis_path = os.path.join(output_dir, "prompt_analysis.json")
    analysis_data = None
    if os.path.isfile(analysis_path):
        checks["analysis_file_exists"] = True
        try:
            with open(analysis_path, 'r', encoding='utf-8') as f:
                analysis_data = json.load(f)
        except Exception:
            analysis_data = None

    # Helper flags for later CSV cross-check
    entries_ok = False
    entries_order_ok = False
    entry_values_ok = { "alpha.txt": False, "beta.txt": False, "gamma.txt": False }
    if analysis_data and isinstance(analysis_data, dict):
        entries = analysis_data.get("entries")
        totals = analysis_data.get("totals")
        if isinstance(entries, list) and len(entries) == 3:
            files_in_entries = []
            for e in entries:
                if isinstance(e, dict) and "file" in e:
                    files_in_entries.append(e["file"])
                else:
                    files_in_entries.append(None)
            if files_in_entries == files_order:
                checks["analysis_entries_order"] = True
                entries_order_ok = True

            # Validate each entry strictly
            for e in entries:
                if not isinstance(e, dict):
                    continue
                fname = e.get("file")
                if fname not in files_order:
                    continue
                exp = expected.get(fname, {})
                # Required keys
                has_all_keys = all(k in e for k in ["characters", "tokens", "avg_chars_per_token", "estimated_cost_usd", "exceeds_token_limit"])
                if not has_all_keys:
                    entry_values_ok[fname] = False
                    continue

                # Type and value checks
                chars_ok = is_int_like(e["characters"]) and (exp["characters"] is not None) and (e["characters"] == exp["characters"])
                tokens_ok = is_int_like(e["tokens"]) and (exp["tokens"] is not None) and (e["tokens"] == exp["tokens"])
                avg_str_ok = validate_decimal_string(e["avg_chars_per_token"], 2) and (exp["avg_set"] is not None) and (e["avg_chars_per_token"] in exp["avg_set"])
                cost_str_ok = validate_decimal_string(e["estimated_cost_usd"], 6) and (exp["cost_set"] is not None) and (e["estimated_cost_usd"] in exp["cost_set"])
                exceed_ok = isinstance(e["exceeds_token_limit"], bool) and (exp["exceeds"] is not None) and (e["exceeds_token_limit"] == exp["exceeds"])

                entry_values_ok[fname] = all([chars_ok, tokens_ok, avg_str_ok, cost_str_ok, exceed_ok])

            # Assign per-entry checks
            checks["analysis_alpha_correct"] = entry_values_ok["alpha.txt"]
            checks["analysis_beta_correct"] = entry_values_ok["beta.txt"]
            checks["analysis_gamma_correct"] = entry_values_ok["gamma.txt"]

            entries_ok = checks["analysis_alpha_correct"] and checks["analysis_beta_correct"] and checks["analysis_gamma_correct"]

        # Validate totals
        if isinstance(totals, dict):
            # Expected totals
            try:
                total_chars_expected = sum(expected[f]["characters"] for f in files_order if expected[f]["characters"] is not None)
                total_tokens_expected = sum(expected[f]["tokens"] for f in files_order if expected[f]["tokens"] is not None)
            except Exception:
                total_chars_expected = None
                total_tokens_expected = None

            # Total cost expected: sum over unrounded token costs, then rounded to 6dp
            total_cost_set = None
            # Also compute alternative: sum of per-entry rounded costs to 6 dp then sum and reformat to 6dp (lenient path)
            if all(expected[f]["cost_unrounded"] is not None for f in files_order):
                try:
                    total_cost_unrounded_sum = sum(expected[f]["cost_unrounded"] for f in files_order)
                    total_cost_set = fmt_set_decimal(total_cost_unrounded_sum, 6)
                except Exception:
                    total_cost_set = None

            totals_chars_ok = is_int_like(totals.get("total_characters")) and (total_chars_expected is not None) and (totals.get("total_characters") == total_chars_expected)
            totals_tokens_ok = is_int_like(totals.get("total_tokens")) and (total_tokens_expected is not None) and (totals.get("total_tokens") == total_tokens_expected)

            total_cost_value = totals.get("total_estimated_cost_usd")
            totals_cost_ok = False
            if isinstance(total_cost_value, str) and validate_decimal_string(total_cost_value, 6) and total_cost_set is not None:
                if total_cost_value in total_cost_set:
                    totals_cost_ok = True
                else:
                    # Leniency: accept sum of provided per-entry costs if matches
                    try:
                        per_entry_costs_from_json = []
                        if isinstance(entries, list) and len(entries) == 3:
                            for e in entries:
                                ce = e.get("estimated_cost_usd")
                                if isinstance(ce, str) and validate_decimal_string(ce, 6):
                                    per_entry_costs_from_json.append(Decimal(ce))
                        if len(per_entry_costs_from_json) == 3:
                            alt_sum = sum(per_entry_costs_from_json)
                            alt_set = fmt_set_decimal(alt_sum, 6)
                            if total_cost_value in alt_set:
                                totals_cost_ok = True
                    except Exception:
                        pass

            checks["analysis_totals_correct"] = totals_chars_ok and totals_tokens_ok and totals_cost_ok

    # Validate output/prompt_summary.csv
    summary_path = os.path.join(output_dir, "prompt_summary.csv")
    csv_lines = None
    if os.path.isfile(summary_path):
        checks["summary_file_exists"] = True
        try:
            with open(summary_path, 'r', encoding='utf-8', newline='') as f:
                # Preserve exact content, strip only trailing newline characters for line count
                content = f.read()
                # Normalize to splitlines keeping all rows; splitlines() removes trailing newline characters
                csv_lines = content.splitlines()
        except Exception:
            csv_lines = None

    if csv_lines is not None:
        # Header check
        expected_header = "file,characters,tokens,avg_chars_per_token,estimated_cost_usd,exceeds_token_limit"
        if len(csv_lines) >= 1 and csv_lines[0] == expected_header:
            checks["summary_header_correct"] = True

        # Rows check: exactly 3 data rows
        if len(csv_lines) == 4:
            data_rows = csv_lines[1:]
            row_files = []
            rows_ok = True
            for i, row in enumerate(data_rows):
                cols = row.split(',')
                if len(cols) != 6:
                    rows_ok = False
                    break
                fcol, ccol, tcol, acol, ecol, xcol = cols
                row_files.append(fcol)
                # Build expected string values
                fname = files_order[i] if i < len(files_order) else None
                if fcol != fname:
                    rows_ok = False
                    break
                exp = expected.get(fname, {})
                # characters and tokens as exact integers
                if exp["characters"] is None or exp["tokens"] is None or exp["avg_set"] is None or exp["cost_set"] is None or exp["exceeds"] is None:
                    rows_ok = False
                    break
                exp_chars_str = str(exp["characters"])
                exp_tokens_str = str(exp["tokens"])
                # Choose a consistent decimal from acceptable set for comparison: since we accept both, ensure CSV value matches one of acceptable formats
                avg_ok = (acol in exp["avg_set"])
                cost_ok = (ecol in exp["cost_set"])
                # Boolean must be lowercase true/false
                if xcol not in ("true", "false"):
                    rows_ok = False
                    break
                # Compare against expected
                if ccol != exp_chars_str or tcol != exp_tokens_str or not avg_ok or not cost_ok or (xcol == "true") != exp["exceeds"]:
                    rows_ok = False
                    break
            # Order check
            order_ok = (row_files == files_order)
            # Additionally ensure CSV matches JSON entries exactly when JSON entries have been validated correctly and order was correct
            csv_matches_json = True
            if analysis_data and isinstance(analysis_data, dict) and entries_ok and entries_order_ok:
                entries = analysis_data.get("entries", [])
                # Map file to entry for easy lookup
                map_json = {e["file"]: e for e in entries if isinstance(e, dict) and "file" in e}
                for row in data_rows:
                    fcol, ccol, tcol, acol, ecol, xcol = row.split(',')
                    je = map_json.get(fcol)
                    if not je:
                        csv_matches_json = False
                        break
                    # Compare string forms
                    if str(je.get("characters")) != ccol or str(je.get("tokens")) != tcol or je.get("avg_chars_per_token") != acol or je.get("estimated_cost_usd") != ecol or (("true" if je.get("exceeds_token_limit") else "false") != xcol):
                        csv_matches_json = False
                        break
            else:
                # If analysis not valid, require only rows_ok and order_ok but do not mark as matching JSON
                csv_matches_json = False

            checks["summary_rows_order_and_values_correct"] = rows_ok and order_ok and csv_matches_json

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if both output files missing or required artifacts missing => reward 0.0
    # Enforced naturally since checks remain False; ensure explicit condition
    if not checks["analysis_file_exists"] and not checks["summary_file_exists"]:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()