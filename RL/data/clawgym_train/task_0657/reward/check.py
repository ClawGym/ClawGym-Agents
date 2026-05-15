import json
import os
import sys
import re

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_string_list(lst):
    if not isinstance(lst, list):
        return False
    for x in lst:
        if not isinstance(x, str):
            return False
    return True

def normalize_heading(line):
    # Strip markdown heading markers and bullets, normalize whitespace and case
    s = line.strip()
    s = re.sub(r'^[#\s\-*]+', '', s).strip()
    return s.lower()

def has_required_headings(text, required_phrases):
    lines = text.splitlines()
    found = set()
    for line in lines:
        norm = normalize_heading(line)
        if norm in required_phrases:
            found.add(norm)
    return all(r in found for r in required_phrases)

def validate_matches(matches):
    # Returns (bool, details) where bool indicates all matches valid per required fields,
    # and details contains auxiliary sets for further checks.
    allowed_types = {"exact", "likely", "weak", "not_verifiable", "no_result"}
    if not isinstance(matches, list) or len(matches) < 8:
        return False, {"platforms": set(), "types": set(), "http_ok": False}
    platforms = set()
    types_set = set()
    http_all = True

    for m in matches:
        if not isinstance(m, dict):
            return False, {"platforms": platforms, "types": types_set, "http_ok": False}
        platform = m.get("platform")
        url = m.get("url")
        final_url = m.get("final_url")
        match_type = m.get("match_type")
        score = m.get("confidence_score")
        notes = m.get("notes")

        if not isinstance(platform, str) or not platform.strip():
            return False, {"platforms": platforms, "types": types_set, "http_ok": False}

        # URL presence and http check
        url_val = url if isinstance(url, str) else (final_url if isinstance(final_url, str) else None)
        if not isinstance(url_val, str):
            return False, {"platforms": platforms, "types": types_set, "http_ok": False}
        if not url_val.startswith("http"):
            http_all = False

        if match_type not in allowed_types:
            return False, {"platforms": platforms, "types": types_set, "http_ok": False}

        # confidence_score numeric 0-100
        if not isinstance(score, (int, float)):
            return False, {"platforms": platforms, "types": types_set, "http_ok": False}
        if score < 0 or score > 100:
            return False, {"platforms": platforms, "types": types_set, "http_ok": False}

        if not isinstance(notes, str) or not notes.strip():
            return False, {"platforms": platforms, "types": types_set, "http_ok": False}

        platforms.add(str(platform).lower())
        types_set.add(match_type)

    return True, {"platforms": platforms, "types": types_set, "http_ok": http_all}

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    results_path = os.path.join(output_dir, "results.json")
    report_path = os.path.join(output_dir, "report.md")
    targets_path = os.path.join(input_dir, "targets.json")

    checks = {
        "results_exists": False,
        "results_json_valid": False,
        "results_structure_valid": False,
        "summary_confidence_allowed": False,
        "checked_platforms_valid": False,
        "matches_valid": False,
        "matches_urls_http": False,
        "matches_platform_coverage": False,
        "matches_distinct_platforms": False,
        "matches_distinct_match_types": False,
        "input_mirrors_reference": False,
        "report_exists": False,
        "report_has_required_sections": False,
    }

    results = None
    if os.path.isfile(results_path):
        checks["results_exists"] = True
        results = load_json(results_path)
        if results is not None:
            checks["results_json_valid"] = True

            # Structure checks
            top_ok = (
                isinstance(results.get("input"), dict) and
                isinstance(results.get("checked_platforms"), list) and
                isinstance(results.get("matches"), list) and
                isinstance(results.get("summary"), dict)
            )
            if top_ok:
                checks["results_structure_valid"] = True

                # Summary confidence
                conf = results.get("summary", {}).get("overall_confidence")
                if isinstance(conf, str) and conf in {"strong", "likely", "possible", "weak"}:
                    checks["summary_confidence_allowed"] = True

                # checked_platforms validity
                checked_platforms = results.get("checked_platforms")
                if is_string_list(checked_platforms) and len(checked_platforms) >= 5:
                    checks["checked_platforms_valid"] = True

                # Matches validation
                valid, details = validate_matches(results.get("matches"))
                if valid:
                    checks["matches_valid"] = True
                    if details.get("http_ok", False):
                        checks["matches_urls_http"] = True

                    # Distinct platform count
                    if len(details.get("platforms", set())) >= 5:
                        checks["matches_distinct_platforms"] = True

                    # Distinct match_type count
                    if len(details.get("types", set())) >= 4:
                        checks["matches_distinct_match_types"] = True

                    # Platform coverage: each match platform should appear in checked_platforms
                    cps = {p.lower() for p in (checked_platforms or []) if isinstance(p, str)}
                    platforms_in_matches = details.get("platforms", set())
                    if platforms_in_matches and platforms_in_matches.issubset(cps):
                        checks["matches_platform_coverage"] = True

                # Input mirroring check against input/targets.json
                targets = None
                if os.path.isfile(targets_path):
                    targets = load_json(targets_path)
                if isinstance(targets, dict) and results.get("input") == targets:
                    checks["input_mirrors_reference"] = True

    # Report checks
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
        except Exception:
            report_text = ""

        required = {
            "input",
            "target type",
            "strongest matches",
            "weaker / ambiguous findings",
            "confidence summary",
            "caveats & safety notes",
        }
        if report_text and has_required_headings(report_text, required):
            checks["report_has_required_sections"] = True

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0

    # No-op baseline: if output dir missing or both required artifacts absent, reward must be 0.0
    if not checks["results_exists"] and not checks["report_exists"]:
        reward = 0.0
    else:
        # Scale reward by proportion of passed checks
        if total_checks > 0:
            reward = passed_checks / total_checks
            # Bound to [0,1]
            if reward < 0:
                reward = 0.0
            if reward > 1:
                reward = 1.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()