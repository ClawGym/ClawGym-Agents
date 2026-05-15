import json
import os
import re
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def get_nested(obj, keys):
    cur = obj
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur

def coalesce(*vals):
    for v in vals:
        if v is not None:
            return v
    return None

def extract_sections(md_text):
    # Recognize headings possibly with leading hashes/spaces, exact titles
    titles = ["Status", "What changed", "Suggestions", "Missing data"]
    patterns = {t: re.compile(r"^\s*#*\s*" + re.escape(t) + r"\s*$", re.IGNORECASE) for t in titles}
    sections = {t: "" for t in titles}
    order = []
    current = None
    lines = md_text.splitlines()
    for line in lines:
        matched_title = None
        for t, pat in patterns.items():
            if pat.match(line):
                matched_title = t
                break
        if matched_title:
            current = matched_title
            if matched_title not in order:
                order.append(matched_title)
            continue
        if current:
            sections[current] += (line + "\n")
    # Trim trailing newline
    for t in sections:
        sections[t] = sections[t].rstrip("\n")
    return sections, order

def count_sentences(text):
    if not text:
        return 0
    # Count sentence terminators ., !, ?
    return len(re.findall(r"[\.!\?]", text))

def suggestions_numbered_items(text):
    items = []
    for line in text.splitlines():
        m = re.match(r"^\s*([0-9]+)\.\s+(.+?)\s*$", line)
        if m:
            num = int(m.group(1))
            content = m.group(2).strip()
            if content:
                items.append((num, content))
    return items

def approx_equal(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def is_int(val):
    return isinstance(val, int) and not isinstance(val, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "md_exists": False,
        "md_has_all_sections": False,
        "md_status_1_2_sentences": False,
        "md_suggestions_numbered_3": False,
        "md_missing_data_mentions_and_phrase": False,
        "json_exists": False,
        "json_valid": False,
        "json_required_keys_present": False,
        "json_date_correct": False,
        "json_suggestions_len3": False,
        "json_missing_data_includes_required": False,
        "json_deltas_fields_present": False,
        "json_deltas_values_match": False
    }

    # Paths
    input_path = os.path.join(input_dir, "apple_health_daily_2026-04-15.json")
    md_path = os.path.join(output_dir, "daily_brief_2026-04-15.md")
    json_path = os.path.join(output_dir, "daily_brief_2026-04-15.json")

    # Load input reference (for expected values)
    input_data = load_json(input_path)

    # Determine missing metrics from input (only if input exists)
    missing_metrics = set()
    expected_values = {}
    if isinstance(input_data, dict):
        # Extract day and baseline values
        day_steps = coalesce(get_nested(input_data, ["day", "steps"]), input_data.get("steps"))
        day_sleep_hours = coalesce(get_nested(input_data, ["day", "sleep_duration_hours"]), input_data.get("sleep_duration_hours"))

        baseline_steps = coalesce(get_nested(input_data, ["baseline", "steps_avg_7d"]), input_data.get("steps_avg_7d"))
        baseline_sleep_hours = coalesce(get_nested(input_data, ["baseline", "sleep_duration_avg_7d"]), input_data.get("sleep_duration_avg_7d"))

        # Optional metrics presence
        rhr = coalesce(get_nested(input_data, ["day", "resting_heart_rate"]), input_data.get("resting_heart_rate"))
        hrv = coalesce(get_nested(input_data, ["day", "hrv"]), input_data.get("hrv"))
        deep_sleep = coalesce(
            get_nested(input_data, ["day", "deep_sleep_duration"]),
            input_data.get("deep_sleep_duration"),
            get_nested(input_data, ["day", "deep_sleep_duration_hours"]),
            input_data.get("deep_sleep_duration_hours")
        )

        if rhr is None:
            missing_metrics.add("resting_heart_rate")
        if hrv is None:
            missing_metrics.add("hrv")
        if deep_sleep is None:
            missing_metrics.add("deep_sleep_duration")

        # Compute expected deltas if possible
        try:
            if day_steps is not None and baseline_steps is not None and isinstance(baseline_steps, (int, float)):
                steps_delta_exact = float(day_steps) - float(baseline_steps)
                expected_values["steps_delta_int"] = int(round(steps_delta_exact))
                if float(baseline_steps) != 0.0:
                    expected_values["steps_percent_change"] = (steps_delta_exact / float(baseline_steps)) * 100.0
            if day_sleep_hours is not None and baseline_sleep_hours is not None and isinstance(baseline_sleep_hours, (int, float)):
                sleep_delta_exact = float(day_sleep_hours) - float(baseline_sleep_hours)
                expected_values["sleep_delta_hours"] = sleep_delta_exact
                if float(baseline_sleep_hours) != 0.0:
                    expected_values["sleep_percent_change"] = (sleep_delta_exact / float(baseline_sleep_hours)) * 100.0
        except Exception:
            expected_values = {}

    # Check Markdown file
    md_text = read_text(md_path)
    if md_text is not None:
        checks["md_exists"] = True
        sections, order = extract_sections(md_text)
        required_sections = ["Status", "What changed", "Suggestions", "Missing data"]
        if all(sections.get(s, "") is not None and (re.search(r"\S", sections.get(s, "")) is not None or True) for s in required_sections):
            # Presence is determined by discovery of headings; ensure headings found at least once
            has_all = True
            for s in required_sections:
                # a heading is present if it appears in order list
                if s not in order:
                    has_all = False
                    break
            checks["md_has_all_sections"] = has_all

        # Status sentences 1-2
        status_content = sections.get("Status", "") if sections else ""
        sent_count = count_sentences(status_content)
        if sent_count >= 1 and sent_count <= 2:
            checks["md_status_1_2_sentences"] = True

        # Suggestions exactly 3 numbered 1., 2., 3.
        sugg_content = sections.get("Suggestions", "") if sections else ""
        items = suggestions_numbered_items(sugg_content)
        nums = [n for n, _ in items]
        if len(items) == 3 and nums == [1, 2, 3] and all(v.strip() for _, v in items):
            checks["md_suggestions_numbered_3"] = True

        # Missing data mentions and phrase 'insufficient data' for each missing metric
        miss_content = sections.get("Missing data", "") if sections else ""
        miss_lower = miss_content.lower()
        md_mentions_ok = True
        if isinstance(input_data, dict):
            if len(missing_metrics) > 0:
                # Must include phrase 'insufficient data'
                if "insufficient data" not in miss_lower:
                    md_mentions_ok = False
                # Check mentions for each metric
                if "resting_heart_rate" in missing_metrics:
                    if not ("resting heart rate" in miss_lower):
                        md_mentions_ok = False
                if "hrv" in missing_metrics:
                    # Accept HRV (case-insensitive)
                    if not ("hrv" in miss_lower):
                        md_mentions_ok = False
                if "deep_sleep_duration" in missing_metrics:
                    if not ("deep sleep" in miss_lower):
                        md_mentions_ok = False
            else:
                # No missing metrics; do not require phrase
                md_mentions_ok = True
        else:
            # If input missing, cannot verify positively
            md_mentions_ok = False
        checks["md_missing_data_mentions_and_phrase"] = md_mentions_ok

    # Check JSON output file
    out_json = load_json(json_path)
    if out_json is not None:
        checks["json_exists"] = True
        checks["json_valid"] = True if isinstance(out_json, dict) else False

        if isinstance(out_json, dict):
            required_top_keys = ["date", "status_summary", "deltas", "suggestions", "missing_data"]
            if all(k in out_json for k in required_top_keys):
                checks["json_required_keys_present"] = True

            # Date
            if str(out_json.get("date")) == "2026-04-15":
                checks["json_date_correct"] = True

            # Suggestions array length 3
            sugg = out_json.get("suggestions")
            if isinstance(sugg, list) and len(sugg) == 3 and all(isinstance(x, str) and x.strip() for x in sugg):
                checks["json_suggestions_len3"] = True

            # missing_data includes required missing metrics (from input)
            md_arr = out_json.get("missing_data")
            missing_json_ok = False
            if isinstance(input_data, dict) and isinstance(md_arr, list):
                missing_json_ok = True
                for m in missing_metrics:
                    if m not in md_arr:
                        missing_json_ok = False
                        break
            checks["json_missing_data_includes_required"] = missing_json_ok

            # deltas fields present and types
            deltas = out_json.get("deltas", {})
            deltas_present = all(k in deltas for k in ["steps_delta", "steps_percent_change", "sleep_delta_hours", "sleep_percent_change"])
            checks["json_deltas_fields_present"] = bool(deltas_present)

            # deltas values match expected within tolerance
            deltas_match = False
            if isinstance(input_data, dict) and isinstance(deltas, dict) and deltas_present and expected_values:
                try:
                    sd = deltas.get("steps_delta")
                    sp = deltas.get("steps_percent_change")
                    sh = deltas.get("sleep_delta_hours")
                    shp = deltas.get("sleep_percent_change")

                    # types: steps_delta should be int, others numbers
                    types_ok = is_int(sd) and isinstance(sp, (int, float)) and isinstance(sh, (int, float)) and isinstance(shp, (int, float))

                    # Compare with tolerances
                    comp_ok = True
                    if "steps_delta_int" in expected_values:
                        comp_ok = comp_ok and abs(int(round(expected_values["steps_delta_int"])) - int(sd)) <= 1
                    else:
                        comp_ok = False
                    if "steps_percent_change" in expected_values:
                        comp_ok = comp_ok and approx_equal(sp, expected_values["steps_percent_change"], 0.5)
                    else:
                        comp_ok = False
                    if "sleep_delta_hours" in expected_values:
                        comp_ok = comp_ok and approx_equal(sh, expected_values["sleep_delta_hours"], 0.1)
                    else:
                        comp_ok = False
                    if "sleep_percent_change" in expected_values:
                        comp_ok = comp_ok and approx_equal(shp, expected_values["sleep_percent_change"], 0.5)
                    else:
                        comp_ok = False

                    deltas_match = types_ok and comp_ok
                except Exception:
                    deltas_match = False
            checks["json_deltas_values_match"] = deltas_match

    # Compute reward: average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Ensure no-op baseline yields 0 if outputs missing
    if not os.path.isfile(md_path) and not os.path.isfile(json_path):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()