import json
import sys
import csv
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return rows
    except Exception:
        return None


def parse_teams_yaml(content: str) -> Optional[Dict[str, Dict[str, Any]]]:
    # Minimal parser for the specific teams.yaml structure used in this task
    # Expected structure:
    # teams:
    #   team-slug:
    #     key: value
    #     ...
    try:
        teams: Dict[str, Dict[str, Any]] = {}
        lines = content.splitlines()
        in_teams = False
        current_team: Optional[str] = None
        for raw_line in lines:
            line = raw_line.rstrip("\n")
            # ignore comments
            if "#" in line:
                # YAML comments start with # but values might include # in quoted strings; given inputs don't, so safe:
                pass
            stripped = line.strip()
            if not stripped:
                continue
            # top-level key
            if not line.startswith(" "):
                # reset state
                current_team = None
                # Expect "teams:"
                if stripped == "teams:":
                    in_teams = True
                else:
                    # other top-level keys not expected
                    continue
                continue
            if not in_teams:
                continue
            # team slug level: two spaces then "slug:"
            if line.startswith("  ") and not line.startswith("    "):
                # two-space indent
                inner = line.strip()
                if inner.endswith(":"):
                    team_slug = inner[:-1].strip()
                    if team_slug:
                        current_team = team_slug
                        teams[current_team] = {}
                continue
            # property level: four spaces
            if current_team and line.startswith("    "):
                inner = line.strip()
                # key: value
                if ":" in inner:
                    key, val = inner.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    # remove surrounding quotes if present
                    if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                        val = val[1:-1]
                    elif val.startswith("'") and val.endswith("'") and len(val) >= 2:
                        val = val[1:-1]
                    # empty string should become ""
                    if val == "null" or val == "~":
                        val = None
                    teams[current_team][key] = val
                continue
        return teams
    except Exception:
        return None


def parse_codeowners(content: str) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Split by whitespace. First token is pattern, rest are owners
        tokens = line.split()
        if not tokens:
            continue
        pattern = tokens[0]
        owners = tokens[1:]
        for owner_tok in owners:
            # strip leading '@'
            owner = owner_tok.lstrip("@")
            if owner:
                entries.append((pattern, owner))
    return entries


def extract_maintainers_from_pyproject(content: str) -> List[str]:
    # We only need project.maintainers array of inline tables containing name fields
    # We'll implement a simple state machine to detect [project] section and parse maintainers block
    maintainers: List[str] = []
    in_project = False
    in_maintainers = False
    buf = ""
    bracket_depth = 0
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]") and line == "[project]":
            in_project = True
            in_maintainers = False
            continue
        if line.startswith("[") and line.endswith("]") and line != "[project]":
            in_project = False
            in_maintainers = False
            continue
        if not in_project:
            continue
        if not in_maintainers:
            # start of maintainers array
            if line.startswith("maintainers") and "=" in line and "[" in line:
                # Accumulate from '[' to closing ']' possibly across multiple lines
                idx = line.index("[")
                buf = line[idx:]
                bracket_depth = buf.count("[") - buf.count("]")
                in_maintainers = True
                if bracket_depth == 0:
                    in_maintainers = False
                    # parse buf
                    maintainers.extend(_extract_names_from_toml_array(buf))
                    buf = ""
            continue
        else:
            buf += " " + line
            bracket_depth = buf.count("[") - buf.count("]")
            if bracket_depth == 0:
                in_maintainers = False
                maintainers.extend(_extract_names_from_toml_array(buf))
                buf = ""
    return maintainers


def _extract_names_from_toml_array(array_text: str) -> List[str]:
    # array_text like: [ { name = "X", email = "..." }, { name = "Y", email = "..." } ]
    names: List[str] = []
    # find occurrences of name = "..."
    for match in re.finditer(r'name\s*=\s*"([^"]+)"', array_text):
        names.append(match.group(1))
    return names


def extract_maintainers_from_package_json(content: str) -> List[str]:
    try:
        data = json.loads(content)
        maintainers_field = data.get("maintainers", [])
        names: List[str] = []
        if isinstance(maintainers_field, list):
            for item in maintainers_field:
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str):
                        names.append(name)
        return names
    except Exception:
        return []


def get_repos(workspace: Path) -> List[Path]:
    repos_root = workspace / "repos"
    if not repos_root.exists():
        return []
    return sorted([p for p in repos_root.iterdir() if p.is_dir()])


def compute_expected(workspace: Path) -> Dict[str, Any]:
    # Load inputs
    teams_path = workspace / "input" / "teams.yaml"
    org_changes_path = workspace / "input" / "org_changes.csv"
    teams_content = read_text(teams_path) or ""
    org_changes_rows = load_csv_dicts(org_changes_path) or []
    teams = parse_teams_yaml(teams_content) if teams_content else None
    if teams is None:
        teams = {}

    # Prepare org changes lookup
    changes_by_team = {}
    for row in org_changes_rows:
        t = (row.get("team") or "").strip()
        ct = (row.get("change_type") or "").strip()
        if not t:
            continue
        changes_by_team.setdefault(t, []).append(ct)

    repos_info: List[Dict[str, Any]] = []
    unknown_owners_set = set()
    missing_root_owner_list: List[str] = []
    # Gather teams that appear in codeowners with merged/dissolved to cross-validate
    merged_dissolved_teams_in_codeowners = set()

    for repo_path in get_repos(workspace):
        repo_name = repo_path.name
        codeowners_path = repo_path / "CODEOWNERS"
        codeowners_content = read_text(codeowners_path) or ""
        entries: List[Tuple[str, str]] = []
        if codeowners_content:
            entries = parse_codeowners(codeowners_content)
        patterns_list: List[Dict[str, Any]] = []
        # Build owner meta
        for pattern, owner in entries:
            team_info = teams.get(owner)
            if team_info is None:
                owner_status = "unknown"
                merged_into = None
                canonical_name = None
                impacted = True
                unknown_owners_set.add(owner)
            else:
                status = str(team_info.get("status", "")).strip()
                if status not in ("active", "merged_into", "dissolved"):
                    # treat anything else as unknown
                    owner_status = "unknown"
                    merged_into = None
                    canonical_name = team_info.get("canonical_name")
                    impacted = True
                else:
                    owner_status = status
                    merged_into = team_info.get("merged_into") if status == "merged_into" else None
                    canonical_name = team_info.get("canonical_name")
                    impacted = status != "active"
                    if status in ("merged_into", "dissolved"):
                        merged_dissolved_teams_in_codeowners.add(owner)
            patterns_list.append({
                "pattern": pattern,
                "owner": owner,
                "owner_status": owner_status,
                "merged_into": merged_into if merged_into is not None else None,
                "canonical_name": canonical_name if canonical_name is not None else None,
                "impacted": bool(impacted),
            })
        # dominant owner
        root_entries = [o for (p, o) in entries if p == "/"]
        dominant_owner = root_entries[0] if root_entries else None
        if dominant_owner is None:
            missing_root_owner_list.append(repo_name)
        # maintainers
        maintainers: List[str] = []
        pyproject_path = repo_path / "pyproject.toml"
        package_json_path = repo_path / "package.json"
        if pyproject_path.exists():
            py_content = read_text(pyproject_path) or ""
            if py_content:
                maintainers = extract_maintainers_from_pyproject(py_content)
        elif package_json_path.exists():
            pj_content = read_text(package_json_path) or ""
            if pj_content:
                maintainers = extract_maintainers_from_package_json(pj_content)
        else:
            maintainers = []
        # alignment
        maint_alignment = "mismatch"
        if dominant_owner is not None and dominant_owner in teams:
            manager_after = teams[dominant_owner].get("manager_after")
            if isinstance(manager_after, str) and manager_after:
                if any(m == manager_after for m in maintainers):
                    maint_alignment = "aligned"
        else:
            maint_alignment = "mismatch"
        # counts
        total_patterns = len(patterns_list)
        impacted_patterns = sum(1 for it in patterns_list if it.get("impacted"))
        percent_impacted = (impacted_patterns / total_patterns * 100.0) if total_patterns > 0 else 0.0

        repos_info.append({
            "name": repo_name,
            "dominant_owner": dominant_owner if dominant_owner is not None else None,
            "maintainer_names": maintainers,
            "maintainer_alignment": maint_alignment,
            "patterns": patterns_list,
            "counts": {
                "total_patterns": total_patterns,
                "impacted_patterns": impacted_patterns,
                "percent_impacted": percent_impacted,
            }
        })

    # Cross-validation mismatches
    org_mismatches: List[str] = []
    # Rule 1: For every team appearing in CODEOWNERS with status merged_into or dissolved, assert matching row exists with change_type merged or dissolved respectively
    for team in sorted(merged_dissolved_teams_in_codeowners):
        team_info = teams.get(team, {})
        status = str(team_info.get("status", "")).strip()
        if status not in ("merged_into", "dissolved"):
            continue
        expected_change = "merged" if status == "merged_into" else "dissolved"
        team_changes = changes_by_team.get(team, [])
        if expected_change not in team_changes:
            org_mismatches.append(f"Expected org_changes row for team '{team}' with change_type '{expected_change}' but not found.")
    # Rule 2: For every row in org_changes.csv with change_type merged/dissolved, assert team is not active in teams.yaml
    for team, change_types in changes_by_team.items():
        if any(ct in ("merged", "dissolved") for ct in change_types):
            tinfo = teams.get(team)
            if tinfo is not None and tinfo.get("status") == "active":
                org_mismatches.append(f"Team '{team}' has org_changes change_type merged/dissolved but is marked active in teams.yaml.")

    expected = {
        "repos": sorted(repos_info, key=lambda r: r["name"]),
        "validation": {
            "unknown_owners": sorted(unknown_owners_set),
            "missing_root_owner": sorted(missing_root_owner_list),
            "org_mismatches": org_mismatches,
        }
    }
    return expected


def almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def read_report(path: Path) -> Tuple[bool, Optional[Dict[str, Any]]]:
    data = load_json(path)
    if not isinstance(data, dict):
        return False, None
    # minimal structural validation
    if "repos" not in data or "validation" not in data:
        return False, None
    if not isinstance(data["repos"], list):
        return False, None
    if not isinstance(data["validation"], dict):
        return False, None
    return True, data


def compare_patterns(expected_patterns: List[Dict[str, Any]], actual_patterns: List[Dict[str, Any]]) -> bool:
    # Compare by mapping key (pattern, owner)
    def keyify(item: Dict[str, Any]) -> Tuple[str, str]:
        return (item.get("pattern"), item.get("owner"))
    exp_map = {keyify(it): it for it in expected_patterns}
    act_map = {keyify(it): it for it in actual_patterns if isinstance(it, dict)}
    if set(exp_map.keys()) != set(act_map.keys()):
        return False
    for k, exp in exp_map.items():
        act = act_map[k]
        # Check fields
        if act.get("owner_status") != exp.get("owner_status"):
            return False
        # merged_into can be None or string
        if act.get("merged_into", None) != exp.get("merged_into", None):
            return False
        # canonical_name
        if act.get("canonical_name", None) != exp.get("canonical_name", None):
            return False
        # impacted boolean
        if bool(act.get("impacted")) != bool(exp.get("impacted")):
            return False
    return True


def compare_counts(exp_counts: Dict[str, Any], act_counts: Dict[str, Any]) -> bool:
    if not isinstance(act_counts, dict):
        return False
    if act_counts.get("total_patterns") != exp_counts.get("total_patterns"):
        return False
    if act_counts.get("impacted_patterns") != exp_counts.get("impacted_patterns"):
        return False
    act_pct = act_counts.get("percent_impacted")
    exp_pct = exp_counts.get("percent_impacted")
    # allow numeric equivalence ignoring type and small float discrepancies
    try:
        act_pct_f = float(act_pct)
        exp_pct_f = float(exp_pct)
    except Exception:
        return False
    if not almost_equal(act_pct_f, exp_pct_f, tol=1e-6):
        return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_json_exists": 0.0,
        "report_json_parseable": 0.0,
        "report_repos_covered": 0.0,
        "patterns_correct": 0.0,
        "dominant_owner_correct": 0.0,
        "maintainers_and_alignment_correct": 0.0,
        "counts_correct": 0.0,
        "validation_unknown_owners_correct": 0.0,
        "validation_missing_root_owner_correct": 0.0,
        "validation_org_mismatches_correct": 0.0,
        "summary_csv_exists": 0.0,
        "summary_schema_correct": 0.0,
        "summary_values_match_report": 0.0,
    }

    expected = compute_expected(workspace)
    report_path = workspace / "output" / "report.json"
    summary_path = workspace / "output" / "summary.csv"

    # report exists
    if report_path.exists():
        scores["report_json_exists"] = 1.0
    else:
        # If report doesn't exist, other report-dependent checks remain 0.0
        pass

    # parseable
    ok, report_data = read_report(report_path) if report_path.exists() else (False, None)
    if ok and report_data is not None:
        scores["report_json_parseable"] = 1.0

        # repos covered: set of repo names should match expected
        exp_repos = expected["repos"]
        act_repos = report_data.get("repos", [])
        exp_repo_names = {r["name"] for r in exp_repos}
        act_repo_names = {r.get("name") for r in act_repos if isinstance(r, dict) and "name" in r}
        if exp_repo_names == act_repo_names:
            scores["report_repos_covered"] = 1.0

        # Build maps by repo name for comparisons
        exp_repo_map = {r["name"]: r for r in exp_repos}
        act_repo_map = {r["name"]: r for r in act_repos if isinstance(r, dict) and "name" in r}

        # patterns_correct across all repos
        patterns_all_ok = True
        dom_all_ok = True
        maintain_all_ok = True
        counts_all_ok = True
        for name, exp_repo in exp_repo_map.items():
            act_repo = act_repo_map.get(name)
            if not isinstance(act_repo, dict):
                patterns_all_ok = False
                dom_all_ok = False
                maintain_all_ok = False
                counts_all_ok = False
                continue
            # patterns
            exp_patterns = exp_repo.get("patterns", [])
            act_patterns = act_repo.get("patterns", [])
            if not isinstance(act_patterns, list):
                patterns_all_ok = False
            else:
                if not compare_patterns(exp_patterns, act_patterns):
                    patterns_all_ok = False
            # dominant_owner
            if act_repo.get("dominant_owner", None) != exp_repo.get("dominant_owner", None):
                dom_all_ok = False
            # maintainers and alignment
            exp_maint = exp_repo.get("maintainer_names", [])
            act_maint = act_repo.get("maintainer_names", [])
            if not (isinstance(act_maint, list) and isinstance(exp_maint, list)):
                maintain_all_ok = False
            else:
                if sorted([str(x) for x in act_maint]) != sorted([str(x) for x in exp_maint]):
                    maintain_all_ok = False
            if act_repo.get("maintainer_alignment") != exp_repo.get("maintainer_alignment"):
                maintain_all_ok = False
            # counts
            exp_counts = exp_repo.get("counts", {})
            act_counts = act_repo.get("counts", {})
            if not compare_counts(exp_counts, act_counts):
                counts_all_ok = False

        if patterns_all_ok:
            scores["patterns_correct"] = 1.0
        if dom_all_ok:
            scores["dominant_owner_correct"] = 1.0
        if maintain_all_ok:
            scores["maintainers_and_alignment_correct"] = 1.0
        if counts_all_ok:
            scores["counts_correct"] = 1.0

        # validation checks
        act_validation = report_data.get("validation", {})
        if isinstance(act_validation, dict):
            # unknown owners
            exp_unknown = set(expected["validation"]["unknown_owners"])
            act_unknown = act_validation.get("unknown_owners", [])
            if isinstance(act_unknown, list) and set([str(x) for x in act_unknown]) == set([str(x) for x in exp_unknown]):
                scores["validation_unknown_owners_correct"] = 1.0
            # missing root owner
            exp_missing = set(expected["validation"]["missing_root_owner"])
            act_missing = act_validation.get("missing_root_owner", [])
            if isinstance(act_missing, list) and set([str(x) for x in act_missing]) == set([str(x) for x in exp_missing]):
                scores["validation_missing_root_owner_correct"] = 1.0
            # org mismatches (expected exact list; in our dataset this is empty)
            exp_mismatches = expected["validation"]["org_mismatches"]
            act_mismatches = act_validation.get("org_mismatches", [])
            if isinstance(act_mismatches, list) and len(act_mismatches) == len(exp_mismatches):
                # If non-empty, require set equality; else both empty
                if len(exp_mismatches) == 0 or set([str(x) for x in act_mismatches]) == set([str(x) for x in exp_mismatches]):
                    scores["validation_org_mismatches_correct"] = 1.0

    # summary csv
    if summary_path.exists():
        scores["summary_csv_exists"] = 1.0
        rows = load_csv_dicts(summary_path)
        if rows is not None:
            # schema check: exact header order
            try:
                with summary_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
                expected_header = ["repo", "total_patterns", "impacted_patterns", "percent_impacted", "maintainer_alignment"]
                if header == expected_header:
                    scores["summary_schema_correct"] = 1.0
            except Exception:
                pass

            # values match report
            ok_report, report_data_for_summary = read_report(workspace / "output" / "report.json") if (workspace / "output" / "report.json").exists() else (False, None)
            if ok_report and report_data_for_summary is not None:
                # Build mapping from report
                rep_map = {}
                for r in report_data_for_summary.get("repos", []):
                    if not isinstance(r, dict) or "name" not in r:
                        continue
                    rep_map[r["name"]] = r
                # Build mapping from csv
                csv_map = {}
                try:
                    for row in rows:
                        repo = row.get("repo")
                        if repo is not None:
                            csv_map[repo] = row
                    # Check same repos
                    if set(rep_map.keys()) == set(csv_map.keys()) and len(rep_map) > 0:
                        all_ok = True
                        for repo, rep in rep_map.items():
                            csv_row = csv_map.get(repo, {})
                            try:
                                tp_csv = int(csv_row.get("total_patterns", ""))
                                ip_csv = int(csv_row.get("impacted_patterns", ""))
                                pi_csv = float(csv_row.get("percent_impacted", ""))
                            except Exception:
                                all_ok = False
                                break
                            rep_counts = rep.get("counts", {})
                            if tp_csv != rep_counts.get("total_patterns"):
                                all_ok = False
                                break
                            if ip_csv != rep_counts.get("impacted_patterns"):
                                all_ok = False
                                break
                            pi_rep = float(rep_counts.get("percent_impacted", 0.0))
                            if not almost_equal(pi_csv, pi_rep, tol=1e-6):
                                all_ok = False
                                break
                            if (csv_row.get("maintainer_alignment") or "") != (rep.get("maintainer_alignment") or ""):
                                all_ok = False
                                break
                        if all_ok:
                            scores["summary_values_match_report"] = 1.0
                except Exception:
                    pass

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()