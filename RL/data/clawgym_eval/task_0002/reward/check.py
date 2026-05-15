import json
import os
import sys
from typing import Any, Dict, List, Tuple

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Checks dictionary initialized to False
    checks: Dict[str, bool] = {
        # Report 1 checks
        "r1_exists_and_json": False,
        "r1_has_keys": False,
        "r1_summary_fields_match": False,
        "r1_groups_lengths": False,
        "r1_top_group_correct": False,
        "r1_all_groups_contains_required_entries": False,
        "r1_critical_instances_correct": False,
        # Report 2 checks
        "r2_exists_and_json": False,
        "r2_has_keys": False,
        "r2_summary_fields_match": False,
        "r2_groups_lengths": False,
        "r2_top_group_correct": False,
        "r2_all_groups_set_matches": False,
    }

    # Helper functions
    def approx_equal(a: float, b: float, tol: float = 0.001) -> bool:
        try:
            return abs(float(a) - float(b)) <= tol
        except Exception:
            return False

    def load_json(path: str) -> Any:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def has_top_keys(obj: Dict[str, Any]) -> bool:
        return all(k in obj for k in ("summary", "groups", "all_groups", "critical_instances"))

    def find_group(groups: List[Dict[str, Any]], repo: str, name: str) -> Dict[str, Any]:
        for g in groups:
            if g.get("repository") == repo and g.get("artifact_name") == name:
                return g
        return {}

    # Expected values from task specification for report.json (full) and report_filtered.json (filtered)
    # Report 1 expected summary fields
    r1_expected_summary = {
        "files_matched": 3,
        "files_scanned": 3,
        "records_scanned": 11,
        "records_filtered": 0,
        "records_missing_size": 1,
        "warn_mb": 300,
        "critical_mb": 900,
        "soon_expires_days": 0,
        "top_n": 5,
        "groups": 7,
        "critical_instances": 2,
    }

    # Report 1 expected top group
    r1_top_expected = {
        "repository": "acme/gizmos",
        "artifact_name": "dist-zip",
        "severity": "critical",
        "max_mb": 950.0,
        "total_mb": 1870.0,
        "instances": 2,
    }

    # Report 1 required groups presence and attributes in all_groups
    r1_required_all_groups = [
        ("acme/widgets", "coverage-html", {"severity": "warn", "expired_count": 1}),
        ("acme/widgets", "unit-tests", {"severity": "warn"}),
        ("acme/gadgets", "test-results-linux", {"severity": "warn"}),
        ("acme/gadgets", "test-results-macos", {"severity": "ok"}),
        ("acme/gizmos", "build-cache", {"severity": "ok"}),
        ("acme/widgets", "<unnamed-artifact>", {"severity": "ok"}),
    ]

    # Report 1 critical instances expected
    r1_expected_critical_ids = {2001, 2002}
    r1_expected_critical_repo = "acme/gizmos"
    r1_expected_critical_name = "dist-zip"

    # Report 2 expected summary fields
    r2_expected_summary_partial = {
        "warn_mb": 300,
        "critical_mb": 900,
        "soon_expires_days": 0,
        "top_n": 10,
        "critical_instances": 0,
        "groups": 3,
    }
    r2_expected_artifact_match = "(coverage|test-results)"

    # Report 2 expected top group
    r2_top_expected = {
        "repository": "acme/gadgets",
        "artifact_name": "test-results-linux",
        "severity": "warn",
        "max_mb": 700.0,
    }

    # Report 2 expected all_groups pair set
    r2_expected_pairs = {
        ("acme/widgets", "coverage-html"),
        ("acme/gadgets", "test-results-linux"),
        ("acme/gadgets", "test-results-macos"),
    }

    # Paths to output files
    report1_path = os.path.join(output_dir, "audit", "report.json")
    report2_path = os.path.join(output_dir, "audit", "report_filtered.json")

    # Validate Report 1
    report1: Dict[str, Any] = {}
    if os.path.isfile(report1_path):
        try:
            report1 = load_json(report1_path)
            checks["r1_exists_and_json"] = isinstance(report1, dict)
        except Exception:
            checks["r1_exists_and_json"] = False

    if checks["r1_exists_and_json"]:
        checks["r1_has_keys"] = has_top_keys(report1)

        if checks["r1_has_keys"]:
            r1_summary = report1.get("summary", {})
            r1_groups = report1.get("groups", [])
            r1_all_groups = report1.get("all_groups", [])
            r1_critical_instances = report1.get("critical_instances", [])

            # Summary fields
            summary_ok = True
            for k, v in r1_expected_summary.items():
                if k not in r1_summary:
                    summary_ok = False
                    break
                if r1_summary[k] != v:
                    summary_ok = False
                    break
            checks["r1_summary_fields_match"] = summary_ok

            # Groups lengths
            checks["r1_groups_lengths"] = (
                isinstance(r1_groups, list) and isinstance(r1_all_groups, list)
                and len(r1_groups) == 5 and len(r1_all_groups) == 7
            )

            # Top group correct
            top_ok = False
            if isinstance(r1_groups, list) and len(r1_groups) >= 1:
                top = r1_groups[0]
                try:
                    top_ok = (
                        top.get("repository") == r1_top_expected["repository"]
                        and top.get("artifact_name") == r1_top_expected["artifact_name"]
                        and top.get("severity") == r1_top_expected["severity"]
                        and int(top.get("instances")) == r1_top_expected["instances"]
                        and approx_equal(float(top.get("max_mb")), r1_top_expected["max_mb"])
                        and approx_equal(float(top.get("total_mb")), r1_top_expected["total_mb"])
                    )
                except Exception:
                    top_ok = False
            checks["r1_top_group_correct"] = top_ok

            # all_groups contains required entries
            all_groups_ok = True
            for repo, name, attrs in r1_required_all_groups:
                g = find_group(r1_all_groups, repo, name)
                if not g:
                    all_groups_ok = False
                    break
                # Check severity
                if "severity" in attrs and g.get("severity") != attrs["severity"]:
                    all_groups_ok = False
                    break
                # Check expired_count if provided
                if "expired_count" in attrs:
                    try:
                        if int(g.get("expired_count")) != int(attrs["expired_count"]):
                            all_groups_ok = False
                            break
                    except Exception:
                        all_groups_ok = False
                        break
            checks["r1_all_groups_contains_required_entries"] = all_groups_ok

            # critical_instances correctness
            crit_ok = False
            try:
                if isinstance(r1_critical_instances, list) and len(r1_critical_instances) == 2:
                    ids = set()
                    valid = True
                    for inst in r1_critical_instances:
                        if inst.get("repository") != r1_expected_critical_repo:
                            valid = False
                            break
                        if inst.get("artifact_name") != r1_expected_critical_name:
                            valid = False
                            break
                        aid = inst.get("artifact_id")
                        # Must be numeric 2001/2002 or coercible
                        try:
                            ids.add(int(aid))
                        except Exception:
                            valid = False
                            break
                    crit_ok = valid and ids == r1_expected_critical_ids
            except Exception:
                crit_ok = False
            checks["r1_critical_instances_correct"] = crit_ok

    # Validate Report 2
    report2: Dict[str, Any] = {}
    if os.path.isfile(report2_path):
        try:
            report2 = load_json(report2_path)
            checks["r2_exists_and_json"] = isinstance(report2, dict)
        except Exception:
            checks["r2_exists_and_json"] = False

    if checks["r2_exists_and_json"]:
        checks["r2_has_keys"] = has_top_keys(report2)

        if checks["r2_has_keys"]:
            r2_summary = report2.get("summary", {})
            r2_groups = report2.get("groups", [])
            r2_all_groups = report2.get("all_groups", [])
            r2_critical_instances = report2.get("critical_instances", [])

            # Summary fields (partial exact match plus filters.artifact_match)
            summary2_ok = True
            for k, v in r2_expected_summary_partial.items():
                if k not in r2_summary or r2_summary[k] != v:
                    summary2_ok = False
                    break
            # filters.artifact_match must be present and equal
            if summary2_ok:
                filters = r2_summary.get("filters", {})
                if not isinstance(filters, dict) or filters.get("artifact_match") != r2_expected_artifact_match:
                    summary2_ok = False
            checks["r2_summary_fields_match"] = summary2_ok

            # Groups lengths
            checks["r2_groups_lengths"] = (
                isinstance(r2_groups, list) and isinstance(r2_all_groups, list)
                and len(r2_groups) == 3 and len(r2_all_groups) == 3
            )

            # Top group correct
            top2_ok = False
            if isinstance(r2_groups, list) and len(r2_groups) >= 1:
                top = r2_groups[0]
                try:
                    top2_ok = (
                        top.get("repository") == r2_top_expected["repository"]
                        and top.get("artifact_name") == r2_top_expected["artifact_name"]
                        and top.get("severity") == r2_top_expected["severity"]
                        and approx_equal(float(top.get("max_mb")), r2_top_expected["max_mb"])
                    )
                except Exception:
                    top2_ok = False
            checks["r2_top_group_correct"] = top2_ok

            # all_groups pair set matches expected
            pairs = set()
            try:
                for g in r2_all_groups:
                    pairs.add((g.get("repository"), g.get("artifact_name")))
                checks["r2_all_groups_set_matches"] = (pairs == r2_expected_pairs)
            except Exception:
                checks["r2_all_groups_set_matches"] = False

    # Compute reward as fraction of checks passed; ensure 0.0 if no output artifacts
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # Enforce no-op baseline: if both reports missing, reward must be 0.0
    no_outputs = not checks["r1_exists_and_json"] and not checks["r2_exists_and_json"]
    if no_outputs:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Emit final JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()