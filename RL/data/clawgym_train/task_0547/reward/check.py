import json
import os
import re
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, ""

def split_lines(text):
    return text.splitlines()

def find_section_indices(lines, heading):
    # Return index of heading line or -1 if not found
    for i, line in enumerate(lines):
        if line.strip() == heading:
            return i
    return -1

def extract_section(lines, start_idx, next_start_idx):
    # Extract lines from start_idx to next_start_idx (exclusive)
    if start_idx < 0:
        return ""
    end = next_start_idx if next_start_idx is not None and next_start_idx > start_idx else len(lines)
    section_lines = lines[start_idx:end]
    return "\n".join(section_lines)

def line_startswith_any(line, prefixes):
    s = line.lstrip()
    return any(s.startswith(p) for p in prefixes)

def get_last_nonempty_line(text):
    lines = [ln.rstrip() for ln in text.splitlines()]
    for ln in reversed(lines):
        if ln.strip() != "":
            return ln
    return ""

def section_contains_keywords(text, required_all=None, required_any=None):
    t = text.lower()
    if required_all:
        for kw in required_all:
            if kw.lower() not in t:
                return False
    if required_any:
        if not any(kw.lower() in t for kw in required_any):
            return False
    return True

def validate_trust_scores_schema(objs):
    # Validate fields and types across all objects
    allowed_risks = {"Low", "Medium", "High", "Critical"}
    for obj in objs:
        # Required keys
        required_keys = {"name", "trust_score", "risk", "permissions", "issues", "positives"}
        if not isinstance(obj, dict):
            return False
        if not required_keys.issubset(set(obj.keys())):
            return False
        # Types
        if not isinstance(obj["name"], str):
            return False
        if not isinstance(obj["trust_score"], int):
            return False
        if not (0 <= obj["trust_score"] <= 100):
            return False
        if not isinstance(obj["risk"], str) or obj["risk"] not in allowed_risks:
            return False
        if not isinstance(obj["permissions"], dict):
            return False
        if "bins" not in obj["permissions"] or "env" not in obj["permissions"]:
            return False
        if not isinstance(obj["permissions"]["bins"], list) or not isinstance(obj["permissions"]["env"], list):
            return False
        if not all(isinstance(x, str) for x in obj["permissions"]["bins"]):
            return False
        if not all(isinstance(x, str) for x in obj["permissions"]["env"]):
            return False
        if not isinstance(obj["issues"], list) or not all(isinstance(x, str) for x in obj["issues"]):
            return False
        if not isinstance(obj["positives"], list) or not all(isinstance(x, str) for x in obj["positives"]):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # trust_scores.json presence and structure
        "has_trust_scores_file": False,
        "trust_scores_parses": False,
        "trust_scores_len_is_3": False,
        "trust_scores_all_objects": False,
        "trust_scores_schema_fields_types": False,
        "trust_scores_names_exact": False,
        "trust_scores_shadow_runner_constraints": False,
        "trust_scores_markdown_exporter_constraints": False,
        "trust_scores_metrics_pinger_constraints": False,
        # security_report.md presence and content
        "has_security_report_file": False,
        "report_has_all_headings": False,
        "report_trust_score_lines_ok": False,
        "report_permissions_subsections_ok": False,
        "report_issues_subsections_ok": False,
        "report_positives_subsections_ok": False,
        "report_recommendation_lines_ok": False,
        "report_keywords_shadow_runner": False,
        "report_keywords_metrics_pinger": False,
        "report_keywords_markdown_exporter": False,
    }

    # Paths
    trust_scores_path = os.path.join(output_dir, "trust_scores.json")
    security_report_path = os.path.join(output_dir, "security_report.md")

    # Expected modules
    expected_names = ["markdown-exporter", "metrics-pinger", "shadow-runner"]
    expected_set = set(expected_names)

    # 1) trust_scores.json checks
    if os.path.isfile(trust_scores_path):
        checks["has_trust_scores_file"] = True
        parsed, data = load_json_file(trust_scores_path)
        if parsed:
            checks["trust_scores_parses"] = True
            if isinstance(data, list):
                if len(data) == 3:
                    checks["trust_scores_len_is_3"] = True
                if all(isinstance(x, dict) for x in data):
                    checks["trust_scores_all_objects"] = True
                if checks["trust_scores_all_objects"]:
                    if validate_trust_scores_schema(data):
                        checks["trust_scores_schema_fields_types"] = True
                        # Names exact
                        names = [obj["name"] for obj in data]
                        if set(names) == expected_set and len(names) == 3:
                            checks["trust_scores_names_exact"] = True
                        # Per-module constraints
                        name_to_obj = {obj["name"]: obj for obj in data if isinstance(obj, dict) and "name" in obj}
                        # shadow-runner
                        if "shadow-runner" in name_to_obj:
                            sr = name_to_obj["shadow-runner"]
                            if isinstance(sr.get("trust_score"), int) and sr.get("risk") == "Critical" and sr["trust_score"] <= 39:
                                checks["trust_scores_shadow_runner_constraints"] = True
                        # markdown-exporter
                        if "markdown-exporter" in name_to_obj:
                            me = name_to_obj["markdown-exporter"]
                            if isinstance(me.get("trust_score"), int) and me.get("risk") == "Low" and me["trust_score"] >= 80:
                                checks["trust_scores_markdown_exporter_constraints"] = True
                        # metrics-pinger
                        if "metrics-pinger" in name_to_obj:
                            mp = name_to_obj["metrics-pinger"]
                            risk_ok = mp.get("risk") in {"Medium", "High"}
                            issues = mp.get("issues")
                            issues_has_kw = False
                            if isinstance(issues, list):
                                for itm in issues:
                                    if isinstance(itm, str):
                                        low = itm.lower()
                                        if ("network" in low) or ("token" in low):
                                            issues_has_kw = True
                                            break
                            if risk_ok and issues_has_kw:
                                checks["trust_scores_metrics_pinger_constraints"] = True

    # 2) security_report.md checks
    if os.path.isfile(security_report_path):
        checks["has_security_report_file"] = True
        ok, report_text = read_text_file(security_report_path)
        if ok:
            lines = split_lines(report_text)
            # Find headings
            headings_map = {}
            for name in expected_names:
                h = f"## {name}"
                idx = find_section_indices(lines, h)
                if idx >= 0:
                    headings_map[name] = idx
            if len(headings_map) == 3:
                checks["report_has_all_headings"] = True
                # Determine section boundaries by next heading index
                ordered_names = expected_names[:]  # keep the specified order
                indices = [headings_map[n] for n in ordered_names]
                # Map of module -> section text
                sections = {}
                for i, name in enumerate(ordered_names):
                    start_idx = headings_map[name]
                    # next heading index among any module that is greater than start
                    next_indices = [headings_map[nm] for nm in ordered_names if headings_map[nm] > start_idx]
                    next_idx = min(next_indices) if next_indices else None
                    sections[name] = extract_section(lines, start_idx, next_idx)

                # Trust Score line check per module
                trust_line_ok_all = True
                risk_levels = "(Low|Medium|High|Critical)"
                pattern = re.compile(r'^Trust Score:\s*(\d{1,3})/100\s*\(Risk:\s*' + risk_levels + r'\)', re.IGNORECASE)
                for name, text in sections.items():
                    found = False
                    for ln in text.splitlines():
                        if ln.lstrip().startswith("Trust Score:"):
                            if pattern.match(ln.strip()):
                                found = True
                                break
                    if not found:
                        trust_line_ok_all = False
                        break
                if trust_line_ok_all:
                    checks["report_trust_score_lines_ok"] = True

                # Permissions subsections and presence of bins/env
                perms_ok_all = True
                for name, text in sections.items():
                    text_lower = text.lower()
                    if "permissions requested:" not in text_lower:
                        perms_ok_all = False
                        break
                    # also require mention of bins and env somewhere in the section
                    if "bins" not in text_lower or "env" not in text_lower:
                        perms_ok_all = False
                        break
                if perms_ok_all:
                    checks["report_permissions_subsections_ok"] = True

                # Issues subsections
                issues_ok_all = True
                for name, text in sections.items():
                    if "issues found:" not in text.lower():
                        issues_ok_all = False
                        break
                if issues_ok_all:
                    checks["report_issues_subsections_ok"] = True

                # Positives subsections
                positives_ok_all = True
                for name, text in sections.items():
                    if "positive signs:" not in text.lower():
                        positives_ok_all = False
                        break
                if positives_ok_all:
                    checks["report_positives_subsections_ok"] = True

                # Recommendation line must be final non-empty line of each section
                rec_ok_all = True
                for name, text in sections.items():
                    last_line = get_last_nonempty_line(text)
                    if not last_line.strip().startswith("Recommendation:"):
                        rec_ok_all = False
                        break
                if rec_ok_all:
                    checks["report_recommendation_lines_ok"] = True

                # Keyword content checks
                # shadow-runner: "base64" AND at least one of ("rm -rf", "credential", "aws") AND one of ("exfil", "curl")
                sr_text = sections.get("shadow-runner", "")
                sr_ok = section_contains_keywords(sr_text, required_all=["base64"]) and \
                        section_contains_keywords(sr_text, required_any=["rm -rf", "credential", "aws"]) and \
                        section_contains_keywords(sr_text, required_any=["exfil", "curl"])
                if sr_ok:
                    checks["report_keywords_shadow_runner"] = True

                # metrics-pinger: include "curl" or "network"
                mp_text = sections.get("metrics-pinger", "")
                if section_contains_keywords(mp_text, required_any=["curl", "network"]):
                    checks["report_keywords_metrics_pinger"] = True

                # markdown-exporter: include "minimal permissions" or "none"
                me_text = sections.get("markdown-exporter", "")
                if section_contains_keywords(me_text, required_any=["minimal permissions", "none"]):
                    checks["report_keywords_markdown_exporter"] = True

    # Compute reward: proportion of passed checks; enforce 0.0 if no outputs
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if any([checks["has_trust_scores_file"], checks["has_security_report_file"]]):
        reward = passed / total_checks
    else:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()