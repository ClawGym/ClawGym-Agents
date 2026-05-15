import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            required = {"field_id", "crop_last_year", "crop_family_last_year", "soil_pH", "nitrate_ppm"}
            if not set(reader.fieldnames or []).issuperset(required):
                return None
            return rows
    except Exception:
        return None


def _parse_rotation_md(text: str) -> Optional[Dict[str, Dict[str, str]]]:
    try:
        plan: Dict[str, Dict[str, str]] = {}
        for line in text.splitlines():
            m = re.match(r"^\s*-\s*(F\d+):\s*(.+?)\s*\(([^()]+)\)\s*$", line)
            if m:
                fid = m.group(1).strip()
                crop = m.group(2).strip()
                fam = m.group(3).strip()
                plan[fid] = {"planned_crop": crop, "planned_family": fam}
        if not plan:
            return None
        return plan
    except Exception:
        return None


def _compute_issues(soil_rows: List[Dict[str, str]], rotation: Dict[str, Dict[str, str]]) -> Tuple[Dict[str, Dict[str, str]], Set[str], Set[str], Set[str]]:
    fields: Dict[str, Dict[str, str]] = {}
    for r in soil_rows:
        fid = r.get("field_id", "").strip()
        if not fid:
            continue
        fields[fid] = {
            "field_id": fid,
            "soil_pH": r.get("soil_pH", "").strip(),
            "nitrate_ppm": r.get("nitrate_ppm", "").strip(),
            "crop_last_year": r.get("crop_last_year", "").strip(),
            "last_year_family": r.get("crop_family_last_year", "").strip(),
        }
    for fid, info in rotation.items():
        if fid not in fields:
            fields[fid] = {
                "field_id": fid,
                "soil_pH": "",
                "nitrate_ppm": "",
                "crop_last_year": "",
                "last_year_family": "",
            }
        fields[fid]["planned_family"] = info.get("planned_family", "")
        fields[fid]["planned_crop"] = info.get("planned_crop", "")

    low_pH: Set[str] = set()
    low_N: Set[str] = set()
    rotation_conflicts: Set[str] = set()
    for fid, info in fields.items():
        try:
            if info.get("soil_pH", "") != "":
                if float(info["soil_pH"]) < 6.2:
                    low_pH.add(fid)
        except ValueError:
            pass
        try:
            if info.get("nitrate_ppm", "") != "":
                if float(info["nitrate_ppm"]) < 10:
                    low_N.add(fid)
        except ValueError:
            pass
        lyf = info.get("last_year_family", "")
        pf = info.get("planned_family", "")
        if lyf and pf and lyf == pf:
            rotation_conflicts.add(fid)
    return fields, low_pH, low_N, rotation_conflicts


def _extract_inserted_segments(template_text: str, memo_text: str) -> Optional[Tuple[str, str, str]]:
    ph1 = "[TO_FILL: Soil Issues Summary]"
    ph2 = "[TO_FILL: Rotation Conflicts]"
    ph3 = "[TO_FILL: Recommended Amendments]"
    try:
        i1 = template_text.index(ph1)
        i2 = template_text.index(ph2)
        i3 = template_text.index(ph3)
    except ValueError:
        return None
    seg0 = template_text[:i1]
    seg1 = template_text[i1 + len(ph1):i2]
    seg2 = template_text[i2 + len(ph2):i3]
    seg3 = template_text[i3 + len(ph3):]

    if not memo_text.startswith(seg0):
        return None
    pos1 = len(seg0)
    idx1 = memo_text.find(seg1, pos1)
    if idx1 < 0:
        return None
    inserted1 = memo_text[pos1:idx1]
    pos2 = idx1 + len(seg1)
    idx2 = memo_text.find(seg2, pos2)
    if idx2 < 0:
        return None
    inserted2 = memo_text[pos2:idx2]
    pos3 = idx2 + len(seg2)
    if not memo_text.endswith(seg3):
        return None
    inserted3 = memo_text[pos3: len(memo_text) - len(seg3)]
    if any(ph in memo_text for ph in (ph1, ph2, ph3)):
        return None
    if len(inserted1.strip()) == 0 or len(inserted2.strip()) == 0 or len(inserted3.strip()) == 0:
        return None
    return inserted1, inserted2, inserted3


def _parse_counts_line(section_text: str) -> Optional[Tuple[int, int, int]]:
    for line in section_text.splitlines():
        m = re.match(r"^\s*Counts:\s*low_pH=(\d+),\s*low_N=(\d+),\s*rotation_conflicts=(\d+)\s*$", line)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def _find_bullet_matches_for_values(section_text: str, fields: Dict[str, Dict[str, str]], value_key: str, expected_set: Set[str]) -> Tuple[bool, Set[str]]:
    found: Set[str] = set()
    val_map: Dict[str, str] = {}
    for fid, info in fields.items():
        if info.get(value_key, "") != "":
            val_map[fid] = info[value_key]
    for line in section_text.splitlines():
        if re.match(r"^\s*-\s+", line):
            m = re.search(r"\b(F\d+)\b", line)
            if not m:
                continue
            fid = m.group(1)
            if fid in val_map:
                val_str = val_map[fid]
                if f"({val_str})" in line:
                    found.add(fid)
    return (found == expected_set), found


def _find_rotation_conflict_lines(section_text: str, fields: Dict[str, Dict[str, str]], conflicts: Set[str]) -> bool:
    if not conflicts:
        return True
    lines = section_text.splitlines()
    for fid in conflicts:
        info = fields.get(fid, {})
        lyf = info.get("last_year_family", "")
        pf = info.get("planned_family", "")
        last_crop = info.get("crop_last_year", "")
        planned_crop = info.get("planned_crop", "")
        found_line = False
        for line in lines:
            if fid not in line:
                continue
            if f"{lyf} -> {pf}" not in line:
                continue
            if last_crop and last_crop in line and planned_crop and planned_crop in line and ("(" in line and ")" in line):
                found_line = True
                break
        if not found_line:
            return False
    return True


def _recommended_mentions_all(section_text: str, fields_with_issues: Set[str]) -> bool:
    lines = section_text.splitlines()
    mentioned: Set[str] = set()
    for fid in fields_with_issues:
        for line in lines:
            if fid in line:
                mentioned.add(fid)
                break
    return mentioned == fields_with_issues


def _read_flagged_csv(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None


def _compare_flagged_csv(header: List[str], data: List[List[str]], expected_rows: List[List[str]]) -> Tuple[bool, bool]:
    required_header = ["field_id", "soil_pH", "nitrate_ppm", "last_year_family", "planned_family", "issues"]
    header_ok = header == required_header
    set_actual = set(tuple(r) for r in data)
    set_expected = set(tuple(r) for r in expected_rows)
    rows_ok = set_actual == set_expected
    return header_ok, rows_ok


def _build_expected_flagged_rows(fields: Dict[str, Dict[str, str]], low_pH: Set[str], low_N: Set[str], conflicts: Set[str]) -> List[List[str]]:
    expected: List[List[str]] = []
    fields_with_issues = sorted(low_pH | low_N | conflicts)
    for fid in fields_with_issues:
        info = fields.get(fid, {})
        issues_parts: List[str] = []
        if fid in low_pH:
            issues_parts.append("low_pH")
        if fid in low_N:
            issues_parts.append("low_N")
        if fid in conflicts:
            issues_parts.append("rotation_conflict")
        issues_str = ";".join(issues_parts)
        expected.append([
            fid,
            info.get("soil_pH", ""),
            info.get("nitrate_ppm", ""),
            info.get("last_year_family", ""),
            info.get("planned_family", ""),
            issues_str
        ])
    return expected


def _parse_email_bullet_list(line: str) -> List[str]:
    if ":" in line:
        items_str = line.split(":", 1)[1]
    else:
        items_str = line
    parts = [p.strip() for p in items_str.split(",")]
    return [p for p in parts if p]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "memo_placeholders_replaced_only": 0.0,
        "memo_counts_line": 0.0,
        "memo_low_pH_bullets": 0.0,
        "memo_low_N_bullets": 0.0,
        "memo_rotation_conflicts_lines": 0.0,
        "memo_recommended_amendments_mentions": 0.0,
        "flagged_csv_header": 0.0,
        "flagged_csv_rows_correct": 0.0,
        "email_headers": 0.0,
        "email_references": 0.0,
        "email_bullet_lists": 0.0,
        "email_ends_with_review": 0.0,
    }

    soil_path = workspace / "input" / "soil_tests.csv"
    rot_path = workspace / "input" / "rotation_plan_2025.md"
    tmpl_path = workspace / "input" / "memo_template.md"

    soil_rows = _read_csv_dicts(soil_path)
    rot_text = _read_text(rot_path)
    tmpl_text = _read_text(tmpl_path)
    rotation = _parse_rotation_md(rot_text) if rot_text is not None else None

    fields: Dict[str, Dict[str, str]] = {}
    low_pH: Set[str] = set()
    low_N: Set[str] = set()
    conflicts: Set[str] = set()
    if soil_rows is not None and rotation is not None:
        fields, low_pH, low_N, conflicts = _compute_issues(soil_rows, rotation)

    memo_path = workspace / "output" / "Rotation_Advisory_Memo_2025.md"
    memo_text = _read_text(memo_path)
    inserted_segments: Optional[Tuple[str, str, str]] = None
    if memo_text is not None and tmpl_text is not None:
        inserted_segments = _extract_inserted_segments(tmpl_text, memo_text)
        if inserted_segments:
            scores["memo_placeholders_replaced_only"] = 1.0

    if inserted_segments and fields:
        soil_section, conflict_section, rec_section = inserted_segments

        counts = _parse_counts_line(soil_section)
        if counts is not None:
            exp_counts = (len(low_pH), len(low_N), len(conflicts))
            if counts == exp_counts:
                scores["memo_counts_line"] = 1.0

        pH_ok, _ = _find_bullet_matches_for_values(soil_section, fields, "soil_pH", low_pH)
        if pH_ok:
            scores["memo_low_pH_bullets"] = 1.0

        n_ok, _ = _find_bullet_matches_for_values(soil_section, fields, "nitrate_ppm", low_N)
        if n_ok:
            scores["memo_low_N_bullets"] = 1.0

        if _find_rotation_conflict_lines(conflict_section, fields, conflicts):
            present: Set[str] = set()
            for fid in conflicts:
                for line in conflict_section.splitlines():
                    if fid in line:
                        present.add(fid)
                        break
            if present == conflicts:
                scores["memo_rotation_conflicts_lines"] = 1.0

        all_flagged = low_pH | low_N | conflicts
        if _recommended_mentions_all(rec_section, all_flagged):
            scores["memo_recommended_amendments_mentions"] = 1.0

    flagged_path = workspace / "output" / "flagged_fields.csv"
    flagged_data = _read_flagged_csv(flagged_path)
    if flagged_data is not None and fields:
        header, rows = flagged_data
        expected_rows = _build_expected_flagged_rows(fields, low_pH, low_N, conflicts)
        header_ok, rows_ok = _compare_flagged_csv(header, rows, expected_rows)
        if header_ok:
            scores["flagged_csv_header"] = 1.0
        if rows_ok:
            scores["flagged_csv_rows_correct"] = 1.0

    email_path = workspace / "output" / "email_to_farm_manager.txt"
    email_text = _read_text(email_path)
    if email_text is not None and fields:
        lines = email_text.splitlines()
        if len(lines) >= 2:
            if lines[0].strip() == "To: Rita Gomez <rita.gomez@example.com>" and lines[1].strip() == "Subject: 2025 Soil Amendments and Rotation Adjustments":
                scores["email_headers"] = 1.0
        if "output/Rotation_Advisory_Memo_2025.md" in email_text and "output/flagged_fields.csv" in email_text:
            scores["email_references"] = 1.0
        blime = None
        bn = None
        bconf = None
        for line in lines:
            s = line.strip()
            if s.startswith("- Fields needing lime (pH<6.2):"):
                blime = s
            elif s.startswith("- Fields with nitrate<10 ppm:"):
                bn = s
            elif s.startswith("- Rotation conflicts (same family as last year):"):
                bconf = s
        bullet_ok = True
        if blime is None or bn is None or bconf is None:
            bullet_ok = False
        else:
            lime_list = _parse_email_bullet_list(blime)
            n_list = _parse_email_bullet_list(bn)
            conf_list = _parse_email_bullet_list(bconf)
            if set(lime_list) != set(low_pH):
                bullet_ok = False
            if set(n_list) != set(low_N):
                bullet_ok = False
            if set(conf_list) != set(conflicts):
                bullet_ok = False
        if bullet_ok:
            scores["email_bullet_lists"] = 1.0
        non_empty = [ln.strip() for ln in lines if ln.strip() != ""]
        if non_empty:
            last_line = non_empty[-1]
            if "review" in last_line.lower():
                scores["email_ends_with_review"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()