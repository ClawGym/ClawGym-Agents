import json
import os
import sys
import re

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def parse_jsonl_records(path):
    records = []
    raw_lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                raw_lines.append(line)
                s = line.strip()
                if not s:
                    # Skip empty lines safely
                    continue
                try:
                    obj = json.loads(s)
                    records.append(obj)
                except Exception:
                    records.append(None)
    except Exception:
        return [], []
    return records, raw_lines

def is_nonempty_string(x):
    return isinstance(x, str) and len(x.strip()) > 0

def validate_alternatives(val):
    # Either non-empty string OR array of non-empty strings
    if isinstance(val, str):
        return len(val.strip()) > 0
    if isinstance(val, list):
        if len(val) == 0:
            return False
        for item in val:
            if not isinstance(item, str) or len(item.strip()) == 0:
                return False
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "decisions_file_exists": False,
        "decisions_non_empty": False,
        "decisions_valid_schema": False,
        "decisions_min_count_12": False,
        "decisions_reversibility_min_counts": False,
        "weekly_file_exists": False,
        "weekly_has_title_date": False,
        "weekly_decisions_count_matches": False,
        "weekly_has_category_lines": False,
        "weekly_has_worth_watching": False,
        "weekly_has_pattern_signal": False,
        "patterns_required_and_exists": False,
        "patterns_has_axis_or": False,
        "patterns_has_bias_mention": False,
        "summary_file_exists": False,
        "summary_header_ok": False,
        "summary_rows_count_ok": False,
        "summary_rows_values_ok": False,
    }

    # Paths
    decisions_path = os.path.join(output_dir, "decisions.jsonl")
    weekly_path = os.path.join(output_dir, "weekly_review.md")
    patterns_path = os.path.join(output_dir, "patterns.md")
    summary_path = os.path.join(output_dir, "summary.csv")

    # 1) Validate decisions.jsonl
    if os.path.isfile(decisions_path):
        checks["decisions_file_exists"] = True
        try:
            size = os.path.getsize(decisions_path)
            if size > 0:
                checks["decisions_non_empty"] = True
        except Exception:
            pass

        records, raw_lines = parse_jsonl_records(decisions_path)
        # Validate each line parses and follows exact schema
        required_keys = {"what", "why", "alternatives", "context", "confidence", "type", "reversibility"}
        allowed_confidences = {"certain", "leaning", "uncertain", "forced"}
        allowed_types = {"Technical", "People", "Strategic", "Communication"}
        allowed_reversibility = {"one-way", "two-way"}

        schema_ok = True
        valid_count = 0
        one_way_count = 0
        two_way_count = 0

        if records:
            for obj in records:
                if obj is None or not isinstance(obj, dict):
                    schema_ok = False
                    break
                # Exact keys only
                if set(obj.keys()) != required_keys:
                    schema_ok = False
                    break
                # Field types and values
                if not is_nonempty_string(obj.get("what", None)):
                    schema_ok = False
                    break
                if not is_nonempty_string(obj.get("why", None)):
                    schema_ok = False
                    break
                if not validate_alternatives(obj.get("alternatives", None)):
                    schema_ok = False
                    break
                if not is_nonempty_string(obj.get("context", None)):
                    schema_ok = False
                    break
                if obj.get("confidence", None) not in allowed_confidences:
                    schema_ok = False
                    break
                if obj.get("type", None) not in allowed_types:
                    schema_ok = False
                    break
                if obj.get("reversibility", None) not in allowed_reversibility:
                    schema_ok = False
                    break

                valid_count += 1
                if obj.get("reversibility") == "one-way":
                    one_way_count += 1
                elif obj.get("reversibility") == "two-way":
                    two_way_count += 1
        else:
            schema_ok = False

        if schema_ok and checks["decisions_non_empty"]:
            checks["decisions_valid_schema"] = True

        if valid_count >= 12 and checks["decisions_valid_schema"]:
            checks["decisions_min_count_12"] = True

        if checks["decisions_valid_schema"] and one_way_count >= 2 and two_way_count >= 2:
            checks["decisions_reversibility_min_counts"] = True

        decisions_count = valid_count
    else:
        decisions_count = 0

    # 2) Validate weekly_review.md
    if os.path.isfile(weekly_path):
        checks["weekly_file_exists"] = True
        weekly_text = load_text(weekly_path)
        lines = [ln.rstrip("\n") for ln in weekly_text.splitlines()]
        # Title line: starts with "Decision Week in Review —" followed by a date
        title_ok = False
        for ln in lines:
            if ln.startswith("Decision Week in Review —"):
                # Look for YYYY-MM-DD after the em dash
                m = re.search(r"^Decision Week in Review —\s*\d{4}-\d{2}-\d{2}\b", ln)
                if m:
                    title_ok = True
                    break
        checks["weekly_has_title_date"] = title_ok

        # Decisions made: N equals number of records in decisions.jsonl
        dec_line_num_ok = False
        for ln in lines:
            if ln.startswith("Decisions made:"):
                # extract integer
                m = re.search(r"Decisions made:\s*(\d+)\b", ln)
                if m:
                    try:
                        n = int(m.group(1))
                        if n == decisions_count:
                            dec_line_num_ok = True
                    except Exception:
                        pass
                break
        checks["weekly_decisions_count_matches"] = dec_line_num_ok

        # Category lines
        cat_required = ["  → Technical", "  → People", "  → Strategic", "  → Communication"]
        has_cats = all(any(ln.startswith(req) for ln in lines) for req in cat_required)
        checks["weekly_has_category_lines"] = has_cats

        # Worth watching and Pattern signal lines with non-empty content after colon
        worth_ok = False
        pattern_ok = False
        for ln in lines:
            if ln.startswith("Worth watching:"):
                after = ln.split("Worth watching:", 1)[1].strip()
                if len(after) > 0:
                    worth_ok = True
            if ln.startswith("Pattern signal:"):
                after = ln.split("Pattern signal:", 1)[1].strip()
                if len(after) > 0:
                    pattern_ok = True
        checks["weekly_has_worth_watching"] = worth_ok
        checks["weekly_has_pattern_signal"] = pattern_ok

    # 3) Validate patterns.md (required if >=10 decisions)
    patterns_required = decisions_count >= 10
    if patterns_required and os.path.isfile(patterns_path):
        checks["patterns_required_and_exists"] = True
        ptxt = load_text(patterns_path)
        ptxt_lower = ptxt.lower()

        # Contains at least one axis phrase
        axis_ok = ("Speed vs. Deliberation" in ptxt) or ("Conservative vs. Aggressive" in ptxt)
        checks["patterns_has_axis_or"] = axis_ok

        # Contains at least one bias term (case-insensitive)
        bias_terms = ["Confirmation bias", "Sunk cost", "Optimism bias", "Availability bias", "Recency bias"]
        bias_ok = False
        for term in bias_terms:
            if term.lower() in ptxt_lower:
                bias_ok = True
                break
        checks["patterns_has_bias_mention"] = bias_ok
    elif patterns_required:
        # Required but missing
        checks["patterns_required_and_exists"] = False

    # 4) Validate summary.csv
    if os.path.isfile(summary_path):
        checks["summary_file_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                rows = [ln.rstrip("\n") for ln in f.readlines()]
        except Exception:
            rows = []
        if rows:
            header_ok = rows[0] == "type,total,one_way,two_way"
            checks["summary_header_ok"] = header_ok

            data_rows = rows[1:]
            # 1 to 4 data rows
            if 1 <= len(data_rows) <= 4:
                checks["summary_rows_count_ok"] = True
            # Validate each row has correct format and non-negative integers in columns 2-4
            values_ok = True
            for r in data_rows:
                parts = r.split(",")
                if len(parts) != 4:
                    values_ok = False
                    break
                # parts[0] type can be any non-empty string
                if len(parts[0].strip()) == 0:
                    values_ok = False
                    break
                # Validate numeric columns
                for idx in [1, 2, 3]:
                    try:
                        val = int(parts[idx])
                        if val < 0:
                            values_ok = False
                            break
                    except Exception:
                        values_ok = False
                        break
                if not values_ok:
                    break
            if values_ok and checks["summary_header_ok"] and checks["summary_file_exists"]:
                checks["summary_rows_values_ok"] = True

    # Compute reward
    # Baseline: if decisions.jsonl missing, reward must be 0.0
    if not checks["decisions_file_exists"]:
        reward = 0.0
    else:
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Avoid division by zero; total > 0 guaranteed
        reward = passed / float(total) if total > 0 else 0.0

    # Print single JSON line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    # Ensure only one JSON object on last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()