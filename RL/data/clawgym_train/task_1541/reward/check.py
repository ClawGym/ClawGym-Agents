import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_iso_like_datetime(s):
    if not isinstance(s, str):
        return False
    # Accept YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS(.sss)?Z?
    date_only = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    date_time = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?Z?$")
    return bool(date_only.match(s) or date_time.match(s))

def extract_section(md_text, heading_contains):
    # Return content of section whose heading line contains the phrase (case-insensitive),
    # from that heading line to before the next heading starting with '#'
    if md_text is None:
        return ""
    lines = md_text.splitlines()
    start_idx = None
    hc = heading_contains.lower()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") and hc in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return ""
    # Find next heading
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].lstrip().startswith("#"):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])

def count_recommendation_items(section_text):
    if not section_text:
        return 0
    count = 0
    for line in section_text.splitlines():
        s = line.strip()
        if s.startswith("- ") or s.startswith("* ") or re.match(r"^\d+\.\s", s):
            count += 1
    return count

def count_confidence_scores(text):
    # Count occurrences of decimals between 0.00 and 0.99 style like 0.78 (we just look for 0.xx or 1.00)
    if not text:
        return 0
    return len(re.findall(r"\b0\.\d{2,}\b", text))

def find_distinct_priorities(text):
    if not text:
        return set()
    return set(re.findall(r"\bP[0-9]\b", text))

def starts_with_h1(html_text):
    if html_text is None:
        return False
    trimmed = html_text.lstrip()
    return trimmed.lower().startswith("<h1")

def has_h2(html_text):
    if html_text is None:
        return False
    return "<h2" in html_text.lower() and "</h2>" in html_text.lower()

def has_ul_with_at_least_n_li(html_text, n):
    if html_text is None:
        return False
    ul_present = "<ul" in html_text.lower() and "</ul>" in html_text.lower()
    li_count = len(re.findall(r"<li\b", html_text, flags=re.IGNORECASE))
    return ul_present and li_count >= n

def has_generated_timestamp(html_text):
    if html_text is None:
        return False
    # Either contains the word Generated or contains an ISO-like date in text
    if "Generated" in html_text or "generated" in html_text:
        return True
    return bool(re.search(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)?\b", html_text))

def validate_nav_summary(nav_json):
    checks = {
        "nav_summary_valid_json": False,
        "nav_summary_has_top_keys": False,
        "nav_summary_generatedAt_iso": False,
        "nav_summary_schemes_len_ge_3": False,
        "nav_summary_scheme_fields_valid": False,
        "nav_summary_latestNav_format_all": False,
        "nav_summary_monthlyAverages_2025_keys_valid": False,
        "nav_summary_some_scheme_has_3_months": False,
    }
    if not isinstance(nav_json, dict):
        return checks
    checks["nav_summary_valid_json"] = True

    # Top-level keys: generatedAt (string), schemes (array)
    if "generatedAt" in nav_json and "schemes" in nav_json and isinstance(nav_json["schemes"], list):
        checks["nav_summary_has_top_keys"] = True
        if is_iso_like_datetime(nav_json.get("generatedAt")):
            checks["nav_summary_generatedAt_iso"] = True

        schemes = nav_json["schemes"]
        if isinstance(schemes, list) and len(schemes) >= 3:
            checks["nav_summary_schemes_len_ge_3"] = True

        scheme_fields_ok = True
        latest_nav_format_ok = True
        monthly_averages_keys_ok = True
        some_scheme_has_3_months = False

        for s in schemes:
            if not isinstance(s, dict):
                scheme_fields_ok = False
                continue
            # Required fields
            if not (
                "schemeCode" in s and isinstance(s["schemeCode"], (int, float)) and
                "schemeName" in s and isinstance(s["schemeName"], str) and
                "latestNav" in s and isinstance(s["latestNav"], str) and
                "monthlyAverages" in s and isinstance(s["monthlyAverages"], dict)
            ):
                scheme_fields_ok = False

            # latestNav format #####: five decimals
            if "latestNav" in s and isinstance(s["latestNav"], str):
                if not re.match(r"^[0-9]+\.[0-9]{5}$", s["latestNav"]):
                    latest_nav_format_ok = False
            else:
                latest_nav_format_ok = False

            # monthlyAverages keys and values
            ma = s.get("monthlyAverages", {})
            if isinstance(ma, dict):
                # All keys must be 2025-01..2025-12 and values must be numbers
                for k, v in ma.items():
                    if not re.match(r"^2025-(0[1-9]|1[0-2])$", str(k)):
                        monthly_averages_keys_ok = False
                        break
                    if not isinstance(v, (int, float)):
                        monthly_averages_keys_ok = False
                        break
                # Count distinct months
                if len([k for k in ma.keys() if re.match(r"^2025-(0[1-9]|1[0-2])$", str(k))]) >= 3:
                    some_scheme_has_3_months = True or some_scheme_has_3_months
            else:
                monthly_averages_keys_ok = False

        checks["nav_summary_scheme_fields_valid"] = scheme_fields_ok
        checks["nav_summary_latestNav_format_all"] = latest_nav_format_ok
        checks["nav_summary_monthlyAverages_2025_keys_valid"] = monthly_averages_keys_ok
        checks["nav_summary_some_scheme_has_3_months"] = some_scheme_has_3_months

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    nav_summary_path = os.path.join(output_dir, "nav_summary.json")
    learning_report_path = os.path.join(output_dir, "learning_report.md")
    nav_note_path = os.path.join(output_dir, "notes", "nav_note.html")
    architecture_path = os.path.join(output_dir, "architecture.md")

    # Existence checks
    checks["nav_summary_exists"] = os.path.isfile(nav_summary_path)
    checks["learning_report_exists"] = os.path.isfile(learning_report_path)
    checks["nav_note_exists"] = os.path.isfile(nav_note_path)
    checks["architecture_exists"] = os.path.isfile(architecture_path)

    # nav_summary.json validations
    nav_json = load_json(nav_summary_path) if checks["nav_summary_exists"] else None
    nav_checks = validate_nav_summary(nav_json) if nav_json is not None else {
        "nav_summary_valid_json": False,
        "nav_summary_has_top_keys": False,
        "nav_summary_generatedAt_iso": False,
        "nav_summary_schemes_len_ge_3": False,
        "nav_summary_scheme_fields_valid": False,
        "nav_summary_latestNav_format_all": False,
        "nav_summary_monthlyAverages_2025_keys_valid": False,
        "nav_summary_some_scheme_has_3_months": False,
    }
    checks.update(nav_checks)

    # learning_report.md validations
    lr_text = read_text(learning_report_path) if checks["learning_report_exists"] else None
    checks["learning_report_has_title"] = bool(lr_text and any(line.startswith("# ") for line in lr_text.splitlines()))
    checks["learning_report_has_usage_patterns_section"] = bool(lr_text and re.search(r"^#{1,6}\s+.*Usage Patterns.*", lr_text, flags=re.IGNORECASE | re.MULTILINE))
    checks["learning_report_has_effectiveness_or_success_section"] = bool(lr_text and (re.search(r"^#{1,6}\s+.*Effectiveness Analysis.*", lr_text, flags=re.IGNORECASE | re.MULTILINE) or re.search(r"^#{1,6}\s+.*Success Metrics.*", lr_text, flags=re.IGNORECASE | re.MULTILINE)))
    checks["learning_report_has_evolution_recommendations_section"] = bool(lr_text and re.search(r"^#{1,6}\s+.*Evolution Recommendations.*", lr_text, flags=re.IGNORECASE | re.MULTILINE))
    # Recommendations section parsing
    rec_section = extract_section(lr_text or "", "Evolution Recommendations")
    checks["learning_report_has_3_recommendation_items"] = count_recommendation_items(rec_section) >= 3
    checks["learning_report_has_3_confidence_scores"] = count_confidence_scores(lr_text or "") >= 3
    checks["learning_report_has_2_distinct_priorities"] = len(find_distinct_priorities(lr_text or "")) >= 2

    # nav_note.html validations
    note_text = read_text(nav_note_path) if checks["nav_note_exists"] else None
    checks["nav_note_starts_with_h1"] = starts_with_h1(note_text)
    checks["nav_note_has_h2"] = has_h2(note_text)
    checks["nav_note_has_ul_with_5_li"] = has_ul_with_at_least_n_li(note_text, 5)
    checks["nav_note_has_generated_timestamp"] = has_generated_timestamp(note_text)

    # architecture.md validations
    arch_text = read_text(architecture_path) if checks["architecture_exists"] else None
    checks["architecture_non_empty"] = bool(arch_text and arch_text.strip())
    code_block_count = 0
    if arch_text:
        code_block_count = len(re.findall(r"```js\b", arch_text))
    checks["architecture_has_4_js_code_blocks"] = code_block_count >= 4
    # Role classes within code blocks (we will search entire text for simplicity)
    arch_search_text = arch_text or ""
    checks["architecture_has_navrepository_class"] = bool(re.search(r"\bclass\s+NavRepository\b", arch_search_text))
    checks["architecture_has_navservice_class"] = bool(re.search(r"\bclass\s+NavService\b", arch_search_text))
    checks["architecture_has_policy_or_strategy_class"] = bool(re.search(r"\bclass\s+\w*(Policy|Strategy)\w*\b", arch_search_text))
    checks["architecture_has_usecase_class"] = bool(re.search(r"\bclass\s+\w*UseCase\w*\b", arch_search_text))
    checks["architecture_has_controller_class"] = bool(re.search(r"\bclass\s+\w*Controller\w*\b", arch_search_text))
    checks["architecture_has_private_field"] = bool(re.search(r"\#[a-zA-Z_]\w*", arch_search_text))
    checks["architecture_has_named_exports"] = bool(re.search(r"\bexport\s+class\b", arch_search_text) or re.search(r"\bexport\s+const\b", arch_search_text))
    # Composition root detection
    has_comp_root_term = "CompositionRoot" in arch_search_text
    has_compose_or_wire = bool(re.search(r"\bcompose\(", arch_search_text) or re.search(r"\bwire\(", arch_search_text))
    has_new_instances = bool("new NavRepository" in arch_search_text and "new NavService" in arch_search_text)
    checks["architecture_has_composition_root"] = has_comp_root_term or has_compose_or_wire or has_new_instances

    # Compute reward
    total_checks = 0
    passed_checks = 0
    for key, val in checks.items():
        if isinstance(val, bool):
            total_checks += 1
            if val:
                passed_checks += 1

    # No-op baseline: if none of the required files exist, reward must be 0.0
    required_exist = checks["nav_summary_exists"] or checks["learning_report_exists"] or checks["nav_note_exists"] or checks["architecture_exists"]
    if not required_exist:
        reward = 0.0
    else:
        reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # Bound reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()