import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            header = reader.fieldnames or []
            return rows, header
    except Exception:
        return None, None


def _parse_yaml_baseline(yaml_text: str) -> Optional[str]:
    # Very minimal YAML parser for simple key: value pairs
    if yaml_text is None:
        return None
    baseline = None
    for line in yaml_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip('\'"')
            if key == "baseline":
                baseline = val
    return baseline


def _is_high_or_critical(sev: str) -> bool:
    if not isinstance(sev, str):
        return False
    return sev.strip().lower() in {"high", "critical"}


def _split_refs(refs: str) -> List[str]:
    if refs is None:
        return []
    parts = [p.strip() for p in refs.split(";")]
    return [p for p in parts if p]


def _round_nearest_int(x: float) -> int:
    # Use standard round to nearest integer; Python's round is acceptable here as no .5 edge cases in inputs
    return int(round(x))


def _word_count(text: str) -> int:
    if text is None:
        return 0
    # Count words by whitespace splitting
    words = re.findall(r"\b\S+\b", text)
    return len(words)


def _line_starts_with_md_marker(line: str) -> bool:
    s = line.lstrip()
    return s.startswith("#") or s.startswith("- ") or s.startswith("* ") or s.startswith("```")


def _parse_bool_text(s: str) -> Optional[bool]:
    if s is None:
        return None
    sl = s.strip().lower()
    if sl in {"true", "t", "yes", "y", "1"}:
        return True
    if sl in {"false", "f", "no", "n", "0"}:
        return False
    return None


def _last_nonempty_lines(text: str, n: int) -> List[str]:
    if text is None:
        return []
    lines = [ln.rstrip("\r\n") for ln in text.splitlines()]
    # Remove trailing empty lines
    idx = len(lines) - 1
    while idx >= 0 and lines[idx].strip() == "":
        idx -= 1
    trimmed = lines[:idx+1]
    res = []
    i = len(trimmed) - 1
    while i >= 0 and len(res) < n:
        if trimmed[i].strip() != "":
            res.append(trimmed[i].strip())
        i -= 1
    res.reverse()
    return res


def _compute_expected(workspace: Path) -> Optional[dict]:
    # Load inputs
    controls_path = workspace / "input" / "controls.json"
    policy_map_path = workspace / "input" / "policy_mapping.csv"
    vuln_path = workspace / "input" / "vuln_findings.csv"
    settings_path = workspace / "input" / "settings.yaml"
    draft_email_path = workspace / "input" / "draft_email.md"

    controls = _load_json(controls_path)
    policy_rows, policy_header = _load_csv_dicts(policy_map_path)
    vuln_rows, vuln_header = _load_csv_dicts(vuln_path)
    settings_text = _read_text(settings_path)
    draft_email_text = _read_text(draft_email_path)

    if controls is None or policy_rows is None or vuln_rows is None or settings_text is None or draft_email_text is None:
        return None

    baseline = _parse_yaml_baseline(settings_text)
    if not baseline:
        return None

    # Build helpful structures
    # Map control_id to (family, mandatory[baseline])
    control_info = {}
    families_set = set()
    for ctrl in controls:
        try:
            cid = ctrl["id"]
            fam = ctrl["family"]
            mand = ctrl.get("mandatory", {})
            is_mand = bool(mand.get(baseline, False))
        except Exception:
            return None
        control_info[cid] = {"family": fam, "mandatory": is_mand}
        families_set.add(fam)

    # Map control_id -> status, notes
    status_map = {}
    notes_map = {}
    for row in policy_rows:
        cid = (row.get("control_id") or "").strip()
        if not cid:
            continue
        status_map[cid] = (row.get("status") or "").strip()
        notes_map[cid] = (row.get("notes") or "").strip()

    # Family counts
    families = sorted(families_set)
    fam_total = {fam: 0 for fam in families}
    fam_impl = {fam: 0 for fam in families}

    for cid, info in control_info.items():
        fam = info["family"]
        if info["mandatory"]:
            fam_total[fam] += 1
            status = status_map.get(cid, "")
            if status == "Implemented":
                fam_impl[fam] += 1

    # Vulnerability counts per family (High/Critical)
    fam_highcrit = {fam: 0 for fam in families}
    # Also map control_id -> referenced by high/critical
    ctrl_ref_by_highcrit = {cid: False for cid in control_info.keys()}
    for row in vuln_rows:
        sev = row.get("severity", "")
        fam = row.get("family", "")
        if _is_high_or_critical(sev):
            if fam in fam_highcrit:
                fam_highcrit[fam] += 1
            refs = _split_refs(row.get("control_references", "") or "")
            for r in refs:
                if r in ctrl_ref_by_highcrit:
                    ctrl_ref_by_highcrit[r] = True

    # coverage_by_family expected
    cov_rows = []
    for fam in families:
        total = fam_total.get(fam, 0)
        impl = fam_impl.get(fam, 0)
        pct = _round_nearest_int((impl / total) * 100) if total > 0 else 0
        highcrit = fam_highcrit.get(fam, 0)
        cov_rows.append({
            "family": fam,
            "total_mandatory": total,
            "implemented": impl,
            "coverage_percent": pct,
            "high_crit_vulns": highcrit,
        })

    # control_gaps expected
    gap_rows = []
    for cid, info in control_info.items():
        if not info["mandatory"]:
            continue
        status = status_map.get(cid, "")
        if status != "Implemented":
            gap_rows.append({
                "control_id": cid,
                "family": info["family"],
                "status": status,
                "mandatory": True,
                "has_high_crit_vuln_ref": bool(ctrl_ref_by_highcrit.get(cid, False)),
                "notes": notes_map.get(cid, ""),
            })
    gap_rows.sort(key=lambda r: r["control_id"])

    # priority_gaps expected
    # Include only gaps where referenced_by_high_crit is true
    # reasons: status reason; vulnerability_reference; family_risk if fam_highcrit >=2 and cov <80
    fam_cov_map = {r["family"]: r["coverage_percent"] for r in cov_rows}
    priority_rows = []
    for gr in gap_rows:
        if not gr["has_high_crit_vuln_ref"]:
            continue
        fam = gr["family"]
        fam_cov = fam_cov_map.get(fam, 0)
        reasons = []
        if gr["status"] == "Partially Implemented":
            reasons.append("partially_implemented")
        else:
            reasons.append("not_implemented")
        reasons.append("vulnerability_reference")
        if fam_highcrit.get(fam, 0) >= 2 and fam_cov < 80:
            reasons.append("family_risk")
        priority_rows.append({
            "control_id": gr["control_id"],
            "family": fam,
            "status": gr["status"],
            "referenced_by_high_crit": True,
            "family_coverage_percent": fam_cov,
            "reasons": reasons,
        })
    priority_rows.sort(key=lambda r: r["control_id"])

    # overall coverage across all mandatory controls
    total_mandatory = sum(fam_total.values())
    total_implemented = sum(fam_impl.values())
    overall_cov = _round_nearest_int((total_implemented / total_mandatory) * 100) if total_mandatory > 0 else 0

    # lowest coverage families (ascending by coverage, then family)
    fam_sorted_by_cov = sorted(cov_rows, key=lambda r: (r["coverage_percent"], r["family"]))
    lowest_three = [r["family"] for r in fam_sorted_by_cov[:3]]

    return {
        "baseline": baseline,
        "coverage_by_family": cov_rows,
        "control_gaps": gap_rows,
        "priority_gaps": priority_rows,
        "overall_coverage": overall_cov,
        "lowest_three_families": lowest_three,
        "draft_email_text": draft_email_text,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "coverage_by_family_file": 0.0,
        "coverage_by_family_rows": 0.0,
        "control_gaps_file": 0.0,
        "control_gaps_rows": 0.0,
        "priority_gaps_file": 0.0,
        "priority_gaps_items": 0.0,
        "policy_email_file": 0.0,
        "policy_email_format": 0.0,
        "policy_email_metrics": 0.0,
    }

    expected = _compute_expected(workspace)
    outputs_dir = workspace / "outputs"

    # Prepare expected structures if available
    if expected is None:
        # We will still check file existence and basic header where possible
        pass

    # 1) coverage_by_family.csv checks
    cov_path = outputs_dir / "coverage_by_family.csv"
    cov_rows, cov_header = _load_csv_dicts(cov_path)
    expected_cov_header = ["family", "total_mandatory", "implemented", "coverage_percent", "high_crit_vulns"]
    if cov_rows is not None and cov_header == expected_cov_header:
        # basic file structure ok
        # Also verify sorted by family alphabetically
        families_in_file = [row.get("family", "") for row in cov_rows]
        if families_in_file == sorted(families_in_file):
            scores["coverage_by_family_file"] = 1.0

    if expected is not None and cov_rows is not None and cov_header == expected_cov_header:
        # Compare content
        # Build expected mapping list in order by family
        exp_cov = expected["coverage_by_family"]
        # ensure length matches
        equal = True
        if len(cov_rows) != len(exp_cov):
            equal = False
        else:
            # Compare each row by index, coercing numeric fields to int
            for i, exp in enumerate(exp_cov):
                got = cov_rows[i]
                try:
                    fam_ok = (got.get("family", "") == exp["family"])
                    tm = int(got.get("total_mandatory", ""))
                    imp = int(got.get("implemented", ""))
                    pct = int(got.get("coverage_percent", ""))
                    hcv = int(got.get("high_crit_vulns", ""))
                    vals_ok = (tm == exp["total_mandatory"] and
                               imp == exp["implemented"] and
                               pct == exp["coverage_percent"] and
                               hcv == exp["high_crit_vulns"])
                    if not (fam_ok and vals_ok):
                        equal = False
                        break
                except Exception:
                    equal = False
                    break
        if equal:
            scores["coverage_by_family_rows"] = 1.0

    # 2) control_gaps.csv checks
    gaps_path = outputs_dir / "control_gaps.csv"
    gaps_rows, gaps_header = _load_csv_dicts(gaps_path)
    expected_gaps_header = ["control_id", "family", "status", "mandatory", "has_high_crit_vuln_ref", "notes"]
    if gaps_rows is not None and gaps_header == expected_gaps_header:
        # verify sorted by control_id alphabetically
        ids_in_file = [row.get("control_id", "") for row in gaps_rows]
        if ids_in_file == sorted(ids_in_file):
            scores["control_gaps_file"] = 1.0

    if expected is not None and gaps_rows is not None and gaps_header == expected_gaps_header:
        exp_gaps = expected["control_gaps"]
        ok = True
        if len(gaps_rows) != len(exp_gaps):
            ok = False
        else:
            for i, exp in enumerate(exp_gaps):
                got = gaps_rows[i]
                cid_ok = got.get("control_id", "") == exp["control_id"]
                fam_ok = got.get("family", "") == exp["family"]
                status_ok = got.get("status", "") == exp["status"]
                # mandatory must be true for all rows (since only mandatory included)
                mand_val = _parse_bool_text(got.get("mandatory", ""))
                mand_ok = (mand_val is True)
                ref_val = _parse_bool_text(got.get("has_high_crit_vuln_ref", ""))
                ref_ok = (ref_val is True) if exp["has_high_crit_vuln_ref"] else (ref_val is False)
                notes_ok = got.get("notes", "") == exp["notes"]
                if not (cid_ok and fam_ok and status_ok and mand_ok and ref_ok and notes_ok):
                    ok = False
                    break
        if ok:
            scores["control_gaps_rows"] = 1.0

    # 3) priority_gaps.json checks
    prio_path = outputs_dir / "priority_gaps.json"
    prio_data = _load_json(prio_path)
    if isinstance(prio_data, list):
        # check sorted by control_id
        try:
            ids = [item.get("control_id", "") for item in prio_data]
            if ids == sorted(ids):
                # Ensure required keys exist in each item
                required_keys = {"control_id", "family", "status", "referenced_by_high_crit", "family_coverage_percent", "reasons"}
                all_have_keys = all(isinstance(item, dict) and required_keys.issubset(set(item.keys())) for item in prio_data)
                if all_have_keys:
                    scores["priority_gaps_file"] = 1.0
        except Exception:
            pass

    if expected is not None and isinstance(prio_data, list):
        exp_prio = expected["priority_gaps"]
        ok = True
        # Count and mapping by control_id
        if len(prio_data) != len(exp_prio):
            ok = False
        else:
            prio_by_id = {item.get("control_id", ""): item for item in prio_data if isinstance(item, dict)}
            for exp in exp_prio:
                got = prio_by_id.get(exp["control_id"])
                if not got:
                    ok = False
                    break
                fam_ok = got.get("family") == exp["family"]
                status_ok = got.get("status") == exp["status"]
                ref_ok = got.get("referenced_by_high_crit") is True
                try:
                    fam_cov_ok = int(got.get("family_coverage_percent")) == exp["family_coverage_percent"]
                except Exception:
                    fam_cov_ok = False
                reasons = got.get("reasons")
                if not isinstance(reasons, list):
                    ok = False
                    break
                # compare as sets; no extras allowed
                if set(reasons) != set(exp["reasons"]):
                    ok = False
                    break
                if not (fam_ok and status_ok and ref_ok and fam_cov_ok):
                    ok = False
                    break
        if ok:
            scores["priority_gaps_items"] = 1.0

    # 4) policy_email.txt checks
    email_path = outputs_dir / "policy_email.txt"
    email_text = _read_text(email_path)
    if email_text is not None:
        scores["policy_email_file"] = 1.0
        # format check: <= 180 words, no markdown markers at line starts, no triple backticks
        wc = _word_count(email_text)
        has_md_marker = any(_line_starts_with_md_marker(ln) for ln in email_text.splitlines())
        has_triple_backticks = "```" in email_text
        if wc <= 180 and not has_md_marker and not has_triple_backticks:
            scores["policy_email_format"] = 1.0

    if expected is not None and email_text is not None:
        # Validate last five labeled lines
        last5 = _last_nonempty_lines(email_text, 5)
        ok = True
        if len(last5) != 5:
            ok = False
        else:
            # Expected values
            baseline = expected["baseline"]
            overall = expected["overall_coverage"]
            lowest_three = expected["lowest_three_families"]
            prio_count = len(expected["priority_gaps"])

            # Build regex/patterns and check exact text after normalization of spaces
            line0 = last5[0]
            line1 = last5[1]
            line2 = last5[2]
            line3 = last5[3]
            line4 = last5[4]

            ok &= (line0 == f"Baseline: {baseline}")
            ok &= (line1 == f"Overall coverage: {overall}%")
            ok &= (line2 == f"Lowest coverage families (ascending): {lowest_three[0]}, {lowest_three[1]}, {lowest_three[2]}")
            ok &= (line3 == f"Priority gaps: {prio_count}")
            ok &= (line4 == "Attachments: coverage_by_family.csv, control_gaps.csv")
        if ok:
            scores["policy_email_metrics"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()