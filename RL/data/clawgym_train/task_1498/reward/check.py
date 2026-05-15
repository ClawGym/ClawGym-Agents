import json
import csv
import sys
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set


def _load_yaml_config(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the specific config structure used in config/groups.yaml.
    Supports:
      - top-level key: value (int, bool, string)
      - roles: list of strings
      - target_counts_per_group: mapping of string->int
    Returns dict or None on failure.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    cfg: Dict[str, Any] = {}
    lines = text.splitlines()
    current_section: Optional[str] = None
    for raw in lines:
        # Keep indentation for detecting list/mapping items but strip trailing spaces
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("- "):
            key = stripped[:-1].strip()
            if key == "roles":
                cfg["roles"] = []
                current_section = "roles"
            elif key == "target_counts_per_group":
                cfg["target_counts_per_group"] = {}
                current_section = "target_counts_per_group"
            else:
                # Start of a section with no nested structure; reset section
                current_section = None
                # This file doesn't have other nested sections; ignore
        else:
            if current_section == "roles":
                # Expect list item "- value"
                s = stripped
                if s.startswith("- "):
                    value = s[2:].strip()
                    cfg["roles"].append(value)
                else:
                    # malformed roles list item
                    return None
            elif current_section == "target_counts_per_group":
                # Expect "key: value"
                m = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*([0-9]+)\s*$', stripped)
                if not m:
                    return None
                k, v = m.group(1), m.group(2)
                try:
                    cfg["target_counts_per_group"][k] = int(v)
                except Exception:
                    return None
            else:
                # top-level key: value
                m = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$', stripped)
                if not m:
                    return None
                key, value = m.group(1), m.group(2)
                # Coerce types
                lv = value.strip()
                if re.fullmatch(r'[0-9]+', lv):
                    cfg[key] = int(lv)
                elif lv.lower() in ("true", "false"):
                    cfg[key] = lv.lower() == "true"
                else:
                    cfg[key] = lv
    # Validate required keys present
    required = [
        "period_field",
        "group_size",
        "roles",
        "role_balance_per_group",
        "balance_field",
        "target_counts_per_group",
        "strict_conflict",
    ]
    for k in required:
        if k not in cfg:
            return None
    # Sanity: types
    if not isinstance(cfg["period_field"], str):
        return None
    if not isinstance(cfg["group_size"], int) or cfg["group_size"] <= 0:
        return None
    if not isinstance(cfg["roles"], list) or not all(isinstance(r, str) for r in cfg["roles"]) or len(cfg["roles"]) == 0:
        return None
    if not isinstance(cfg["role_balance_per_group"], str):
        return None
    if not isinstance(cfg["balance_field"], str):
        return None
    if not isinstance(cfg["target_counts_per_group"], dict) or not all(
        isinstance(k, str) and isinstance(v, int) for k, v in cfg["target_counts_per_group"].items()
    ):
        return None
    if not isinstance(cfg["strict_conflict"], bool):
        return None
    return cfg


def _load_students(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            expected = ["student_id", "name", "period", "reading_level"]
            if reader.fieldnames is None:
                return None
            # Allow additional columns but must include expected
            for col in expected:
                if col not in reader.fieldnames:
                    return None
            rows: List[Dict[str, str]] = []
            for row in reader:
                # Basic validation of non-empty fields
                if not row.get("student_id") or not row.get("name") or not row.get("period") or not row.get("reading_level"):
                    return None
                rows.append({
                    "student_id": row["student_id"],
                    "name": row["name"],
                    "period": row["period"],
                    "reading_level": row["reading_level"],
                })
            return rows
    except Exception:
        return None


def _load_preferences(path: Path) -> Optional[Dict[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return None
        prefs: Dict[str, str] = {}
        for entry in data:
            if not isinstance(entry, dict):
                return None
            sid = entry.get("student_id")
            role = entry.get("preferred_role")
            if not isinstance(sid, str) or not isinstance(role, str):
                return None
            prefs[sid] = role
        return prefs
    except Exception:
        return None


def _load_conflicts(path: Path) -> Optional[Set[Tuple[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            expected = ["student_id_a", "student_id_b"]
            if reader.fieldnames is None:
                return None
            for col in expected:
                if col not in reader.fieldnames:
                    return None
            pairs: Set[Tuple[str, str]] = set()
            for row in reader:
                a = row.get("student_id_a")
                b = row.get("student_id_b")
                if not a or not b:
                    return None
                # Store canonical ordered tuple
                if a <= b:
                    pairs.add((a, b))
                else:
                    pairs.add((b, a))
            return pairs
    except Exception:
        return None


def _load_assignments(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return None
        # basic element type check; full validation done later
        for rec in data:
            if not isinstance(rec, dict):
                return None
        return data
    except Exception:
        return None


def _load_summary(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows: List[Dict[str, str]] = []
            for row in reader:
                rows.append(row)
            return (reader.fieldnames, rows)
    except Exception:
        return None


def _index_students_by_id(students: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {s["student_id"]: s for s in students}


def _group_assignments(assignments: List[Dict[str, Any]], period_field: str) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    by_period: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for rec in assignments:
        per = rec.get(period_field)
        gid = rec.get("group_id")
        if per is None or gid is None:
            # Will be flagged elsewhere
            per = str(per)
            gid = str(gid)
        if per not in by_period:
            by_period[per] = {}
        if gid not in by_period[per]:
            by_period[per][gid] = []
        by_period[per][gid].append(rec)
    return by_period


def _safe_int(val: Any) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "assignments_file_exists": 0.0,
        "assignments_complete_coverage": 0.0,
        "assignments_schema_and_values_valid": 0.0,
        "group_sizes_valid": 0.0,
        "group_period_purity": 0.0,
        "reading_balance_valid": 0.0,
        "conflicts_respected": 0.0,
        "role_balance_valid": 0.0,
        ".preference_flags_correct": 0.0,
        "summary_header_valid": 0.0,
        "summary_counts_and_validity_match": 0.0,
    }

    # Load config and inputs
    cfg_path = workspace / "config" / "groups.yaml"
    students_path = workspace / "input" / "students.csv"
    prefs_path = workspace / "input" / "preferences.json"
    conflicts_path = workspace / "input" / "conflicts.csv"
    assignments_path = workspace / "output" / "assignments.json"
    summary_path = workspace / "output" / "summary.csv"

    cfg = _load_yaml_config(cfg_path)
    students = _load_students(students_path)
    prefs = _load_preferences(prefs_path)
    conflicts = _load_conflicts(conflicts_path)
    assignments = _load_assignments(assignments_path)
    summary = _load_summary(summary_path)

    # Baseline existence checks for assignments and summary parseability
    if assignments is not None:
        scores["assignments_file_exists"] = 1.0
    else:
        # If file missing or malformed, other checks depending on it will remain 0.0
        assignments = None

    # Assignments schema and coverage checks require cfg and students and prefs
    if assignments is not None and cfg is not None and students is not None and prefs is not None:
        # coverage: all students appear exactly once; no duplicates; no extras
        roster_ids = [s["student_id"] for s in students]
        roster_set = set(roster_ids)
        assigned_ids = [rec.get("student_id") for rec in assignments if isinstance(rec, dict)]
        if len(assigned_ids) == len(assignments) and all(isinstance(x, str) for x in assigned_ids):
            assigned_set = set(assigned_ids)
            duplicates = len(assigned_ids) != len(assigned_set)
            extras = assigned_set - roster_set
            missing = roster_set - assigned_set
            if not duplicates and not extras and not missing:
                scores["assignments_complete_coverage"] = 1.0

        # schema and values: required keys, type checks, roles and reading level valid, roster match for name/period/reading_level
        required_keys = ["student_id", "name", "period", "group_id", "assigned_role", "reading_level", "preference_matched"]
        roles = set(cfg["roles"])
        balance_levels = set(cfg["target_counts_per_group"].keys())
        students_by_id = _index_students_by_id(students)
        schema_ok = True
        values_ok = True
        for rec in assignments:
            # keys presence
            for k in required_keys:
                if k not in rec:
                    schema_ok = False
                    break
            if not schema_ok:
                break
            # types and non-empty
            if not isinstance(rec["student_id"], str) or not rec["student_id"]:
                values_ok = False
                break
            if not isinstance(rec["name"], str) or not rec["name"]:
                values_ok = False
                break
            if not isinstance(rec["period"], str) or not rec["period"]:
                values_ok = False
                break
            if not isinstance(rec["group_id"], (str, int)):
                values_ok = False
                break
            if not isinstance(rec["assigned_role"], str) or rec["assigned_role"] not in roles:
                values_ok = False
                break
            if not isinstance(rec["reading_level"], str) or rec["reading_level"] not in balance_levels:
                values_ok = False
                break
            if not isinstance(rec["preference_matched"], bool):
                values_ok = False
                break
            # roster consistency
            sid = rec["student_id"]
            roster = students_by_id.get(sid)
            if roster is None:
                values_ok = False
                break
            if rec["name"] != roster["name"] or rec["period"] != roster["period"] or rec["reading_level"] != roster["reading_level"]:
                values_ok = False
                break
        if schema_ok and values_ok:
            scores["assignments_schema_and_values_valid"] = 1.0

        # group sizes valid and period purity
        period_field = cfg["period_field"]
        grouped = _group_assignments(assignments, period_field)
        gsize = cfg["group_size"]
        group_size_ok = True
        period_purity_ok = True
        for per, groups in grouped.items():
            for gid, members in groups.items():
                if len(members) != gsize:
                    group_size_ok = False
                # period purity: all members share same period value
                periods_in_group = set(m.get(period_field) for m in members)
                if len(periods_in_group) != 1:
                    period_purity_ok = False
                # If mismatch period metadata with roster period, earlier check would catch; here ensure grouping correct
            # Also ensure total count by period equals roster count per period (partitioning)
            # Not strictly required beyond group size/purity; skip additional strictness
        if group_size_ok:
            scores["group_sizes_valid"] = 1.0
        if period_purity_ok:
            scores["group_period_purity"] = 1.0

        # reading balance per group exact
        balance_field = cfg["balance_field"]
        target_counts = cfg["target_counts_per_group"]
        reading_ok = True
        for per, groups in grouped.items():
            for gid, members in groups.items():
                counts: Dict[str, int] = {k: 0 for k in target_counts.keys()}
                # Also ensure no extra categories
                extra_found = False
                for m in members:
                    lvl = m.get(balance_field)
                    if lvl not in counts:
                        extra_found = True
                        break
                    counts[lvl] += 1
                if extra_found:
                    reading_ok = False
                    break
                # Compare to target
                for k, v in target_counts.items():
                    if counts.get(k, 0) != v:
                        reading_ok = False
                        break
                if not reading_ok:
                    break
            if not reading_ok:
                break
        if reading_ok:
            scores["reading_balance_valid"] = 1.0

        # conflicts respected
        conflicts_ok = True
        if cfg["strict_conflict"]:
            if conflicts is None:
                conflicts_ok = False
            else:
                # Build mapping student_id -> (period, group_id)
                loc: Dict[str, Tuple[str, str]] = {}
                for per, groups in grouped.items():
                    for gid, members in groups.items():
                        for m in members:
                            sid = m["student_id"]
                            # Grouped by m[period_field], so period consistency should match per
                            loc[sid] = (per, str(gid))
                for (a, b) in conflicts:
                    if a in loc and b in loc:
                        if loc[a] == loc[b]:
                            conflicts_ok = False
                            break
        if conflicts_ok:
            scores["conflicts_respected"] = 1.0

        # role balance equal
        role_balance_ok = True
        if cfg["role_balance_per_group"].lower() == "equal":
            num_roles = len(cfg["roles"])
            # group_size must be divisible by number of roles
            if gsize % num_roles != 0:
                role_balance_ok = False
            else:
                expected_per_role = gsize // num_roles
                for per, groups in grouped.items():
                    for gid, members in groups.items():
                        role_counts: Dict[str, int] = {r: 0 for r in cfg["roles"]}
                        # Also detect roles not in list (already checked earlier)
                        for m in members:
                            r = m["assigned_role"]
                            role_counts[r] = role_counts.get(r, 0) + 1
                        for r in cfg["roles"]:
                            if role_counts.get(r, 0) != expected_per_role:
                                role_balance_ok = False
                                break
                        if not role_balance_ok:
                            break
                    if not role_balance_ok:
                        break
        if role_balance_ok:
            scores["role_balance_valid"] = 1.0

        # preference flags consistent
        pref_flags_ok = True
        for rec in assignments:
            sid = rec["student_id"]
            preferred = prefs.get(sid)
            expected_match = (preferred == rec["assigned_role"])
            if rec["preference_matched"] is not expected_match:
                pref_flags_ok = False
                break
        if pref_flags_ok:
            scores[".preference_flags_correct"] = 1.0

    # Summary checks
    header_expected = [
        "period",
        "group_id",
        "count_Isolationist",
        "count_Interventionist",
        "count_low",
        "count_mid",
        "count_high",
        "preferences_matched",
        "valid_group",
    ]
    if summary is not None:
        header, rows = summary
        if header == header_expected:
            scores["summary_header_valid"] = 1.0

    if summary is not None and assignments is not None and cfg is not None:
        # Compare counts and valid_group
        header, rows = summary
        period_field = cfg["period_field"]
        grouped = _group_assignments(assignments, period_field)
        # Build a set of (period, group_id) present in assignments
        assign_groups: Set[Tuple[str, str]] = set()
        for per, groups in grouped.items():
            for gid in groups:
                assign_groups.add((per, str(gid)))

        summary_groups: Set[Tuple[str, str]] = set()
        counts_ok = True
        valid_group_ok = True
        roles = cfg["roles"]
        # For computing validity: use prior checks per group independent of summary
        gsize = cfg["group_size"]
        num_roles = len(roles)
        target_counts = cfg["target_counts_per_group"]
        # Build conflict mapping again
        conflicts_pairs: Set[Tuple[str, str]] = conflicts if conflicts is not None else set()

        # Create mapping period->group_id->computed stats from assignments
        computed_counts: Dict[Tuple[str, str], Dict[str, int]] = {}
        computed_pref_matches: Dict[Tuple[str, str], int] = {}
        computed_valid: Dict[Tuple[str, str], bool] = {}
        for per, groups in grouped.items():
            for gid, members in groups.items():
                key = (per, str(gid))
                # role counts
                r_counts = {r: 0 for r in roles}
                for m in members:
                    r_counts[m["assigned_role"]] = r_counts.get(m["assigned_role"], 0) + 1
                # reading counts
                rl_counts = {k: 0 for k in target_counts.keys()}
                for m in members:
                    lvl = m[cfg["balance_field"]]
                    rl_counts[lvl] = rl_counts.get(lvl, 0) + 1
                # pref matches
                pm = sum(1 for m in members if m.get("preference_matched") is True)
                computed_counts[key] = {
                    **{f"count_{r}": r_counts.get(r, 0) for r in roles},
                    **{f"count_{lvl}": rl_counts.get(lvl, 0) for lvl in target_counts.keys()},
                }
                computed_pref_matches[key] = pm
                # validity: role balance, exact reading counts, conflicts
                role_ok = True
                if cfg["role_balance_per_group"].lower() == "equal":
                    if gsize % num_roles != 0:
                        role_ok = False
                    else:
                        exp_per_role = gsize // num_roles
                        for r in roles:
                            if r_counts.get(r, 0) != exp_per_role:
                                role_ok = False
                                break
                reading_ok = True
                for lvl, exp in target_counts.items():
                    if rl_counts.get(lvl, 0) != exp:
                        reading_ok = False
                        break
                conflict_ok = True
                if cfg["strict_conflict"]:
                    # Build set of student ids in group
                    sids = [m["student_id"] for m in members]
                    sset = set(sids)
                    # check each conflict pair if both in sset
                    for (a, b) in conflicts_pairs:
                        if a in sset and b in sset:
                            conflict_ok = False
                            break
                computed_valid[key] = (role_ok and reading_ok and conflict_ok)

        # Now validate summary rows
        for row in rows:
            per = row.get("period")
            gid = row.get("group_id")
            if per is None or gid is None:
                counts_ok = False
                valid_group_ok = False
                break
            key = (per, str(gid))
            summary_groups.add(key)
            # Counts for roles
            for r in roles:
                field = f"count_{r}"
                val = _safe_int(row.get(field))
                if val is None:
                    counts_ok = False
                    break
                expected = computed_counts.get(key, {}).get(field)
                if expected is None or val != expected:
                    counts_ok = False
                    break
            if not counts_ok:
                break
            # Counts for reading levels (keys from target_counts)
            for lvl in target_counts.keys():
                field = f"count_{lvl}"
                val = _safe_int(row.get(field))
                if val is None:
                    counts_ok = False
                    break
                expected = computed_counts.get(key, {}).get(field)
                if expected is None or val != expected:
                    counts_ok = False
                    break
            if not counts_ok:
                break
            # preferences_matched as integer count
            pm_val = _safe_int(row.get("preferences_matched"))
            if pm_val is None or pm_val != computed_pref_matches.get(key, -1):
                counts_ok = False
                break
            # valid_group: must be "TRUE" only if computed_valid True, else should be "FALSE"
            valid_str = row.get("valid_group")
            comp = computed_valid.get(key, False)
            if comp:
                if valid_str != "TRUE":
                    valid_group_ok = False
                    break
            else:
                if valid_str == "TRUE":
                    valid_group_ok = False
                    break

        # Ensure group sets match exactly
        if summary_groups != assign_groups:
            counts_ok = False
            valid_group_ok = False

        if counts_ok and valid_group_ok:
            scores["summary_counts_and_validity_match"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()