import os
import sys
import json
import re
import csv

# Attempt to import yaml; if unavailable, use heuristic validation
try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # Fallback to heuristic


def get_workspace_root():
    if len(sys.argv) > 1 and sys.argv[1]:
        return sys.argv[1]
    return "/root/.openclaw/workspace"


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def file_exists(path):
    try:
        return os.path.isfile(path)
    except Exception:
        return False


def validate_yaml(text):
    # If PyYAML is available, use it for strict parsing
    if yaml is not None:
        try:
            yaml.safe_load(text)
            return True
        except Exception:
            return False
    # Heuristic YAML validation: Allow comments, blank lines, list items, and key: value lines
    # This is a conservative check that ensures there are recognizable YAML structures
    valid_line = re.compile(r"""^(
        \s*#.*$ |                               # comment
        \s*$    |                               # blank
        \s*-\s+[^\n:]+:\s*.*$ |                 # list item with key: value
        \s*-\s+.+$ |                             # list item value
        \s*[^\n:]+:\s*.*$                       # key: value
    )""", re.VERBOSE)
    for line in text.splitlines():
        if not valid_line.match(line):
            return False
    return True


def count_deeplink_patterns(text):
    # Pattern: scheme://path with {placeholder}
    pattern = re.compile(r'\b[a-zA-Z][a-zA-Z0-9+\-.]*://[^\s"\'\)]*\{[^}]+\}[^\s"\'\)]*')
    matches = pattern.findall(text)
    return len(set(matches))


def count_screen_entries(text):
    # Count unique values after - name: or - screen:
    names = set()
    for m in re.finditer(r'^\s*-\s*(?:name|screen)\s*:\s*(.+)$', text, flags=re.IGNORECASE | re.MULTILINE):
        val = m.group(1).strip()
        if val:
            names.add(val)
    # If none found, also consider lines like 'screen: XYZ' not necessarily in list
    if not names:
        for m in re.finditer(r'^\s*(?:name|screen)\s*:\s*(.+)$', text, flags=re.IGNORECASE | re.MULTILINE):
            val = m.group(1).strip()
            if val:
                names.add(val)
    return len(names)


def csv_read_rows(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                # keep raw rows (including possibly blank)
                rows.append(row)
    except Exception:
        return None
    return rows


def normalize(s):
    return (s or "").strip().lower()


def check_network_conditions(rows, header):
    try:
        idx = header.index("Network Condition")
    except ValueError:
        return False
    have_offline = False
    have_slow3g = False
    have_wifi = False
    for r in rows[1:]:
        if not r or len(r) <= idx:
            continue
        cond = normalize(r[idx])
        if "offline" in cond:
            have_offline = True
        # slow-3g detection: allow variants like slow-3g, slow 3g, slow3g
        if ("3g" in cond and "slow" in cond) or "slow-3g" in cond or "slow3g" in cond:
            have_slow3g = True
        if "wifi" in cond or "wi-fi" in cond:
            have_wifi = True
    return have_offline and have_slow3g and have_wifi


def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dictionary with all checks set to False
    checks = {
        # Presence checks
        "has_architecture_md": False,
        "has_offline_sync_strategy_md": False,
        "has_navigation_yaml": False,
        "has_permissions_policy_md": False,
        "has_notifications_json": False,
        "has_test_matrix_csv": False,
        "has_release_checklist_md": False,
        # Structural checks
        "architecture_sections_ok": False,
        "architecture_codename_ok": False,
        "offline_keywords_ok": False,
        "offline_strategy_ok": False,
        "navigation_yaml_parseable": False,
        "navigation_patterns_count_ok": False,
        "navigation_screens_count_ok": False,
        "permissions_required_phrases_ok": False,
        "permissions_includes_camera_and_location": False,
        "notifications_json_parseable": False,
        "notifications_has_categories_grouping": False,
        "test_matrix_header_ok": False,
        "test_matrix_row_count_ok": False,
        "test_matrix_network_conditions_ok": False,
        "release_checklist_phrases_ok": False,
    }

    # Define expected output paths
    arch_path = os.path.join(output_dir, "architecture.md")
    offline_path = os.path.join(output_dir, "offline_sync_strategy.md")
    nav_yaml_path = os.path.join(output_dir, "navigation_and_deep_links.yaml")
    perm_path = os.path.join(output_dir, "permissions_policy.md")
    notif_json_path = os.path.join(output_dir, "notifications_plan.json")
    test_csv_path = os.path.join(output_dir, "test_matrix.csv")
    release_path = os.path.join(output_dir, "release_checklist.md")

    # Presence
    if file_exists(arch_path):
        checks["has_architecture_md"] = True
        text = read_text(arch_path) or ""
        low = text.lower()
        required_sections = [
            "lifecycle",
            "permissions",
            "offline first",
            "performance",
            "navigation",
            "notifications",
            "deep linking",
            "storage",
            "input handling",
            "touch and gestures",
            "accessibility",
            "testing",
            "app store",
        ]
        if all(sec in low for sec in required_sections):
            checks["architecture_sections_ok"] = True
        if "orion-77".lower() in low:
            checks["architecture_codename_ok"] = True

    if file_exists(offline_path):
        checks["has_offline_sync_strategy_md"] = True
        text = read_text(offline_path) or ""
        low = text.lower()
        # Must include words: cache, retry, conflict, queue
        if all(word in low for word in ["cache", "retry", "conflict", "queue"]):
            checks["offline_keywords_ok"] = True
        # Must include at least one of phrases: "last write wins" or "manual merge"
        if ("last write wins" in low) or ("manual merge" in low):
            checks["offline_strategy_ok"] = True

    if file_exists(nav_yaml_path):
        checks["has_navigation_yaml"] = True
        text = read_text(nav_yaml_path) or ""
        # YAML parseable or heuristically valid
        if validate_yaml(text):
            checks["navigation_yaml_parseable"] = True
        # At least three deep link patterns with placeholders
        if count_deeplink_patterns(text) >= 3:
            checks["navigation_patterns_count_ok"] = True
        # At least four distinct screen entries
        if count_screen_entries(text) >= 4:
            checks["navigation_screens_count_ok"] = True

    if file_exists(perm_path):
        checks["has_permissions_policy_md"] = True
        text = read_text(perm_path) or ""
        low = text.lower()
        if ("ask in context" in low) and ("graceful degradation" in low):
            checks["permissions_required_phrases_ok"] = True
        # Reference at least two common mobile permissions such as camera and location
        if ("camera" in low) and ("location" in low):
            checks["permissions_includes_camera_and_location"] = True

    if file_exists(notif_json_path):
        checks["has_notifications_json"] = True
        text = read_text(notif_json_path) or ""
        parsed = None
        try:
            parsed = json.loads(text)
            checks["notifications_json_parseable"] = True
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            if "categories" in parsed and "grouping" in parsed:
                checks["notifications_has_categories_grouping"] = True

    if file_exists(test_csv_path):
        checks["has_test_matrix_csv"] = True
        rows = csv_read_rows(test_csv_path)
        if rows is not None and len(rows) >= 1:
            header = rows[0]
            expected_header = ["Device", "OS Version", "Screen Size", "Network Condition", "Test Case", "Status"]
            if header == expected_header:
                checks["test_matrix_header_ok"] = True
            # Count non-empty data rows (exclude header)
            data_rows = [r for r in rows[1:] if any(cell.strip() for cell in r)]
            if len(data_rows) >= 8:
                checks["test_matrix_row_count_ok"] = True
            if checks["test_matrix_header_ok"]:
                if check_network_conditions(rows, header):
                    checks["test_matrix_network_conditions_ok"] = True

    if file_exists(release_path):
        checks["has_release_checklist_md"] = True
        text = read_text(release_path) or ""
        low = text.lower()
        if all(phrase in low for phrase in ["privacy policy", "test account", "no placeholders", "regular updates"]):
            checks["release_checklist_phrases_ok"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Ensure baseline: if output dir missing or empty and nothing passed, reward is 0.0 implicitly
    result = {"reward": float(reward)}
    # Preserve insertion order with reward first
    result.update(checks)
    print(json.dumps(result))


if __name__ == "__main__":
    main()