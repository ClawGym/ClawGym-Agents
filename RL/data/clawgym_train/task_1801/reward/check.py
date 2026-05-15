import json
import sys
import subprocess
import csv
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = list(reader)
            # Normalize None values to empty strings
            norm_rows = []
            for r in rows:
                norm_rows.append({k: (v if v is not None else "") for k, v in r.items()})
            return list(reader.fieldnames), norm_rows
    except Exception:
        return None, None


def _normalize_log(s: str) -> str:
    # Normalize newlines, strip trailing spaces, collapse trailing blank lines
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in s.split("\n")]
    # Remove trailing empty lines
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _run_validator(workspace: Path, target_csv: Path) -> Tuple[bool, Optional[str], Optional[int]]:
    script = workspace / "tools" / "validate_resources.py"
    if not script.exists():
        return False, None, None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(target_csv)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        return True, proc.stdout, proc.returncode
    except Exception:
        return False, None, None


def _find_section_lines(md: str, heading: str) -> Tuple[List[str], int, int]:
    """
    Find lines under a section given by heading text (ignoring leading #'s and spaces).
    Returns (lines_in_section, start_index, end_index_exclusive). If not found, returns ([], -1, -1).
    """
    lines = md.splitlines()
    def _is_heading(line: str, expected: str) -> bool:
        stripped = line.lstrip()
        i = 0
        while i < len(stripped) and stripped[i] == '#':
            i += 1
        stripped2 = stripped[i:].lstrip()
        return stripped2 == expected

    idxs = [i for i, ln in enumerate(lines) if _is_heading(ln, heading)]
    if not idxs:
        return [], -1, -1
    start = idxs[0] + 1
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].lstrip().startswith("#"):
            end = j
            break
    section_lines = lines[start:end]
    return section_lines, start, end


def _extract_bullets(section_lines: List[str]) -> List[str]:
    bullets = []
    for ln in section_lines:
        stripped = ln.strip()
        if stripped.startswith("- "):
            bullets.append(stripped)
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validator_before_captured_correctly": 0.0,
        "resources_clean_csv_structure": 0.0,
        "resources_clean_csv_categories_canonical": 0.0,
        "resources_clean_csv_specific_fixes": 0.0,
        "validator_after_zero_errors_and_matches": 0.0,
        "resources_summary_json_correct": 0.0,
        "guide_sections_and_resource_bullets": 0.0,
        "guide_resources_content_covers_all": 0.0,
        "guide_routines_bullet_count_5_to_8": 0.0,
        "guide_no_external_links": 0.0,
        "email_length_under_170_words": 0.0,
        "email_references_resource_or_guide": 0.0,
        "email_positive_tone_no_guilt": 0.0,
        "email_has_open_invitation": 0.0,
    }

    # Paths
    input_resources = workspace / "input" / "resources.csv"
    input_notes = workspace / "input" / "college_notes.md"
    input_draft = workspace / "input" / "draft_message.txt"
    tools_validator = workspace / "tools" / "validate_resources.py"

    out_dir = workspace / "output"
    validator_before = out_dir / "validator_before.txt"
    cleaned_csv = out_dir / "resources_clean.csv"
    validator_after = out_dir / "validator_after.txt"
    summary_json = out_dir / "resources_summary.json"
    guide_md = out_dir / "guide.md"
    email_txt = out_dir / "email_to_child.txt"

    # 1) Validate before: run validator on input/resources.csv and compare with output/validator_before.txt
    before_expected_ok = False
    if input_resources.exists() and tools_validator.exists() and validator_before.exists():
        ran, stdout, rc = _run_validator(workspace, input_resources)
        if ran and stdout is not None:
            expected_norm = _normalize_log(stdout)
            if rc is None:
                rc = 1
            text = _read_text(validator_before)
            if text is not None:
                actual_norm = _normalize_log(text)
                if expected_norm == actual_norm and rc != 0:
                    before_expected_ok = True
    scores["validator_before_captured_correctly"] = 1.0 if before_expected_ok else 0.0

    # 2) Check cleaned csv structure and content
    header, rows = _load_csv(cleaned_csv) if cleaned_csv.exists() else (None, None)
    required_cols = ["resource_name", "category", "description", "hours", "contact"]
    structure_ok = False
    categories_canonical_ok = False
    specific_fixes_ok = False
    if header is not None and rows is not None:
        # structure
        if header == required_cols and len(rows) == 4:
            structure_ok = True
        # canonical categories
        allowed_canonical = {"Academics", "Wellness", "Finance", "Community"}
        if all((r.get("category", "") in allowed_canonical) for r in rows):
            categories_canonical_ok = True
        # specific fixes expected
        expected_by_name = {
            "Writing Center": {"category": "Academics"},
            "Counseling Services": {"category": "Wellness"},
            "Food Pantry": {"category": "Wellness", "hours": "TBD"},
            "Peer Tutoring": {"category": "Academics"},
        }
        names = [r.get("resource_name", "") for r in rows]
        has_all_names = set(names) == set(expected_by_name.keys())
        all_required_nonempty_or_tbd = True
        for r in rows:
            for col in required_cols:
                val = (r.get(col) or "").strip()
                if val == "":
                    all_required_nonempty_or_tbd = False
                    break
            if not all_required_nonempty_or_tbd:
                break
        exp_match = True
        if has_all_names:
            index = {r.get("resource_name", ""): r for r in rows}
            for nm, exp in expected_by_name.items():
                r = index.get(nm, {})
                for key, exp_val in exp.items():
                    if (r.get(key) or "") != exp_val:
                        exp_match = False
                        break
                if not exp_match:
                    break
        else:
            exp_match = False

        if structure_ok and categories_canonical_ok and has_all_names and all_required_nonempty_or_tbd and exp_match:
            specific_fixes_ok = True

    scores["resources_clean_csv_structure"] = 1.0 if structure_ok else 0.0
    scores["resources_clean_csv_categories_canonical"] = 1.0 if categories_canonical_ok else 0.0
    scores["resources_clean_csv_specific_fixes"] = 1.0 if specific_fixes_ok else 0.0

    # 3) Validate after
    after_ok = False
    if cleaned_csv.exists() and tools_validator.exists() and validator_after.exists():
        ran2, stdout2, rc2 = _run_validator(workspace, cleaned_csv)
        if ran2 and stdout2 is not None:
            expected_norm2 = _normalize_log(stdout2)
            text2 = _read_text(validator_after)
            if text2 is not None:
                actual_norm2 = _normalize_log(text2)
                zero_errors = ("Finished with 0 error(s)") in expected_norm2 and rc2 == 0
                if expected_norm2 == actual_norm2 and zero_errors:
                    after_ok = True
    scores["validator_after_zero_errors_and_matches"] = 1.0 if after_ok else 0.0

    # 4) Summary JSON correctness
    summary_ok = False
    if summary_json.exists() and header is not None and rows is not None and categories_canonical_ok:
        try:
            txt = _read_text(summary_json)
            if txt is not None:
                content = json.loads(txt)
            else:
                content = None
            if isinstance(content, dict):
                expected_map: Dict[str, List[str]] = {}
                for r in rows:
                    cat = r.get("category", "")
                    nm = r.get("resource_name", "")
                    if cat and nm:
                        expected_map.setdefault(cat, []).append(nm)
                keys_match = set(content.keys()) == set(expected_map.keys())
                values_match = True
                for k, v in expected_map.items():
                    if k not in content or not isinstance(content[k], list):
                        values_match = False
                        break
                    if set(content[k]) != set(v):
                        values_match = False
                        break
                summary_ok = keys_match and values_match
        except Exception:
            summary_ok = False
    scores["resources_summary_json_correct"] = 1.0 if summary_ok else 0.0

    # 5) Guide checks
    guide_sections_ok = False
    guide_resources_cover_ok = False
    guide_routines_count_ok = False
    guide_no_links_ok = False

    guide_text = _read_text(guide_md) if guide_md.exists() else None
    if guide_text is not None and rows is not None:
        res_heading = "Campus Resources to Bookmark:"
        routines_heading = "First-Semester Routines:"
        res_section, _, _ = _find_section_lines(guide_text, res_heading)
        routines_section, _, _ = _find_section_lines(guide_text, routines_heading)
        if res_section and routines_section:
            guide_sections_ok = True
        res_bullets = _extract_bullets(res_section)
        if len(res_bullets) == len(rows):
            all_ok = True
            for r in rows:
                nm = r.get("resource_name", "")
                contact = r.get("contact", "")
                found = False
                for b in res_bullets:
                    if nm in b and contact in b and "\n" not in b:
                        found = True
                        break
                if not found:
                    all_ok = False
                    break
            guide_resources_cover_ok = all_ok
        routines_bullets = _extract_bullets(routines_section)
        if 5 <= len(routines_bullets) <= 8:
            if all("\n" not in b for b in routines_bullets):
                guide_routines_count_ok = True
        if "http://" not in guide_text and "https://" not in guide_text:
            guide_no_links_ok = True

    scores["guide_sections_and_resource_bullets"] = 1.0 if guide_sections_ok else 0.0
    scores["guide_resources_content_covers_all"] = 1.0 if guide_resources_cover_ok else 0.0
    scores["guide_routines_bullet_count_5_to_8"] = 1.0 if guide_routines_count_ok else 0.0
    scores["guide_no_external_links"] = 1.0 if guide_no_links_ok else 0.0

    # 6) Email checks
    email_text = _read_text(email_txt) if email_txt.exists() else None
    if email_text is not None:
        words = re.findall(r"\b\w+\b", email_text)
        scores["email_length_under_170_words"] = 1.0 if len(words) <= 170 else 0.0
        referenced = False
        lower_email = email_text.lower()
        if rows is not None:
            for r in rows:
                nm = r.get("resource_name", "")
                if nm and nm.lower() in lower_email:
                    referenced = True
                    break
        if not referenced and "guide" in lower_email:
            referenced = True
        scores["email_references_resource_or_guide"] = 1.0 if referenced else 0.0
        banned_phrases = [
            "disappointed",
            "so quiet",
            "keep worrying",
            "worrying",
            "text me every day",
            "call me more often",
            "don't stay out late",
            "wasting money",
            "you should",
            "you must",
            "i printed a bunch of things",
        ]
        no_banned = not any(bp in lower_email for bp in banned_phrases)
        scores["email_positive_tone_no_guilt"] = 1.0 if no_banned else 0.0
        lines = [ln.strip() for ln in email_text.splitlines()]
        non_empty = [ln for ln in lines if ln]
        invitation_phrases = [
            "reach out",
            "text me if",
            "call me if",
            "i'm here",
            "i am here",
            "i'm always here",
            "you can call",
            "you can text",
            "here for you",
        ]
        has_invitation = False
        for ln in non_empty[-3:]:
            lnl = ln.lower()
            if any(p in lnl for p in invitation_phrases):
                has_invitation = True
                break
        scores["email_has_open_invitation"] = 1.0 if has_invitation else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()