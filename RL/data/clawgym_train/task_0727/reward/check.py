import json
import os
import sys
import re
import csv
from collections import defaultdict, OrderedDict

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Evaluation constants (deterministic)
    CAP = 5  # enforced cap for evaluation
    STOPWORDS = {"the", "and", "of", "news"}  # evaluation stopwords
    KEYWORD_PATTERN = re.compile(r"^[a-z0-9\- ]+$")
    ALERT_NAME_PATTERN = re.compile(r"^[a-z0-9_]+_news_alert$")

    checks = OrderedDict([
        ("alerts_exists", False),
        ("alerts_non_empty", False),
        ("alerts_valid_json_lines", False),
        ("alerts_schema_fields", False),
        ("alert_name_pattern", False),
        ("keywords_non_empty_and_cap", False),
        ("keywords_chars_lowercase_ok", False),
        ("keywords_sorted_unique", False),
        ("keywords_no_stopwords", False),
        ("report_exists", False),
        ("report_header_ok", False),
        ("report_rows_count_match", False),
        ("report_num_keywords_correct", False),
        ("report_keywords_joined_match", False),
        ("global_exists", False),
        ("global_valid_object", False),
        ("global_matches_recomputed", False),
        ("readme_exists", False),
        ("readme_has_sections", False),
        ("readme_len_ok", False),
    ])

    alerts_path = os.path.join(output_dir, "alerts.jsonl")
    report_path = os.path.join(output_dir, "report.csv")
    global_path = os.path.join(output_dir, "global_keywords.json")
    readme_path = os.path.join(output_dir, "README.md")

    alerts = []
    # 1) alerts.jsonl checks
    if os.path.isfile(alerts_path):
        checks["alerts_exists"] = True
        try:
            with open(alerts_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            nonblank_lines = [ln for ln in lines if ln.strip() != ""]
            if len(nonblank_lines) > 0:
                checks["alerts_non_empty"] = True
            # Parse JSON lines
            parsed_ok = True
            temp_alerts = []
            for ln in nonblank_lines:
                try:
                    obj = json.loads(ln)
                    temp_alerts.append(obj)
                except Exception:
                    parsed_ok = False
                    break
            if parsed_ok and len(temp_alerts) > 0:
                alerts = temp_alerts
                checks["alerts_valid_json_lines"] = True
        except Exception:
            # Leave checks as False where appropriate
            pass

    # Further alerts checks only if valid JSON lines parsed
    if checks["alerts_valid_json_lines"]:
        # Schema fields and types
        schema_ok = True
        name_pat_ok = True
        kw_len_ok = True
        kw_chars_ok = True
        kw_sorted_unique_ok = True
        kw_no_stop_ok = True

        for obj in alerts:
            # Schema
            if not (isinstance(obj, dict)
                    and isinstance(obj.get("alert_name"), str)
                    and isinstance(obj.get("department_id"), str)
                    and isinstance(obj.get("notify"), bool)
                    and isinstance(obj.get("keywords"), list)):
                schema_ok = False
                # No need to continue checking other fields if schema invalid for one
                # But continue to consume all to keep deterministic
            # alert_name pattern
            an = obj.get("alert_name")
            if not (isinstance(an, str) and ALERT_NAME_PATTERN.fullmatch(an or "")):
                name_pat_ok = False

            # keywords list conditions
            kws = obj.get("keywords")
            if not isinstance(kws, list) or len(kws) < 1 or len(kws) > CAP:
                kw_len_ok = False
            else:
                # characters and lowercase check
                for k in kws:
                    if not isinstance(k, str):
                        kw_chars_ok = False
                        break
                    if k != k.strip():
                        kw_chars_ok = False
                        break
                    if k != k.lower():
                        kw_chars_ok = False
                        break
                    if not KEYWORD_PATTERN.fullmatch(k):
                        kw_chars_ok = False
                        break
                # sorted and unique
                if kws != sorted(kws):
                    kw_sorted_unique_ok = False
                if len(set(kws)) != len(kws):
                    kw_sorted_unique_ok = False
                # stopwords
                for k in kws:
                    if k in STOPWORDS:
                        kw_no_stop_ok = False
                        break

        checks["alerts_schema_fields"] = schema_ok
        checks["alert_name_pattern"] = name_pat_ok
        checks["keywords_non_empty_and_cap"] = kw_len_ok
        checks["keywords_chars_lowercase_ok"] = kw_chars_ok
        checks["keywords_sorted_unique"] = kw_sorted_unique_ok
        checks["keywords_no_stopwords"] = kw_no_stop_ok

    # 2) report.csv checks
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["department_id", "alert_name", "notify", "num_keywords", "keywords_joined"]
                if header == expected_header:
                    checks["report_header_ok"] = True

            # Only proceed if alerts parsed and header ok
            if checks["alerts_valid_json_lines"] and checks["report_header_ok"]:
                data_rows = rows[1:]
                # Use DictReader to ensure field access by name
                with open(report_path, "r", encoding="utf-8", newline="") as f2:
                    dict_reader = csv.DictReader(f2)
                    dict_rows = list(dict_reader)

                # count match
                if len(dict_rows) == len(alerts):
                    checks["report_rows_count_match"] = True

                # Build index for rows by (department_id, alert_name)
                row_index = {}
                for r in dict_rows:
                    key = (r.get("department_id", ""), r.get("alert_name", ""))
                    row_index[key] = r

                num_kw_ok = True
                kw_join_ok = True
                for a in alerts:
                    key = (a.get("department_id", ""), a.get("alert_name", ""))
                    if key not in row_index:
                        num_kw_ok = False
                        kw_join_ok = False
                        break
                    r = row_index[key]
                    # num_keywords check
                    try:
                        nk = int(r.get("num_keywords", "").strip()) if r.get("num_keywords") is not None else None
                    except Exception:
                        nk = None
                    if nk != len(a.get("keywords", [])):
                        num_kw_ok = False
                    # keywords_joined check
                    joined = ";".join(a.get("keywords", []))
                    if r.get("keywords_joined", "") != joined:
                        kw_join_ok = False

                checks["report_num_keywords_correct"] = num_kw_ok
                checks["report_keywords_joined_match"] = kw_join_ok

        except Exception:
            # leave related checks as False
            pass

    # 3) global_keywords.json checks
    if os.path.isfile(global_path):
        checks["global_exists"] = True
        try:
            with open(global_path, "r", encoding="utf-8") as f:
                global_obj = json.load(f)
            # validate object shape
            valid_obj = isinstance(global_obj, dict)
            if valid_obj:
                for k, v in global_obj.items():
                    if not isinstance(k, str) or not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                        valid_obj = False
                        break
            checks["global_valid_object"] = valid_obj

            # match recomputed
            if checks["alerts_valid_json_lines"] and valid_obj:
                recomputed = defaultdict(set)
                for a in alerts:
                    dep = a.get("department_id", "")
                    for kw in a.get("keywords", []):
                        recomputed[kw].add(dep)
                recomputed_final = {k: sorted(list(v)) for k, v in recomputed.items()}

                # Compare keys and exact lists
                match_ok = True
                if set(recomputed_final.keys()) != set(global_obj.keys()):
                    match_ok = False
                else:
                    for k in recomputed_final.keys():
                        if k not in global_obj:
                            match_ok = False
                            break
                        v_expected = recomputed_final[k]
                        v_got = global_obj[k]
                        if v_expected != v_got:
                            match_ok = False
                            break
                checks["global_matches_recomputed"] = match_ok

        except Exception:
            # keep defaults
            pass

    # 4) README.md checks
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                content = f.read()
            lower = content.lower()
            if ("approach" in lower) and ("assumptions" in lower) and ("next steps" in lower):
                checks["readme_has_sections"] = True
            if len(content) >= 600:
                checks["readme_len_ok"] = True
        except Exception:
            pass

    # Calculate reward as average of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Ensure baseline of 0.0 if output directory missing or empty
    # If no output files exist, passed will be 0 anyway
    reward = (passed / total_checks) if total_checks > 0 else 0.0
    # Clamp to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = OrderedDict()
    result["reward"] = reward
    for k, v in checks.items():
        result[k] = v
    print(json.dumps(result))

if __name__ == "__main__":
    main()