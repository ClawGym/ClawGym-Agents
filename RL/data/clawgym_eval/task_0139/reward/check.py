import json
import os
import sys
import csv
import re

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_compatibility(csv_path, preferred_letter, modules_set):
    """
    Returns a sorted list of modules unavailable under preferred_letter (e.g., 'B').
    Only includes modules present in modules_set.
    """
    unavailable = []
    if not os.path.isfile(csv_path):
        return unavailable

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            # Identify module column
            module_col = None
            lower_headers = [h.lower().strip() for h in headers]
            for h in headers:
                hl = h.lower().strip()
                if hl in ("module", "modules", "name", "module_name", "skill", "tool"):
                    module_col = h
                    break
            if module_col is None:
                # Fallback: first column that is not a method column
                method_markers = set(["a", "b", "c", "method a", "method b", "method c", "available_a", "available_b", "available_c"])
                for h in headers:
                    if h.lower().strip() not in method_markers:
                        module_col = h
                        break
                if module_col is None and headers:
                    module_col = headers[0]

            # Identify preferred method column (e.g., 'B')
            preferred_candidates = []
            for h in headers:
                hl = h.lower().strip()
                if hl == preferred_letter.lower():
                    preferred_candidates.append(h)
                if hl == f"method {preferred_letter.lower()}":
                    preferred_candidates.append(h)
                if hl == f"available_{preferred_letter.lower()}":
                    preferred_candidates.append(h)
                if hl == f"{preferred_letter.lower()}_available":
                    preferred_candidates.append(h)
            preferred_col = preferred_candidates[0] if preferred_candidates else None
            if preferred_col is None:
                # Try exact uppercase 'B'
                for h in headers:
                    if h.strip() == preferred_letter:
                        preferred_col = h
                        break

            if preferred_col is None:
                return []

            for row in reader:
                mod_name = str(row.get(module_col, "")).strip()
                if not mod_name or mod_name not in modules_set:
                    continue
                val = str(row.get(preferred_col, "")).strip().lower()
                # Treat 'no', '0', 'false' as unavailable
                is_no = val in ("no", "0", "false")
                if is_no:
                    unavailable.append(mod_name)
    except Exception:
        return []
    return sorted(unavailable)

def extract_section_items(content, section_label, next_labels):
    """
    Extract list items from a section starting with a line that begins with section_label.
    Items may be:
    - inline on the same line, comma-separated
    - on subsequent lines until next labeled section, with optional bullets
    Returns a list of stripped items (empty strings filtered).
    """
    lines = content.splitlines()
    items = []
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith(section_label.lower()):
            start_idx = i
            # Inline case
            after = line.split(":", 1)[1] if ":" in line else ""
            if after.strip():
                # split by comma
                parts = [p.strip() for p in after.split(",")]
                items.extend([p for p in parts if p])
            break
    if start_idx is None:
        return []

    # If inline had items, also allow subsequent bullet lines directly after if present
    i = start_idx + 1
    while i < len(lines):
        l = lines[i].strip()
        if any(l.lower().startswith(lbl.lower()) for lbl in next_labels):
            break
        if l == "":
            # allow blank lines within section, but break if we already collected some and then double blank?
            # Just continue to be lenient
            i += 1
            continue
        # Handle bullet markers or plain lines
        # Remove leading bullet indicators like "- ", "* ", "• ", "- [ ] ", "- [x] "
        l2 = re.sub(r"^-\s*\[.\]\s*", "", l)  # task checkbox bullet
        l2 = re.sub(r"^[-*•]\s*", "", l2)
        if l2:
            # split by comma if inline list on a line
            if "," in l2 and not l2.startswith("/"):  # for module lists, comma-separated
                parts = [p.strip() for p in l2.split(",")]
                items.extend([p for p in parts if p])
            else:
                items.append(l2)
        i += 1
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for it in items:
        if it not in seen:
            deduped.append(it)
            seen.add(it)
    return deduped

def extract_section_text(content, section_label, next_labels):
    """
    Extract raw text of a section starting at section_label until next label.
    Returns the joined text (including the starting line).
    """
    lines = content.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith(section_label.lower()):
            start_idx = i
            break
    if start_idx is None:
        return ""
    collected = [lines[start_idx]]
    i = start_idx + 1
    while i < len(lines):
        l = lines[i]
        if any(l.strip().lower().startswith(lbl.lower()) for lbl in next_labels):
            break
        collected.append(l)
        i += 1
    return "\n".join(collected)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    modules_path = os.path.join(input_dir, "modules.json")
    prefs_path = os.path.join(input_dir, "preferences.json")
    compat_path = os.path.join(input_dir, "compatibility.csv")
    summary_path = os.path.join(output_dir, "summary.json")
    report_path = os.path.join(output_dir, "install_report.md")

    # Initialize checks
    checks = {
        # Summary.json checks
        "summary_exists": False,
        "summary_valid_json": False,
        "installed_via_correct": False,
        "modules_total_correct": False,
        "unavailable_list_correct": False,
        "fallbacks_object_correct": False,
        "server_configured_correct": False,
        "quick_starts_includes_required": False,
        "quick_starts_all_start_with_slash": False,
        # Report checks
        "report_exists": False,
        "report_title_present": False,
        "report_installation_method_correct": False,
        "report_modules_detected_correct": False,
        "report_server_configured_line_correct": False,
        "report_unavailable_section_matches": False,
        "report_fallback_plan_lists_all_unavailable_and_method_a": False,
        "report_quick_starts_include_required": False,
        # Cross-file consistency
        "cross_file_consistency": False,
    }

    # Load inputs
    modules_data = load_json(modules_path) or []
    modules_list = modules_data if isinstance(modules_data, list) else []
    modules_set = set([m for m in modules_list if isinstance(m, str)])
    modules_count = len(modules_list)

    prefs_data = load_json(prefs_path) or {}
    # Preferred method letter (e.g., "B"), with fallback keys
    preferred_letter = None
    for key in ["preferred_method", "method_preference", "preferred", "preference"]:
        if key in prefs_data and isinstance(prefs_data[key], str):
            preferred_letter = prefs_data[key].strip().upper()
            break
    if preferred_letter not in ("A", "B", "C"):
        preferred_letter = "B"  # fallback if missing; dataset expects B

    enable_server = None
    for key in ["enable_server", "server_enabled", "server", "mcp_enabled"]:
        if key in prefs_data:
            enable_server = bool(prefs_data[key])
            break
    if enable_server is None:
        enable_server = False

    preferred_method_str = f"Method {preferred_letter}"

    # Determine expected unavailable modules under preferred method using compatibility.csv
    expected_unavailable = parse_compatibility(compat_path, preferred_letter, modules_set)
    expected_unavailable_sorted = sorted(expected_unavailable)

    # Required quick start commands
    required_qs = {"/research", "/validate", "/stream"}

    # Validate summary.json
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        summary = load_json(summary_path)
        if isinstance(summary, dict):
            checks["summary_valid_json"] = True
            # installed_via
            installed_via = summary.get("installed_via", None)
            if isinstance(installed_via, str) and installed_via in ("Method A", "Method B", "Method C"):
                if installed_via == preferred_method_str:
                    checks["installed_via_correct"] = True
            # modules_total
            modules_total = summary.get("modules_total", None)
            if isinstance(modules_total, int) and modules_total == modules_count:
                checks["modules_total_correct"] = True
            # unavailable
            unavailable = summary.get("unavailable", None)
            if isinstance(unavailable, list) and all(isinstance(x, str) for x in unavailable):
                # must be sorted alphabetically and match expected set
                if unavailable == expected_unavailable_sorted:
                    checks["unavailable_list_correct"] = True
            # fallbacks
            fallbacks = summary.get("fallbacks", None)
            if isinstance(fallbacks, dict):
                # Keys must match unavailable and values must be "Method A"
                keys_match = set(fallbacks.keys()) == set(expected_unavailable_sorted)
                values_ok = all(v == "Method A" for v in fallbacks.values())
                if keys_match and values_ok:
                    checks["fallbacks_object_correct"] = True
            # server_configured
            server_configured = summary.get("server_configured", None)
            if isinstance(server_configured, bool) and server_configured == enable_server:
                checks["server_configured_correct"] = True
            # quick_starts
            quick_starts = summary.get("quick_starts", None)
            if isinstance(quick_starts, list) and all(isinstance(x, str) for x in quick_starts):
                contains_required = required_qs.issubset(set(quick_starts))
                if contains_required:
                    checks["quick_starts_includes_required"] = True
                if all(isinstance(x, str) and x.startswith("/") for x in quick_starts):
                    checks["quick_starts_all_start_with_slash"] = True

    # Validate install_report.md
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_content = f.read()
        except Exception:
            report_content = ""

        # Title line
        lines = [ln.strip() for ln in report_content.splitlines()]
        if any(ln == "Startup Toolkit Setup Report" for ln in lines):
            checks["report_title_present"] = True

        # Installation method line
        install_line_ok = False
        for ln in lines:
            if ln.startswith("Installation method:"):
                # must contain the exact method string
                if preferred_method_str in ln:
                    install_line_ok = True
                break
        checks["report_installation_method_correct"] = install_line_ok

        # Modules detected line
        modules_line_ok = False
        for ln in lines:
            if ln.startswith("Modules detected:"):
                # Extract number from line
                m = re.search(r"Modules detected:\s*(\d+)", ln)
                if m and int(m.group(1)) == modules_count:
                    modules_line_ok = True
                break
        checks["report_modules_detected_correct"] = modules_line_ok

        # Server configured line
        server_line_ok = False
        for ln in lines:
            if ln.startswith("Server configured:"):
                after = ln.split(":", 1)[1].strip().lower()
                expected_val = "yes" if enable_server else "no"
                if after == expected_val:
                    server_line_ok = True
                break
        checks["report_server_configured_line_correct"] = server_line_ok

        # Unavailable modules section
        next_labels = [
            "Fallback plan:",
            "Quick start commands:",
            "Installation method:",
            "Modules detected:",
            "Server configured:",
        ]
        unavailable_items = extract_section_items(report_content, "Unavailable modules:", next_labels)
        # Normalize items by stripping trailing punctuation
        unavailable_items_norm = [itm.strip().rstrip(",") for itm in unavailable_items if itm.strip()]
        if sorted(unavailable_items_norm) == expected_unavailable_sorted:
            checks["report_unavailable_section_matches"] = True

        # Fallback plan section
        fallback_text = extract_section_text(report_content, "Fallback plan:", next_labels)
        fallback_ok = False
        if fallback_text:
            # Must mention Method A
            mentions_method_a = "Method A" in fallback_text
            # Must list each unavailable module somewhere in the section
            modules_covered = all((mod in fallback_text) for mod in expected_unavailable_sorted)
            if mentions_method_a and modules_covered:
                fallback_ok = True
        checks["report_fallback_plan_lists_all_unavailable_and_method_a"] = fallback_ok

        # Quick start commands section
        quick_items = extract_section_items(report_content, "Quick start commands:", next_labels)
        quick_set = set([q.strip() for q in quick_items if q.strip()])
        quick_ok = required_qs.issubset(quick_set)
        checks["report_quick_starts_include_required"] = quick_ok

    # Cross-file consistency (only if both files parsed and summary JSON valid)
    cross_ok = False
    if checks["summary_valid_json"] and checks["report_exists"]:
        summary = load_json(summary_path) or {}
        if isinstance(summary, dict):
            sv_method = summary.get("installed_via")
            sv_total = summary.get("modules_total")
            sv_server = summary.get("server_configured")
            sv_unavail = summary.get("unavailable") if isinstance(summary.get("unavailable"), list) else None
            # From report
            report_method_ok = checks["report_installation_method_correct"]
            report_total_ok = checks["report_modules_detected_correct"]
            report_server_ok = checks["report_server_configured_line_correct"]
            report_unavailable_ok = checks["report_unavailable_section_matches"]

            # Basic consistency conditions:
            if (sv_method == preferred_method_str and
                sv_total == modules_count and
                isinstance(sv_server, bool) and sv_server == enable_server and
                isinstance(sv_unavail, list) and sorted(sv_unavail) == expected_unavailable_sorted and
                report_method_ok and report_total_ok and report_server_ok and report_unavailable_ok):
                cross_ok = True
    checks["cross_file_consistency"] = cross_ok

    # Compute reward
    # Required artifacts: both summary.json and install_report.md must exist, otherwise reward 0.0
    required_present = checks["summary_exists"] and checks["report_exists"]
    if not required_present:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Avoid division by zero; total_checks > 0 here
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()