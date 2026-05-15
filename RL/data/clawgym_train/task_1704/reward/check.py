import json
import os
import re
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def load_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    return None, "invalid_jsonl"
        return items, None
    except Exception as e:
        return None, str(e)

def normalize_failure_type(s):
    if not isinstance(s, str):
        return ""
    s = s.strip().lower()
    s = s.replace("/", " ").replace("-", " ").replace(" ", "_")
    # Map some variants to canonical
    if s.startswith("string"):
        return "stringing"
    if s.startswith("warp"):
        return "warping"
    if "layer" in s and ("adhesion" in s or "delamination" in s or "delam" in s):
        return "layer_adhesion"
    if "first" in s and "layer" in s:
        return "first_layer"
    if "ring" in s or "ghost" in s or "vibration" in s:
        return "ringing"
    # return as-is if matches known
    if s in {"stringing", "warping", "layer_adhesion", "first_layer", "ringing"}:
        return s
    return s

def expected_failure_from_id_or_desc(case_id, description):
    # Prefer id mapping if matches case1..case5
    if isinstance(case_id, str):
        m = re.match(r"case\s*([1-5])", case_id.strip().lower())
        if m:
            idx = int(m.group(1))
            mapping = {
                1: "stringing",
                2: "warping",
                3: "layer_adhesion",
                4: "first_layer",
                5: "ringing",
            }
            return mapping.get(idx, "")
    # Keyword-based mapping fallback
    desc = (description or "").lower()
    # Order is important to disambiguate
    if any(k in desc for k in ["ringing", "ghosting", "vibration", "rippl", "echo"]):
        return "ringing"
    if any(k in desc for k in ["first layer", "first-layer", "firstlayer", "initial layer", "not sticking first", "z offset", "z-offset"]):
        return "first_layer"
    if any(k in desc for k in ["delamination", "layer adhesion", "layer split", "split along layer", "crack along layer", "layer separation"]):
        return "layer_adhesion"
    if any(k in desc for k in ["warp", "warping", "corner lift", "lifting", "peel", "detaching", "pop off"]):
        return "warping"
    if any(k in desc for k in ["string", "stringing", "wispy", "hair", "cobweb", "ooze"]):
        return "stringing"
    return ""

def any_key_matches(d, patterns):
    if not isinstance(d, dict):
        return False
    keys = [str(k).lower() for k in d.keys()]
    for k in keys:
        for pat in patterns:
            if isinstance(pat, str):
                if pat in k:
                    return True
            else:
                if pat.search(k):
                    return True
    return False

def fix_has_groups_for_failure(fix_dict, failure_type):
    # Each failure_type requires two param groups to be present in the given fix dict
    # We will match using case-insensitive substrings/regex on keys
    if not isinstance(fix_dict, dict):
        return False
    ft = normalize_failure_type(failure_type)
    if ft == "stringing":
        group1 = [re.compile(r"retract.*(dist|len|length)"), re.compile(r"retract.*speed")]
        group2 = [re.compile(r"temp"), re.compile(r"travel.*speed"), re.compile(r"wipe")]
        has_g1 = any_key_matches(fix_dict, group1)
        has_g2 = any_key_matches(fix_dict, group2)
        return has_g1 and has_g2
    if ft == "warping":
        group1 = [re.compile(r"\bbrim\b"), re.compile(r"brim.*width"), re.compile(r"mouse.*ear")]
        group2 = [re.compile(r"bed.*temp"), re.compile(r"fan.*(first|initial).*layer"), re.compile(r"fan_speed_first_layers")]
        has_g1 = any_key_matches(fix_dict, group1)
        has_g2 = any_key_matches(fix_dict, group2)
        return has_g1 and has_g2
    if ft == "layer_adhesion":
        group1 = [re.compile(r"temp"), re.compile(r"fan")]
        group2 = [re.compile(r"print.*speed"), re.compile(r"layer.*height")]
        has_g1 = any_key_matches(fix_dict, group1)
        has_g2 = any_key_matches(fix_dict, group2)
        return has_g1 and has_g2
    if ft == "first_layer":
        group1 = [re.compile(r"first.*layer.*height"), re.compile(r"first.*layer.*speed"), re.compile(r"\bz.*offset")]
        group2 = [re.compile(r"bed.*temp"), re.compile(r"first.*layer.*flow"), re.compile(r"initial.*layer.*flow")]
        has_g1 = any_key_matches(fix_dict, group1)
        has_g2 = any_key_matches(fix_dict, group2)
        return has_g1 and has_g2
    if ft == "ringing":
        group1 = [re.compile(r"perimeter.*speed"), re.compile(r"\bspeed\b")]
        group2 = [re.compile(r"accel"), re.compile(r"\bjerk\b")]
        has_g1 = any_key_matches(fix_dict, group1)
        has_g2 = any_key_matches(fix_dict, group2)
        return has_g1 and has_g2
    # Unknown failure types: cannot verify
    return False

def is_number(v):
    return isinstance(v, (int, float))

def contains_phrase_ci(text, phrase):
    return phrase.lower() in text.lower()

def contains_regex(text, pattern):
    return re.search(pattern, text, re.IGNORECASE) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "diagnoses_exists": False,
        "diagnoses_valid_json": False,
        "diagnoses_length_match": False,
        "diagnoses_required_fields": False,
        "diagnoses_ranked_min3": False,
        "diagnoses_confidences_valid": False,
        "diagnoses_top_failure_expected": False,
        "fixes_all_slicers_present": False,
        "fixes_params_top_failure_per_slicer": False,
        "failure_log_exists": False,
        "failure_log_valid_json": False,
        "failure_log_has_entries_for_all_ids": False,
        "failure_log_consistent_with_diagnoses": False,
        "report_exists": False,
        "report_has_summary_and_top_recurring": False,
        "report_mentions_all_failures": False,
        "report_mentions_printer_material_combo": False,
    }

    # Load input cases
    input_path = os.path.join(input_dir, "print_failures.jsonl")
    input_cases, input_err = load_jsonl(input_path)
    if input_cases is None:
        # Without input, cannot verify lengths or expectations
        n_cases = 0
        ids = []
        printer_material_pairs = []
    else:
        n_cases = len(input_cases)
        ids = []
        printer_material_pairs = []
        for item in input_cases:
            cid = item.get("id")
            ids.append(cid)
            printer = item.get("printer", "")
            material = item.get("material", "")
            if isinstance(printer, str) and isinstance(material, str):
                printer_material_pairs.append((printer.strip(), material.strip()))

    # 1) diagnoses.json checks
    diagnoses_path = os.path.join(output_dir, "diagnoses.json")
    if os.path.isfile(diagnoses_path):
        checks["diagnoses_exists"] = True
        diagnoses, err = load_json(diagnoses_path)
        if isinstance(diagnoses, list):
            checks["diagnoses_valid_json"] = True
            if n_cases > 0 and len(diagnoses) == n_cases:
                checks["diagnoses_length_match"] = True

            # Check required fields and structures
            required_fields_ok = True
            ranked_min3_ok = True
            confidences_ok = True
            top_failure_expected_ok = True
            fixes_slicers_ok = True
            fixes_params_ok = True

            # Build a map id -> top failure for later comparison
            top_failures_by_id = {}
            # For each case, check
            for i, item in enumerate(diagnoses):
                # Required keys
                for key in ["id", "printer", "material", "description", "ranked_diagnoses", "top_causes", "fixes"]:
                    if key not in item:
                        required_fields_ok = False
                        break
                if not required_fields_ok:
                    break

                # ranked_diagnoses >= 3 and confidences within [0,1]
                rd = item.get("ranked_diagnoses")
                if not isinstance(rd, list) or len(rd) < 3:
                    ranked_min3_ok = False
                else:
                    # confidences
                    for hyp in rd:
                        if not isinstance(hyp, dict):
                            confidences_ok = False
                            break
                        if "failure_type" not in hyp or "confidence" not in hyp:
                            confidences_ok = False
                            break
                        conf = hyp.get("confidence")
                        if not is_number(conf) or not (0.0 <= float(conf) <= 1.0):
                            confidences_ok = False
                            break

                # fixes structure
                fixes = item.get("fixes")
                slicer_keys = ["PrusaSlicer", "Cura", "OrcaSlicer"]
                if not isinstance(fixes, dict) or not all(k in fixes and isinstance(fixes.get(k), dict) for k in slicer_keys):
                    fixes_slicers_ok = False

                # Determine expected failure from input or description
                # Find the corresponding input case by id if possible
                case_id = item.get("id")
                # Attempt to pull description from input if needed; else use diagnoses item description
                desc = item.get("description", "")
                exp = ""
                # If we have input cases, try to find matching id to use its description for determination
                if input_cases is not None and ids:
                    try:
                        idx = ids.index(case_id)
                        source_desc = input_cases[idx].get("description", desc)
                        exp = expected_failure_from_id_or_desc(case_id, source_desc)
                    except ValueError:
                        exp = expected_failure_from_id_or_desc(case_id, desc)
                else:
                    exp = expected_failure_from_id_or_desc(case_id, desc)
                # If cannot determine expected, we'll skip strict check for this item
                if exp:
                    top = rd[0] if isinstance(rd, list) and rd else {}
                    top_ft = normalize_failure_type(top.get("failure_type", ""))
                    if normalize_failure_type(exp) != top_ft:
                        top_failure_expected_ok = False
                    else:
                        # For fixes param groups, ensure each slicer has required keys for this top failure
                        if isinstance(fixes, dict):
                            for sk in slicer_keys:
                                if sk in fixes and isinstance(fixes.get(sk), dict):
                                    if not fix_has_groups_for_failure(fixes[sk], exp):
                                        fixes_params_ok = False
                                else:
                                    fixes_params_ok = False
                        else:
                            fixes_params_ok = False

                # top_causes length >= 2
                tc = item.get("top_causes")
                if not isinstance(tc, list) or len(tc) < 2:
                    required_fields_ok = False

                # Record top failure by id
                top_failures_by_id[case_id] = normalize_failure_type(rd[0]["failure_type"]) if isinstance(rd, list) and rd and isinstance(rd[0], dict) and "failure_type" in rd[0] else ""

            if required_fields_ok:
                checks["diagnoses_required_fields"] = True
            if ranked_min3_ok:
                checks["diagnoses_ranked_min3"] = True
            if confidences_ok:
                checks["diagnoses_confidences_valid"] = True
            if top_failure_expected_ok and n_cases > 0:
                checks["diagnoses_top_failure_expected"] = True
            if fixes_slicers_ok:
                checks["fixes_all_slicers_present"] = True
            if fixes_params_ok and n_cases > 0:
                checks["fixes_params_top_failure_per_slicer"] = True

            # Store for later
            diagnoses_top_by_id = top_failures_by_id
        else:
            # not a list
            diagnoses_top_by_id = {}
        diagnoses_data = diagnoses if isinstance(diagnoses, list) else []
    else:
        diagnoses_top_by_id = {}
        diagnoses_data = []

    # 2) failure-log.json checks
    fl_path = os.path.join(output_dir, "failure-log.json")
    if os.path.isfile(fl_path):
        checks["failure_log_exists"] = True
        fl_json, err = load_json(fl_path)
        if isinstance(fl_json, dict) and isinstance(fl_json.get("failures"), list):
            checks["failure_log_valid_json"] = True
            fl_entries = fl_json.get("failures")
            # must have >= n_cases and exactly one per input id
            if n_cases > 0:
                ids_set = set(ids)
                found_ids = [e.get("id") for e in fl_entries if isinstance(e, dict)]
                # exactly one per id: same set and count equal to n_cases
                unique_found = set([fid for fid in found_ids if fid is not None])
                has_all = ids_set.issubset(unique_found) and len([fid for fid in found_ids if fid in ids_set]) >= n_cases
                # ensure exactly one per input id
                exact_once = True
                for cid in ids:
                    if found_ids.count(cid) != 1:
                        exact_once = False
                        break
                if has_all and exact_once:
                    # Also verify required keys exist per entry
                    required_ok_all = True
                    for e in fl_entries:
                        if e.get("id") in ids_set:
                            for key in ["printer", "material", "failure_type", "description", "slicer_settings", "fixed_by", "notes"]:
                                if key not in e:
                                    required_ok_all = False
                                    break
                            if not isinstance(e.get("slicer_settings"), dict):
                                required_ok_all = False
                            if not isinstance(e.get("fixed_by"), str) or not isinstance(e.get("notes"), str):
                                required_ok_all = False
                    if required_ok_all:
                        checks["failure_log_has_entries_for_all_ids"] = True

            # Consistency with diagnoses: failure_type matches top-ranked for that id
            consistent = True
            if diagnoses_top_by_id and isinstance(fl_json, dict):
                for e in fl_entries:
                    cid = e.get("id")
                    if cid in diagnoses_top_by_id and diagnoses_top_by_id[cid]:
                        if normalize_failure_type(e.get("failure_type", "")) != diagnoses_top_by_id[cid]:
                            consistent = False
                            break
            if consistent and diagnoses_top_by_id:
                checks["failure_log_consistent_with_diagnoses"] = True
        else:
            fl_entries = []
    else:
        fl_entries = []

    # 3) report.md checks
    report_path = os.path.join(output_dir, "report.md")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        content, err = load_text(report_path)
        if isinstance(content, str):
            # Must contain "Summary" and "Top recurring combinations"
            has_summary = contains_phrase_ci(content, "Summary")
            has_top_rec = contains_phrase_ci(content, "Top recurring combinations")
            if has_summary and has_top_rec:
                checks["report_has_summary_and_top_recurring"] = True

            # Mentions of each expected failure category at least once
            categories_ok = True
            # Check case-insensitive, allow hyphen/space variations for First Layer
            if not contains_phrase_ci(content, "Stringing"): categories_ok = False
            if not contains_phrase_ci(content, "Warping"): categories_ok = False
            if not contains_phrase_ci(content, "Layer Adhesion"): categories_ok = False
            if not contains_regex(content, r"first[\s-]?layer"): categories_ok = False
            if not contains_phrase_ci(content, "Ringing"): categories_ok = False
            if categories_ok:
                checks["report_mentions_all_failures"] = True

            # At least one printer+material combo mention matching an input pair
            combo_ok = False
            if printer_material_pairs:
                for pr, mat in printer_material_pairs:
                    if not pr or not mat:
                        continue
                    # Check variants: "Printer + MATERIAL", "Printer / MATERIAL", "Printer - MATERIAL", "Printer & MATERIAL"
                    patterns = [
                        re.escape(pr) + r"\s*\+\s*" + re.escape(mat),
                        re.escape(pr) + r"\s*/\s*" + re.escape(mat),
                        re.escape(pr) + r"\s*-\s*" + re.escape(mat),
                        re.escape(pr) + r"\s*&\s*" + re.escape(mat),
                    ]
                    for pat in patterns:
                        if contains_regex(content, pat):
                            combo_ok = True
                            break
                    if combo_ok:
                        break
            if combo_ok:
                checks["report_mentions_printer_material_combo"] = True

    # Compute reward: proportion of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output folder missing or all three required artifacts missing, reward must be 0.0
    outputs_present = any(os.path.isfile(os.path.join(output_dir, p)) for p in ["diagnoses.json", "failure-log.json", "report.md"])
    if not outputs_present:
        reward = 0.0

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()