import json
import os
import sys
from typing import Dict, List

def key_slug(name: str) -> str:
    s = name.lower()
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "/"):
            out.append("_")
        else:
            out.append("")
    return "".join(out).strip("_")

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    expected_keywords = ["Bitcoin", "Trump", "Arsenal FC"]
    expected_tags = ["crypto", "sports", "politics"]

    # Initialize checks dictionary with all expected keys set to False
    checks: Dict[str, bool] = {}

    def add_check(name: str, value: bool = False):
        checks[name] = value

    # Global/structure checks
    add_check("summary_exists", False)
    add_check("summary_valid_json", False)
    add_check("has_top_level_keywords_and_tags", False)
    add_check("keywords_exactly_expected", False)
    add_check("tags_exactly_expected", False)
    add_check("raw_logs_all_distinct", False)
    add_check("raw_logs_all_relative", False)

    # Per-keyword checks
    for kw in expected_keywords:
        slug = key_slug(kw)
        add_check(f"kw_{slug}_raw_log_path_format", False)
        add_check(f"kw_{slug}_raw_log_file_exists", False)
        add_check(f"kw_{slug}_preamble_and_markers", False)
        add_check(f"kw_{slug}_contains_required_phrase", False)
        add_check(f"kw_{slug}_had_no_results_field", False)

    # Per-tag checks
    for tag in expected_tags:
        slug = key_slug(tag)
        add_check(f"tag_{slug}_raw_log_path_format", False)
        add_check(f"tag_{slug}_raw_log_file_exists", False)
        add_check(f"tag_{slug}_preamble_and_markers", False)
        add_check(f"tag_{slug}_contains_active_events", False)

    summary_path = os.path.join(output_dir, "summary.json")
    summary = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            if isinstance(summary, dict):
                checks["summary_valid_json"] = True
        except Exception:
            summary = None

    raw_log_paths_collected: List[str] = []

    if checks["summary_valid_json"] and isinstance(summary, dict):
        has_keywords = "keywords" in summary and isinstance(summary.get("keywords"), dict)
        has_tags = "tags" in summary and isinstance(summary.get("tags"), dict)
        if has_keywords and has_tags:
            checks["has_top_level_keywords_and_tags"] = True

            keywords_obj = summary.get("keywords", {})
            tags_obj = summary.get("tags", {})

            # Exact key sets
            kw_keys = set(keywords_obj.keys())
            if kw_keys == set(expected_keywords) and len(kw_keys) == 3:
                checks["keywords_exactly_expected"] = True

            tag_keys = set(tags_obj.keys())
            if tag_keys == set(expected_tags) and len(tag_keys) == 3:
                checks["tags_exactly_expected"] = True

            # Validate keyword entries
            for kw in expected_keywords:
                slug = key_slug(kw)
                entry = keywords_obj.get(kw, {})
                # had_no_results must be boolean field
                had_no_results = entry.get("had_no_results", None)
                if isinstance(had_no_results, bool):
                    checks[f"kw_{slug}_had_no_results_field"] = True

                raw_log = entry.get("raw_log", None)
                # Path format: string, startswith output/raw/, not absolute
                path_format_ok = isinstance(raw_log, str) and raw_log.startswith("output/raw/") and not raw_log.startswith("/")
                if path_format_ok:
                    checks[f"kw_{slug}_raw_log_path_format"] = True
                    raw_log_paths_collected.append(raw_log)

                # Existence and content checks
                if isinstance(raw_log, str):
                    abs_path = os.path.join(workspace_root, raw_log)
                    if os.path.isfile(abs_path):
                        checks[f"kw_{slug}_raw_log_file_exists"] = True
                        content = read_text(abs_path)
                        # Preamble and markers
                        preamble_ok = ("SECURITY: Command execution output follows." in content
                                       and "<<<STDOUT:" in content
                                       and "<<<END_STDOUT:" in content)
                        if preamble_ok:
                            checks[f"kw_{slug}_preamble_and_markers"] = True
                        # Required phrase: "active events" (case-insensitive) or "No markets found" (case-insensitive)
                        lower_c = content.lower()
                        phrase_ok = ("active events" in lower_c) or ("no markets found" in lower_c)
                        if phrase_ok:
                            checks[f"kw_{slug}_contains_required_phrase"] = True

            # Validate tag entries
            for tag in expected_tags:
                slug = key_slug(tag)
                entry = tags_obj.get(tag, {})
                raw_log = entry.get("raw_log", None)
                path_format_ok = isinstance(raw_log, str) and raw_log.startswith("output/raw/") and not raw_log.startswith("/")
                if path_format_ok:
                    checks[f"tag_{slug}_raw_log_path_format"] = True
                    raw_log_paths_collected.append(raw_log)

                if isinstance(raw_log, str):
                    abs_path = os.path.join(workspace_root, raw_log)
                    if os.path.isfile(abs_path):
                        checks[f"tag_{slug}_raw_log_file_exists"] = True
                        content = read_text(abs_path)
                        preamble_ok = ("SECURITY: Command execution output follows." in content
                                       and "<<<STDOUT:" in content
                                       and "<<<END_STDOUT:" in content)
                        if preamble_ok:
                            checks[f"tag_{slug}_preamble_and_markers"] = True
                        # Tag logs must contain exact substring "Active events ("
                        if "Active events (" in content:
                            checks[f"tag_{slug}_contains_active_events"] = True

            # Aggregate checks for distinct and relative paths
            # Only pass if we have collected all six paths and they are distinct and none absolute
            if len(raw_log_paths_collected) == 6:
                if len(set(raw_log_paths_collected)) == 6:
                    checks["raw_logs_all_distinct"] = True
                if all(isinstance(p, str) and not p.startswith("/") for p in raw_log_paths_collected):
                    checks["raw_logs_all_relative"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline: if nothing is in output or summary missing, passed_checks likely 0 -> reward 0.0
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()