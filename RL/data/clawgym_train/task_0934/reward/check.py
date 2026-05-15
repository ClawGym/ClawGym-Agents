import json
import os
import sys
import re

def read_json(path):
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

def split_words(text):
    # Count non-empty whitespace-separated tokens
    return [t for t in text.split() if t.strip() != ""]

def get_platforms_map(req_data):
    # Try common container keys first
    if not isinstance(req_data, dict):
        return {}
    for key in ["platforms", "versions", "platform_rules", "platform_requirements", "rules"]:
        val = req_data.get(key)
        if isinstance(val, dict):
            return val
    # Fallback: if root appears to contain platform keys directly
    required = {"linkedin", "speaker_introduction", "website_about", "press_kit", "conference_program"}
    if required.issubset(set(req_data.keys())):
        return req_data
    return {}

def get_int(d, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, int):
            return v
        # Sometimes numeric as string
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                pass
    return None

def get_word_range(d):
    # Supports: [min,max] list, or {"min": x, "max": y}, or {"recommended_word_range": [min,max]}
    if isinstance(d, dict):
        if "recommended_word_range" in d:
            v = d.get("recommended_word_range")
            if isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
                return int(v[0]), int(v[1])
            if isinstance(v, dict):
                mn = v.get("min")
                mx = v.get("max")
                if isinstance(mn, int) and isinstance(mx, int):
                    return mn, mx
        # Alternative keys
        if "word_range" in d:
            v = d.get("word_range")
            if isinstance(v, (list, tuple)) and len(v) == 2:
                try:
                    return int(v[0]), int(v[1])
                except Exception:
                    pass
        mn = d.get("min_words")
        mx = d.get("max_words")
        if isinstance(mn, int) and isinstance(mx, int):
            return mn, mx
    return None

def get_phrases(d):
    # Support multiple possible keys
    for key in ["must_include_phrases", "required_phrases", "must_include"]:
        v = d.get(key)
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            return v
    return []

def get_max_chars(d):
    return get_int(d, ["max_characters", "max_chars", "max_length_chars", "max_len", "character_limit"])

def get_openings_requirements(req_data):
    # Look for openings requirements structure
    if not isinstance(req_data, dict):
        return {}
    # Common keys
    if isinstance(req_data.get("openings_requirements"), dict):
        return req_data["openings_requirements"]
    if isinstance(req_data.get("openings"), dict):
        return req_data["openings"]
    # Flattened
    out = {}
    if "openings_min_count" in req_data:
        out["min_count"] = req_data.get("openings_min_count")
    if "avoid_name_start" in req_data:
        out["avoid_name_start"] = req_data.get("avoid_name_start")
    return out

def normalize(s):
    return s.lower() if isinstance(s, str) else s

def extract_full_name_from_profile(profile):
    if not isinstance(profile, dict):
        return None
    # Try common locations
    for key in ["full_name", "name"]:
        v = profile.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    person = profile.get("person")
    if isinstance(person, dict):
        for key in ["full_name", "name"]:
            v = person.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    # Sometimes nested under "profile" key
    prof = profile.get("profile")
    if isinstance(prof, dict):
        for key in ["full_name", "name"]:
            v = prof.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None

def ends_with_sentence_punct(s):
    return isinstance(s, str) and len(s) > 0 and s.strip().endswith((".", "?"))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "bios_json_exists": False,
        "bios_json_valid": False,
        "person_full_name_present": False,
        "versions_keys_exact": False,
        "all_versions_text_present": False,
        "counts_match": False,
        "length_constraints_met": False,
        "phrases_included": False,
        "openings_structure_valid": False,
        "openings_count_met": False,
        "openings_sentence_rules_met": False,
        "openings_avoid_name_start_met": False,
        "readme_exists": False,
        "readme_has_name": False,
        "readme_lists_platforms": False,
    }

    # Load reference inputs
    profile_path = os.path.join(input_dir, "profile.json")
    platform_req_path = os.path.join(input_dir, "platform_requirements.json")
    profile_data = read_json(profile_path)
    platform_requirements = read_json(platform_req_path)

    # Extract target full name from profile
    profile_full_name = extract_full_name_from_profile(profile_data)

    # Load outputs
    bios_path = os.path.join(output_dir, "bios.json")
    readme_path = os.path.join(output_dir, "README.md")

    bios_data = None
    if os.path.isfile(bios_path):
        checks["bios_json_exists"] = True
        bios_data = read_json(bios_path)
        if isinstance(bios_data, dict):
            checks["bios_json_valid"] = True

    # README
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        readme_text = read_text(readme_path) or ""
    else:
        readme_text = ""

    # Validate bios.json structure
    platforms = ["linkedin", "speaker_introduction", "website_about", "press_kit", "conference_program"]
    versions_obj = None
    if checks["bios_json_valid"]:
        # person.full_name
        person = bios_data.get("person")
        if isinstance(person, dict):
            fn = person.get("full_name")
            if isinstance(fn, str) and fn.strip():
                checks["person_full_name_present"] = True
        # versions
        versions_obj = bios_data.get("versions")
        if isinstance(versions_obj, dict) and set(versions_obj.keys()) == set(platforms):
            checks["versions_keys_exact"] = True

        # text present and counts
        all_text_present = True
        counts_ok = True
        length_ok = True
        phrases_ok = True

        # Prepare platform constraints
        plat_map = get_platforms_map(platform_requirements if isinstance(platform_requirements, dict) else {})

        for p in platforms:
            v = versions_obj.get(p) if isinstance(versions_obj, dict) else None
            if not isinstance(v, dict):
                all_text_present = False
                counts_ok = False
                length_ok = False
                phrases_ok = False
                continue
            text = v.get("text")
            wc = v.get("word_count")
            cc = v.get("char_count")
            if not (isinstance(text, str) and text.strip()):
                all_text_present = False
            # verify counts
            if isinstance(text, str) and isinstance(wc, int) and isinstance(cc, int):
                recomputed_wc = len(split_words(text))
                recomputed_cc = len(text)
                if not (recomputed_wc == wc and recomputed_cc == cc):
                    counts_ok = False
                # enforce constraints if available
                rules = plat_map.get(p, {}) if isinstance(plat_map, dict) else {}
                max_chars = get_max_chars(rules) if isinstance(rules, dict) else None
                word_range = get_word_range(rules) if isinstance(rules, dict) else None
                if max_chars is not None:
                    if recomputed_cc > max_chars:
                        length_ok = False
                if word_range is not None and isinstance(word_range, tuple):
                    mn, mx = word_range
                    if recomputed_wc < mn or recomputed_wc > mx:
                        length_ok = False
                # phrases inclusion
                phrases = get_phrases(rules) if isinstance(rules, dict) else []
                if phrases:
                    t_low = text.lower()
                    for ph in phrases:
                        if isinstance(ph, str) and ph.strip():
                            if ph.lower() not in t_low:
                                phrases_ok = False
                                break
            else:
                counts_ok = False
                # if counts missing, cannot evaluate constraints
                rules = plat_map.get(p, {}) if isinstance(plat_map, dict) else {}
                phrases = get_phrases(rules) if isinstance(rules, dict) else []
                if phrases:
                    phrases_ok = False

        checks["all_versions_text_present"] = all_text_present and checks["versions_keys_exact"]
        checks["counts_match"] = counts_ok and checks["versions_keys_exact"]
        checks["length_constraints_met"] = length_ok and checks["versions_keys_exact"] and checks["counts_match"]
        checks["phrases_included"] = phrases_ok and checks["versions_keys_exact"] and checks["all_versions_text_present"]

        # Openings validation
        openings = bios_data.get("openings")
        openings_valid_struct = isinstance(openings, list) and all(isinstance(x, dict) for x in openings)
        if openings_valid_struct:
            # Basic fields
            fields_ok = True
            sentence_rules_ok = True
            for item in openings:
                s = item.get("sentence")
                wid = item.get("what_it_does")
                bfr = item.get("best_for_reader")
                if not (isinstance(s, str) and s.strip() and isinstance(wid, str) and wid.strip() and isinstance(bfr, str) and bfr.strip()):
                    fields_ok = False
                if isinstance(s, str):
                    if len(s) > 200 or not ends_with_sentence_punct(s):
                        sentence_rules_ok = False
                else:
                    sentence_rules_ok = False
            checks["openings_structure_valid"] = fields_ok
            checks["openings_sentence_rules_met"] = sentence_rules_ok and fields_ok

            # Count requirement
            openings_rules = get_openings_requirements(platform_requirements if isinstance(platform_requirements, dict) else {})
            min_count = None
            if isinstance(openings_rules, dict):
                # direct min_count or nested
                if isinstance(openings_rules.get("min_count"), int):
                    min_count = openings_rules.get("min_count")
                elif isinstance(openings_rules.get("openings_min_count"), int):
                    min_count = openings_rules.get("openings_min_count")
            if min_count is None:
                # also check top-level fallback
                if isinstance(platform_requirements, dict):
                    v = platform_requirements.get("openings_min_count")
                    if isinstance(v, int):
                        min_count = v
            if isinstance(min_count, int):
                checks["openings_count_met"] = len(openings) >= min_count
            else:
                # If unspecified, treat as valid
                checks["openings_count_met"] = True

            # Avoid name start requirement
            avoid_name = False
            if isinstance(openings_rules, dict):
                v = openings_rules.get("avoid_name_start")
                if isinstance(v, bool):
                    avoid_name = v
            if not avoid_name and isinstance(platform_requirements, dict):
                v = platform_requirements.get("avoid_name_start")
                if isinstance(v, bool):
                    avoid_name = v
            if avoid_name:
                if isinstance(profile_full_name, str) and profile_full_name.strip():
                    not_name_start = 0
                    name_lower = profile_full_name.strip().lower()
                    for item in openings:
                        s = item.get("sentence")
                        if isinstance(s, str):
                            if not s.strip().lower().startswith(name_lower):
                                not_name_start += 1
                    checks["openings_avoid_name_start_met"] = not_name_start >= 3
                else:
                    # Cannot verify without profile name; mark as failed
                    checks["openings_avoid_name_start_met"] = False
            else:
                # No requirement -> pass
                checks["openings_avoid_name_start_met"] = True
        else:
            checks["openings_structure_valid"] = False
            checks["openings_count_met"] = False
            checks["openings_sentence_rules_met"] = False
            # If requirement exists to avoid name start, fails without openings
            openings_rules = get_openings_requirements(platform_requirements if isinstance(platform_requirements, dict) else {})
            avoid_name = False
            if isinstance(openings_rules, dict):
                v = openings_rules.get("avoid_name_start")
                if isinstance(v, bool):
                    avoid_name = v
            if not avoid_name and isinstance(platform_requirements, dict):
                v = platform_requirements.get("avoid_name_start")
                if isinstance(v, bool):
                    avoid_name = v
            checks["openings_avoid_name_start_met"] = (not avoid_name)

    # README checks (dependent on profile name for one check)
    if checks["readme_exists"]:
        # Name from profile.json must appear
        if isinstance(profile_full_name, str) and profile_full_name and profile_full_name in readme_text:
            checks["readme_has_name"] = True
        # List of platform names
        found_all = True
        text_low = readme_text.lower()
        for p in platforms:
            if p.lower() not in text_low:
                found_all = False
                break
        checks["readme_lists_platforms"] = found_all

    # Compute reward
    # No-op baseline handling: if output dir missing or both artifacts missing, reward=0.0
    output_exists = os.path.isdir(output_dir)
    artifacts_present = checks["bios_json_exists"] or checks["readme_exists"]
    if (not output_exists) or (not artifacts_present):
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Avoid awarding if both required artifacts missing; already handled
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print result JSON
    result = {"reward": float(round(reward, 6))}
    # Ensure reward first, then checks
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()