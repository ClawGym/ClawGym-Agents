import json
import os
import sys
from collections import OrderedDict

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def build_paths(workspace_root):
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")
    return input_dir, output_dir, reward_dir

def normalize_skills(skills_node):
    # Returns dict: name -> set(files)
    result = {}
    if isinstance(skills_node, dict):
        for name, files in skills_node.items():
            if isinstance(files, list):
                result[str(name)] = set(str(x) for x in files)
    elif isinstance(skills_node, list):
        for entry in skills_node:
            if isinstance(entry, dict):
                name = entry.get("name")
                files = entry.get("files", [])
                if isinstance(name, str) and isinstance(files, list):
                    result[name] = set(str(x) for x in files)
            elif isinstance(entry, str):
                # No file list available
                result[entry] = set()
    return result

def compute_skill_quality(skills_map):
    total = len(skills_map)
    complete = incomplete = broken = 0
    for name, files in skills_map.items():
        has_index = "index.js" in files
        has_skill_md = "SKILL.md" in files
        if has_index and has_skill_md:
            complete += 1
        elif has_index ^ has_skill_md:
            incomplete += 1
        else:
            broken += 1
    complete_percent = round((complete / total) * 100) if total > 0 else 0
    incomplete_percent = round((incomplete / total) * 100) if total > 0 else 0
    status = "pass"
    if complete_percent < 50:
        status = "critical"
    elif complete_percent < 75:
        status = "warning"
    return {
        "status": status,
        "total": total,
        "complete": complete,
        "incomplete": incomplete,
        "broken": broken,
        "details": {
            "completePercent": complete_percent,
            "incompletePercent": incomplete_percent
        }
    }

def compute_dependencies(package_node):
    deps = {}
    if isinstance(package_node, dict):
        d1 = package_node.get("dependencies") or {}
        d2 = package_node.get("devDependencies") or {}
        if isinstance(d1, dict):
            for k in d1.keys():
                deps[k] = True
        if isinstance(d2, dict):
            for k in d2.keys():
                deps[k] = True
    scanned = len(deps)
    return {
        "status": "pass",
        "scanned": scanned,
        "vulnerabilities": 0,
        "details": {
            "totalDependencies": scanned
        },
        "message": f"{scanned} dependencies found. Run npm audit for full scan."
    }

def compute_cleanup(skills_map, extras_list):
    junk_patterns = ["__MACOSX", ".DS_Store", ".usage-tracker"]
    junk_folders = 0
    if isinstance(extras_list, list):
        for name in extras_list:
            try:
                s = str(name)
            except Exception:
                s = ""
            for p in junk_patterns:
                if p in s:
                    junk_folders += 1
                    break
    incomplete_skills = 0
    for name, files in skills_map.items():
        if "index.js" not in files:
            incomplete_skills += 1
    status = "pass"
    if junk_folders > 0 or incomplete_skills > 100:
        status = "warning"
    return {
        "status": status,
        "junkFolders": junk_folders,
        "incompleteSkills": incomplete_skills,
        "potentialSavings": 0,
        "details": {
            "junkFolders": junk_folders,
            "incompleteSkills": incomplete_skills
        }
    }

def compute_protected(skills_map):
    protected_list = [
        "evolver","feishu-evolver-wrapper","feishu-common","feishu-post",
        "feishu-card","feishu-doc","feishu-doc","common","clawhub","git-sync",
        "downloader","uploader","xfyun-search","xfyun-tts","podcast-gen","weather",
        "healthcheck","skill-creator","skill-quality-auditor","skill-cleanup-executor",
        "workspace-health-dashboard"
    ]
    # The list above contains "feishu-doc" twice due to a typo; ensure uniqueness while preserving order
    seen = set()
    ordered_protected = []
    for item in protected_list:
        if item not in seen:
            seen.add(item)
            ordered_protected.append(item)
    names_present = set(skills_map.keys())
    present_count = 0
    missing = []
    for item in ordered_protected:
        if item in names_present:
            present_count += 1
        else:
            missing.append(item)
    status = "pass" if len(missing) == 0 else "warning"
    return {
        "status": status,
        "protected": present_count,
        "missing": missing,
        "details": {
            "protectedCount": present_count,
            "missingCount": len(missing)
        }
    }

def compute_summary(skill_quality, deps, cleanup, protected_check):
    checks_total = 4
    statuses = {
        "skillQuality": skill_quality.get("status"),
        "dependencies": deps.get("status"),
        "cleanup": cleanup.get("status"),
        "protectedSkills": protected_check.get("status"),
    }
    passed = 0
    warnings = 0
    critical = 0
    for key, status in statuses.items():
        if status == "pass":
            passed += 1
        elif status == "warning":
            warnings += 1
        elif status == "critical":
            critical += 1
    # Special rule: protectedSkills counts as passed in the summary regardless of its status (if no error)
    if statuses.get("protectedSkills") in ("pass", "warning", "critical"):
        # The task specifies "as long as no error occurs" — we only set counts for pass/warning/critical
        # and do not model "error" here, so we always add 1 for protectedSkills.
        passed += 1
        # Do not decrement warnings if protected is warning; warnings remain as calculated.
    score = round((passed / checks_total) * 100) if checks_total > 0 else 0
    if critical > 0:
        overall = "critical"
    elif warnings > 0:
        overall = "warning"
    else:
        overall = "healthy"
    return {
        "overallHealth": overall,
        "score": score,
        "checks": checks_total,
        "passed": passed,
        "warnings": warnings,
        "critical": critical
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir = build_paths(workspace_root)

    # Initialize checks - all False by default
    checks = OrderedDict()
    checks["dashboard_json_exists"] = False
    checks["dashboard_json_valid"] = False
    checks["dashboard_json_skill_quality_expected"] = False
    checks["dashboard_json_dependencies_expected"] = False
    checks["dashboard_json_cleanup_expected"] = False
    checks["dashboard_json_protected_expected"] = False
    checks["dashboard_json_summary_expected"] = False
    checks["dashboard_txt_exists"] = False
    checks["dashboard_txt_contains_overall_warning"] = False
    checks["dashboard_txt_contains_score_50"] = False
    checks["dashboard_txt_contains_checks_2_of_4"] = False
    checks["remediation_md_exists"] = False
    checks["remediation_md_min_bullets"] = False
    checks["remediation_md_mentions_skills"] = False
    checks["remediation_md_mentions_junk"] = False
    checks["remediation_md_mentions_protected_or_missing"] = False

    # Load input snapshot for expected computation
    snapshot_path = os.path.join(input_dir, "workspace_snapshot.json")
    snapshot, snapshot_err = load_json_file(snapshot_path)
    # We must compute expectations from input; if input missing or invalid, we still do not award positives.

    expected = None
    if snapshot is not None:
        skills_map = normalize_skills(snapshot.get("skills"))
        package_node = snapshot.get("package", {})
        extras_list = snapshot.get("skills_root_extras", [])

        expected_skill_quality = compute_skill_quality(skills_map)
        expected_dependencies = compute_dependencies(package_node)
        expected_cleanup = compute_cleanup(skills_map, extras_list)
        expected_protected = compute_protected(skills_map)
        expected_summary = compute_summary(
            expected_skill_quality, expected_dependencies, expected_cleanup, expected_protected
        )
        expected = {
            "skillQuality": expected_skill_quality,
            "dependencies": expected_dependencies,
            "cleanup": expected_cleanup,
            "protectedSkills": expected_protected,
            "summary": expected_summary
        }

    # Validate dashboard.json
    dashboard_json_path = os.path.join(output_dir, "dashboard.json")
    if os.path.isfile(dashboard_json_path):
        checks["dashboard_json_exists"] = True
        data, err = load_json_file(dashboard_json_path)
        if err is None and isinstance(data, dict):
            # basic structure
            timestamp_ok = isinstance(data.get("timestamp"), str)
            version_ok = data.get("version") == "1.0.0"
            summary_ok = isinstance(data.get("summary"), dict)
            checks_node = data.get("checks")
            checks_ok = isinstance(checks_node, dict) and all(
                k in checks_node for k in ("skillQuality", "dependencies", "cleanup", "protectedSkills")
            )
            if timestamp_ok and version_ok and summary_ok and checks_ok:
                checks["dashboard_json_valid"] = True

                if expected is not None:
                    # Compare Skill Quality
                    dq = checks_node.get("skillQuality", {})
                    try:
                        sq_match = (
                            dq.get("status") == expected["skillQuality"]["status"] and
                            dq.get("total") == expected["skillQuality"]["total"] and
                            dq.get("complete") == expected["skillQuality"]["complete"] and
                            dq.get("incomplete") == expected["skillQuality"]["incomplete"] and
                            dq.get("broken") == expected["skillQuality"]["broken"] and
                            isinstance(dq.get("details"), dict) and
                            dq["details"].get("completePercent") == expected["skillQuality"]["details"]["completePercent"] and
                            dq["details"].get("incompletePercent") == expected["skillQuality"]["details"]["incompletePercent"]
                        )
                    except Exception:
                        sq_match = False
                    if sq_match:
                        checks["dashboard_json_skill_quality_expected"] = True

                    # Compare Dependencies
                    dd = checks_node.get("dependencies", {})
                    dep_match = (
                        dd.get("status") == expected["dependencies"]["status"] and
                        dd.get("scanned") == expected["dependencies"]["scanned"] and
                        isinstance(dd.get("message"), str) and
                        f"{expected['dependencies']['scanned']} dependencies found" in dd.get("message", "")
                    )
                    if dep_match:
                        checks["dashboard_json_dependencies_expected"] = True

                    # Compare Cleanup
                    dc = checks_node.get("cleanup", {})
                    cleanup_match = (
                        dc.get("status") == expected["cleanup"]["status"] and
                        dc.get("junkFolders") == expected["cleanup"]["junkFolders"] and
                        dc.get("incompleteSkills") == expected["cleanup"]["incompleteSkills"]
                    )
                    if cleanup_match:
                        checks["dashboard_json_cleanup_expected"] = True

                    # Compare Protected
                    dp = checks_node.get("protectedSkills", {})
                    protected_match = (
                        dp.get("status") == expected["protectedSkills"]["status"] and
                        dp.get("protected") == expected["protectedSkills"]["protected"] and
                        isinstance(dp.get("missing"), list) and
                        len(dp.get("missing")) == len(expected["protectedSkills"]["missing"]) and
                        isinstance(dp.get("details"), dict) and
                        dp["details"].get("missingCount") == expected["protectedSkills"]["details"]["missingCount"]
                    )
                    if protected_match:
                        checks["dashboard_json_protected_expected"] = True

                    # Compare Summary
                    ds = data.get("summary", {})
                    summary_match = (
                        ds.get("overallHealth") == expected["summary"]["overallHealth"] and
                        ds.get("score") == expected["summary"]["score"] and
                        ds.get("checks") == expected["summary"]["checks"] and
                        ds.get("passed") == expected["summary"]["passed"] and
                        ds.get("warnings") == expected["summary"]["warnings"] and
                        ds.get("critical") == expected["summary"]["critical"]
                    )
                    if summary_match:
                        checks["dashboard_json_summary_expected"] = True

    # Validate dashboard.txt
    dashboard_txt_path = os.path.join(output_dir, "dashboard.txt")
    if os.path.isfile(dashboard_txt_path):
        checks["dashboard_txt_exists"] = True
        try:
            content = open(dashboard_txt_path, "r", encoding="utf-8").read()
        except Exception:
            content = ""
        lc = content.lower()
        if "overall health:" in lc and "warning" in lc:
            checks["dashboard_txt_contains_overall_warning"] = True
        if "Score: 50/100" in content:
            checks["dashboard_txt_contains_score_50"] = True
        if "Checks: 2/4 passed" in content:
            checks["dashboard_txt_contains_checks_2_of_4"] = True

    # Validate remediation.md
    remediation_md_path = os.path.join(output_dir, "remediation.md")
    if os.path.isfile(remediation_md_path):
        checks["remediation_md_exists"] = True
        try:
            rcontent = open(remediation_md_path, "r", encoding="utf-8").read()
        except Exception:
            rcontent = ""
        lines = rcontent.splitlines()
        bullet_count = 0
        for line in lines:
            s = line.lstrip()
            if s.startswith("-") or s.startswith("*"):
                bullet_count += 1
        if bullet_count >= 3:
            checks["remediation_md_min_bullets"] = True
        lc_r = rcontent.lower()
        if ("feishu-doc" in rcontent) and ("weather" in rcontent):
            checks["remediation_md_mentions_skills"] = True
        if ("__MACOSX" in rcontent) or (".DS_Store" in rcontent):
            checks["remediation_md_mentions_junk"] = True
        if ("protected" in lc_r) or ("missing" in lc_r):
            checks["remediation_md_mentions_protected_or_missing"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or empty, ensure reward is exactly 0.0
    if (not os.path.isdir(output_dir)) or (len([name for name in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, name))]) == 0):
        reward = 0.0

    # Build result with "reward" first
    result = OrderedDict()
    result["reward"] = reward
    for k, v in checks.items():
        result[k] = v

    print(json.dumps(result))

if __name__ == "__main__":
    main()