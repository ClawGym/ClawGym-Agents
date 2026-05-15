import json
import os
import sys
import csv

def read_input_serials(input_csv_path):
    serials = []
    try:
        with open(input_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if "serial" not in reader.fieldnames:
                return serials
            for row in reader:
                s = (row.get("serial") or "").strip()
                if s:
                    serials.append(s)
    except Exception:
        pass
    return serials

def read_jsonl(path):
    objs = []
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line == "":
                    continue
                lines.append(line)
                try:
                    obj = json.loads(line)
                    objs.append(obj)
                except Exception:
                    return lines, None  # invalid JSON line
        return lines, objs
    except Exception:
        return [], None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    input_csv = os.path.join(input_dir, "serials.csv")
    decoded_path = os.path.join(output_dir, "decoded.jsonl")
    metrics_path = os.path.join(output_dir, "metrics.json")
    summary_path = os.path.join(output_dir, "summary.md")

    # Expected serials derived from task (also cross-check with input file)
    expected_serials = read_input_serials(input_csv)
    # Fallback if input cannot be read (but still only score based on outputs)
    if not expected_serials:
        expected_serials = [
            "C02JK3AADKQ2",
            "C07HL9ZZDL41",
            "C6KSMAXYHG7H",
            "K4PMWCGJT4",
            "X9L2M7QPA6",
            "356789012345678",
        ]

    # 1) decoded.jsonl checks
    checks["decoded_exists"] = os.path.isfile(decoded_path)
    decoded_lines, decoded_objs = ([], None)
    if checks["decoded_exists"]:
        decoded_lines, decoded_objs = read_jsonl(decoded_path)
    checks["decoded_valid_jsonl"] = decoded_objs is not None and isinstance(decoded_objs, list)

    # Build map by serial if valid
    by_serial = {}
    all_formats_valid = True
    allowed_formats = {"old_12char", "new_randomized", "imei"}
    if checks["decoded_valid_jsonl"]:
        # Count lines must match number of input serials
        checks["decoded_count_matches_input"] = (len(decoded_lines) == len(expected_serials))
        # Ensure each line has required fields and formats allowed
        missing_sf = False
        for obj in decoded_objs:
            s = obj.get("serial")
            f = obj.get("format")
            if not isinstance(s, str) or not isinstance(f, str):
                missing_sf = True
                continue
            by_serial[s] = obj
            if f not in allowed_formats:
                all_formats_valid = False
        checks["decoded_has_serial_and_format"] = not missing_sf
        # Serial set should match input set (order-insensitive)
        decoded_serial_set = set(by_serial.keys())
        input_serial_set = set([s.strip() for s in expected_serials])
        checks["decoded_serials_match_input_set"] = (decoded_serial_set == input_serial_set)
        checks["decoded_formats_allowed"] = all_formats_valid
    else:
        checks["decoded_count_matches_input"] = False
        checks["decoded_has_serial_and_format"] = False
        checks["decoded_serials_match_input_set"] = False
        checks["decoded_formats_allowed"] = False

    # Specific serial validations for old-format ones
    # C02JK3AADKQ2
    c02 = by_serial.get("C02JK3AADKQ2")
    checks["c02_present"] = c02 is not None
    checks["c02_format_old"] = bool(c02 and c02.get("format") == "old_12char")
    checks["c02_loc_code"] = bool(c02 and isinstance(c02.get("manufacturing_location"), dict) and c02["manufacturing_location"].get("code") == "C02")
    checks["c02_year_2012"] = bool(c02 and isinstance(c02.get("manufacture_date"), dict) and c02["manufacture_date"].get("year") == 2012)
    di = c02.get("device_info") if c02 else None
    checks["c02_device_identifier"] = bool(di and isinstance(di, dict) and di.get("model_identifier") == "MacBookPro10,1")
    # device_name contains 'MacBook Pro 15" Retina Mid-2012'
    dn = di.get("device_name") if isinstance(di, dict) else None
    checks['c02_device_name_contains'] = bool(isinstance(dn, str) and 'MacBook Pro 15" Retina Mid-2012' in dn)

    # C07HL9ZZDL41
    c07 = by_serial.get("C07HL9ZZDL41")
    checks["c07_present"] = c07 is not None
    checks["c07_format_old"] = bool(c07 and c07.get("format") == "old_12char")
    checks["c07_loc_code"] = bool(c07 and isinstance(c07.get("manufacturing_location"), dict) and c07["manufacturing_location"].get("code") == "C07")
    checks["c07_year_2012"] = bool(c07 and isinstance(c07.get("manufacture_date"), dict) and c07["manufacture_date"].get("year") == 2012)
    di7 = c07.get("device_info") if c07 else None
    checks["c07_device_identifier"] = bool(di7 and isinstance(di7, dict) and di7.get("model_identifier") == "MacBookPro9,1")
    dn7 = di7.get("device_name") if isinstance(di7, dict) else None
    checks['c07_device_name_contains'] = bool(isinstance(dn7, str) and 'MacBook Pro 15" Mid-2012' in dn7)

    # C6KSMAXYHG7H
    c6k = by_serial.get("C6KSMAXYHG7H")
    checks["c6k_present"] = c6k is not None
    checks["c6k_format_old"] = bool(c6k and c6k.get("format") == "old_12char")
    checks["c6k_loc_code"] = bool(c6k and isinstance(c6k.get("manufacturing_location"), dict) and c6k["manufacturing_location"].get("code") == "C6K")
    checks["c6k_year_2016"] = bool(c6k and isinstance(c6k.get("manufacture_date"), dict) and c6k["manufacture_date"].get("year") == 2016)
    di6 = c6k.get("device_info") if c6k else None
    checks["c6k_device_identifier"] = bool(di6 and isinstance(di6, dict) and di6.get("model_identifier") == "iPhone9,1")
    dn6 = di6.get("device_name") if isinstance(di6, dict) else None
    checks['c6k_device_name_contains'] = bool(isinstance(dn6, str) and 'iPhone 7 4.7' in dn6)

    # New randomized serials
    k4 = by_serial.get("K4PMWCGJT4")
    checks["k4_present"] = k4 is not None
    checks["k4_format_new"] = bool(k4 and k4.get("format") == "new_randomized")

    x9 = by_serial.get("X9L2M7QPA6")
    checks["x9_present"] = x9 is not None
    checks["x9_format_new"] = bool(x9 and x9.get("format") == "new_randomized")

    # IMEI
    imei = by_serial.get("356789012345678")
    checks["imei_present"] = imei is not None
    checks["imei_format_imei"] = bool(imei and imei.get("format") == "imei")

    # 2) metrics.json checks
    checks["metrics_exists"] = os.path.isfile(metrics_path)
    metrics = load_json(metrics_path) if checks["metrics_exists"] else None
    checks["metrics_valid_json"] = isinstance(metrics, dict)
    checks["metrics_has_keys"] = bool(metrics and all(k in metrics for k in ("total", "old_12char", "new_randomized", "imei")))
    metrics_arrays_match = False
    metrics_total_correct = False
    metrics_total_equals_sum = False
    if checks["metrics_has_keys"]:
        try:
            old_arr = metrics.get("old_12char", [])
            new_arr = metrics.get("new_randomized", [])
            imei_arr = metrics.get("imei", [])
            metrics_arrays_match = (set(old_arr) == {"C02JK3AADKQ2", "C07HL9ZZDL41", "C6KSMAXYHG7H"} and
                                    set(new_arr) == {"K4PMWCGJT4", "X9L2M7QPA6"} and
                                    set(imei_arr) == {"356789012345678"})
            metrics_total_correct = (metrics.get("total") == 6)
            total_sum = len(old_arr) + len(new_arr) + len(imei_arr)
            metrics_total_equals_sum = (metrics.get("total") == total_sum)
        except Exception:
            metrics_arrays_match = False
            metrics_total_correct = False
            metrics_total_equals_sum = False
    checks["metrics_arrays_match"] = metrics_arrays_match
    checks["metrics_total_correct"] = metrics_total_correct
    checks["metrics_total_equals_sum"] = metrics_total_equals_sum

    # 3) summary.md checks
    checks["summary_exists"] = os.path.isfile(summary_path)
    summary_nonempty = False
    summary_has_next_steps = False
    if checks["summary_exists"]:
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                content = f.read()
            summary_nonempty = len(content.strip()) > 0
            # Case-insensitive check for phrase "Next steps"
            summary_has_next_steps = ("next steps" in content.lower())
        except Exception:
            summary_nonempty = False
            summary_has_next_steps = False
    checks["summary_nonempty"] = summary_nonempty
    checks["summary_has_next_steps"] = summary_has_next_steps

    # Compute reward: average of passed checks; ensure 0 if no outputs present
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    # No-op baseline: if output directory missing or empty essential files missing, keep reward 0.0
    essential_present = checks["decoded_exists"] and checks["metrics_exists"] and checks["summary_exists"]
    if total_checks > 0 and essential_present:
        reward = passed / total_checks
        # Ensure within [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()