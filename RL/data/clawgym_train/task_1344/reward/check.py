import json
import csv
import sys
import re
import importlib
import importlib.util
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import tempfile
import os


def read_text_safe(path: Path) -> Tuple[bool, Optional[str]]:
    try:
        if not path.exists():
            return False, None
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, None


def load_json_safe(path: Path) -> Tuple[bool, Optional[dict]]:
    try:
        if not path.exists():
            return False, None
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def load_csv_dicts_safe(path: Path) -> Tuple[bool, Optional[List[Dict[str, str]]]]:
    try:
        if not path.exists():
            return False, None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return True, rows
    except Exception:
        return False, None


def find_heading_section(text: str, heading: str) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        m = re.match(r'^\s*#{1,6}\s*(.+?)\s*$', line)
        if m and m.group(1).strip() == heading:
            start_idx = i
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if re.match(r'^\s*#{1,6}\s*\S', lines[j]):
            end_idx = j
            break
    section_lines = lines[start_idx + 1:end_idx]
    return "\n".join(section_lines).strip()


def count_words(text: str) -> int:
    return len(re.findall(r'\b\w+\b', text))


def extract_named_message(text: str, label: str) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == label or re.match(r'^\s*#{1,6}\s*' + re.escape(label) + r'\s*$', stripped):
            start_idx = i
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        nxt = lines[j].strip()
        if nxt == "Message 1" or nxt == "Message 2" or re.match(r'^\s*#{1,6}\s*(Message 1|Message 2)\s*$', nxt):
            end_idx = j
            break
    body = "\n".join(lines[start_idx + 1:end_idx]).strip()
    return body


def import_refactored_module(workspace: Path, module_name: str) -> Tuple[bool, Optional[object], Optional[str]]:
    ref_src = workspace / "output" / "refactored" / "src"
    if not ref_src.exists():
        return False, None, "refactored source dir missing"
    old_sys_path = list(sys.path)
    old_cwd = os.getcwd()
    try:
        sys.path.insert(0, str(ref_src))
        os.chdir(str(workspace))
        try:
            module = importlib.import_module(module_name)
            return True, module, None
        except Exception as e:
            return False, None, f"import error: {e}"
    finally:
        try:
            os.chdir(old_cwd)
        except Exception:
            pass
        try:
            if sys.path and sys.path[0] == str(ref_src):
                sys.path.pop(0)
        except Exception:
            pass


def compute_expected_gpas_from_config_and_data(workspace: Path) -> Tuple[bool, Optional[Dict[str, float]]]:
    ok_cfg, cfg = load_json_safe(workspace / "config" / "settings.json")
    ok_csv, rows = load_csv_dicts_safe(workspace / "data" / "sample_students.csv")
    if not ok_cfg or not ok_csv or cfg is None or rows is None:
        return False, None
    scale = cfg.get("gpa_scale", {})
    expected: Dict[str, float] = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        grades_str = (row.get("grades") or "").strip()
        grades = [g.strip() for g in grades_str.split(";") if g.strip()]
        pts = [float(scale.get(g, 0.0)) for g in grades]
        gpa = round((sum(pts) / len(pts)) if pts else 0.0, 2)
        expected[name] = gpa
    return True, expected


def load_expected_from_tests(workspace: Path) -> Tuple[bool, Optional[Dict[str, float]]]:
    ok, obj = load_json_safe(workspace / "tests" / "expected_gpa.json")
    if not ok or obj is None:
        return False, None
    exp = {}
    try:
        for s in obj.get("students", []):
            name = s["name"]
            gpa = float(s["expected_gpa"])
            exp[name] = gpa
        return True, exp
    except Exception:
        return False, None


def get_action_items(text: str) -> List[str]:
    items = []
    for line in text.splitlines():
        if re.match(r'^\s*\d+\.\s+', line):
            items.append(line.strip())
    return items


def check_logging_setup(texts: List[str]) -> bool:
    no_prints = all("print(" not in t for t in texts)
    uses_logger = any(re.search(r'logging\.getLogger\(\s*__name__\s*\)', t) for t in texts)
    return no_prints and uses_logger


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "refactored_utils_contains_calculate_gpa": 0.0,
        "gradebook_uses_utils_calculate_gpa": 0.0,
        "refactored_no_prints_and_has_logging": 0.0,
        "logging_setup_from_config_present": 0.0,
        "class_and_methods_preserved": 0.0,
        "calculate_gpa_returns_expected_values": 0.0,
        "export_matches_expected_gpas": 0.0,
        "report_sections_and_inventory": 0.0,
        "code_issues_with_line_numbers": 0.0,
        "verification_plan_references_files": 0.0,
        "remaining_risks_and_next_steps_present": 0.0,
        "revised_messages_two_under_120": 0.0,
        "meeting_notes_sections_and_five_actions": 0.0,
        "action_items_have_owners_and_due": 0.0,
        "status_update_three_bullets_and_topics": 0.0,
    }

    ref_utils = workspace / "output" / "refactored" / "src" / "utils.py"
    ref_gradebook = workspace / "output" / "refactored" / "src" / "gradebook.py"

    ok_utils_text, utils_text = read_text_safe(ref_utils)
    if ok_utils_text and utils_text:
        if re.search(r'def\s+calculate_gpa\s*\(\s*\w+\s*,\s*\w+\s*\)\s*:', utils_text):
            scores["refactored_utils_contains_calculate_gpa"] = 1.0

    ok_gb_text, gb_text = read_text_safe(ref_gradebook)
    if ok_gb_text and gb_text:
        uses_utils_call = ("utils.calculate_gpa" in gb_text) or (
            re.search(r'from\s+utils\s+import\s+calculate_gpa', gb_text) and "calculate_gpa(" in gb_text
        )
        no_dup_scale = ('"A": 4.0' not in gb_text) and ('LETTER_POINTS' not in gb_text)
        if uses_utils_call and no_dup_scale:
            scores["gradebook_uses_utils_calculate_gpa"] = 1.0

    if ok_utils_text and ok_gb_text and utils_text and gb_text:
        if check_logging_setup([utils_text, gb_text]):
            scores["refactored_no_prints_and_has_logging"] = 1.0

        logging_cfg_ref = ("logging_level" in utils_text) or ("logging_level" in gb_text) \
            or ("config/settings.json" in utils_text) or ("config/settings.json" in gb_text)
        if logging_cfg_ref:
            scores["logging_setup_from_config_present"] = 1.0

    ok_gradebook_mod, gb_mod, _ = import_refactored_module(workspace, "gradebook")
    ok_utils_mod, utils_mod, _ = import_refactored_module(workspace, "utils")

    if ok_gradebook_mod and gb_mod is not None:
        Gradebook = getattr(gb_mod, "Gradebook", None)
        if Gradebook is not None:
            has_methods = all(hasattr(Gradebook, m) for m in ["load_from_csv", "compute_gpa", "export_csv"])
            if has_methods:
                scores["class_and_methods_preserved"] = 1.0

    ok_cfg, cfg = load_json_safe(workspace / "config" / "settings.json")
    ok_csv, sample_rows = load_csv_dicts_safe(workspace / "data" / "sample_students.csv")
    if ok_utils_mod and utils_mod is not None and ok_cfg and ok_csv and cfg and sample_rows:
        calc = getattr(utils_mod, "calculate_gpa", None)
        scale = cfg.get("gpa_scale", {})
        alice_row = None
        for r in sample_rows:
            if (r.get("name") or "").strip() == "Alice":
                alice_row = r
                break
        try:
            if callable(calc) and alice_row:
                grades_str = (alice_row.get("grades") or "").strip()
                grades = [g.strip() for g in grades_str.split(";") if g.strip()]
                val = calc(grades, scale)
                if abs(float(val) - 3.67) < 1e-6:
                    scores["calculate_gpa_returns_expected_values"] = 1.0
        except Exception:
            pass

    ok_tests_exp, tests_exp = load_expected_from_tests(workspace)
    ok_expected_cfg, expected_cfg = compute_expected_gpas_from_config_and_data(workspace)
    if ok_gradebook_mod and gb_mod is not None and ok_tests_exp and tests_exp and ok_csv and sample_rows:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_out = Path(tmpdir) / "out.csv"
                old_cwd = os.getcwd()
                os.chdir(str(workspace))
                try:
                    gb = gb_mod.Gradebook()
                    data_path = workspace / "data" / "sample_students.csv"
                    gb.load_from_csv(str(data_path))
                    gb.export_csv(str(tmp_out))
                finally:
                    os.chdir(old_cwd)
                ok_exp_csv, exp_rows = load_csv_dicts_safe(tmp_out)
                if ok_exp_csv and exp_rows is not None:
                    got = {}
                    valid_fields = True
                    for row in exp_rows:
                        if "name" not in row or "gpa" not in row:
                            valid_fields = False
                            break
                        name = (row["name"] or "").strip()
                        gpa_str = (row["gpa"] or "").strip()
                        if not re.match(r'^\d+(\.\d{2})$', gpa_str):
                            valid_fields = False
                            break
                        got[name] = float(gpa_str)
                    names_match = set(got.keys()) == set(tests_exp.keys())
                    values_match = names_match and all(abs(got[n] - tests_exp[n]) < 1e-6 for n in got.keys())
                    cfg_match = True
                    if expected_cfg:
                        cfg_match = set(got.keys()) == set(expected_cfg.keys()) and all(abs(got[n] - expected_cfg[n]) < 1e-6 for n in got.keys())
                    if valid_fields and values_match and cfg_match:
                        scores["export_matches_expected_gpas"] = 1.0
        except Exception:
            pass

    report_path = workspace / "output" / "report" / "refactoring_summary.md"
    ok_report, report_text = read_text_safe(report_path)
    if ok_report and report_text:
        required_sections = [
            "Overview",
            "Repository Inventory",
            "Code Issues Identified",
            "Refactoring Changes",
            "Verification Plan",
            "Remaining Risks and Next Steps",
        ]
        sections_ok = all(find_heading_section(report_text, s) is not None for s in required_sections)
        inv = find_heading_section(report_text, "Repository Inventory") or ""
        files_required = [
            "src/gradebook.py",
            "src/utils.py",
            "config/settings.json",
            "data/sample_students.csv",
            "tests/expected_gpa.json",
            "messages/drafts.md",
            "README.md",
        ]
        inventory_ok = all(f in inv for f in files_required)
        if sections_ok and inventory_ok:
            scores["report_sections_and_inventory"] = 1.0

        issues_sec = find_heading_section(report_text, "Code Issues Identified") or ""
        issue_lines = [l for l in issues_sec.splitlines() if ("src/gradebook.py" in l or "src/utils.py" in l or "README.md" in l)]
        count_with_line_nums = 0
        for l in issue_lines:
            if re.search(r':\d+\b', l) or re.search(r'\bline\s+\d+\b', l, flags=re.IGNORECASE):
                count_with_line_nums += 1
        if count_with_line_nums >= 3:
            scores["code_issues_with_line_numbers"] = 1.0

        ver = find_heading_section(report_text, "Verification Plan") or ""
        if "tests/expected_gpa.json" in ver and "data/sample_students.csv" in ver:
            scores["verification_plan_references_files"] = 1.0

        risks = find_heading_section(report_text, "Remaining Risks and Next Steps") or ""
        list_items = [l for l in risks.splitlines() if re.match(r'^\s*[-*]\s+.+', l)]
        if len(list_items) >= 2:
            scores["remaining_risks_and_next_steps_present"] = 1.0

    revised_path = workspace / "output" / "messages" / "revised.md"
    ok_rev, rev_text = read_text_safe(revised_path)
    if ok_rev and rev_text:
        msg1 = extract_named_message(rev_text, "Message 1")
        msg2 = extract_named_message(rev_text, "Message 2")
        if msg1 is not None and msg2 is not None:
            if count_words(msg1) <= 120 and count_words(msg2) <= 120 and len(msg1.strip()) > 0 and len(msg2.strip()) > 0:
                scores["revised_messages_two_under_120"] = 1.0

    notes_path = workspace / "output" / "meeting" / "notes.md"
    ok_notes, notes_text = read_text_safe(notes_path)
    if ok_notes and notes_text:
        has_agenda = find_heading_section(notes_text, "Agenda") is not None
        has_decisions = find_heading_section(notes_text, "Decisions") is not None
        has_actions = find_heading_section(notes_text, "Action Items") is not None
        actions_section = find_heading_section(notes_text, "Action Items") or ""
        items = get_action_items(actions_section)
        if has_agenda and has_decisions and has_actions and len(items) >= 5:
            scores["meeting_notes_sections_and_five_actions"] = 1.0
        owners = ["Dev", "QA", "PM", "You"]
        due_markers = [" by ", "EOD", "EOW", "today", "tomorrow", "next ", "due ", "Due "]
        if items:
            owners_due_ok = True
            for it in items[:5]:
                has_owner = any(o in it for o in owners)
                has_due = any(dm in it for dm in due_markers) or re.search(r'\b\d{4}-\d{2}-\d{2}\b', it) is not None
                if not (has_owner and has_due):
                    owners_due_ok = False
                    break
            if owners_due_ok:
                scores["action_items_have_owners_and_due"] = 1.0

    status_path = workspace / "output" / "status" / "update.md"
    ok_status, status_text = read_text_safe(status_path)
    if ok_status and status_text:
        bullets = [l.strip() for l in status_text.splitlines() if re.match(r'^\s*[-*]\s+', l)]
        total_words = count_words(status_text)
        topics_ok = False
        if len(bullets) == 3 and total_words <= 120:
            b1, b2, b3 = bullets
            t1 = re.search(r'\brefactor(ed|ing)?\b|\bclean\s*up\b|\brestructure', b1, flags=re.IGNORECASE) is not None
            t2 = re.search(r'\bimpact\b|\brisk\b|\bexpected\b', b2, flags=re.IGNORECASE) is not None
            t3 = re.search(r'\breview\b|\bfeedback\b|\brequest\b', b3, flags=re.IGNORECASE) is not None
            topics_ok = t1 and t2 and t3
        if topics_ok:
            scores["status_update_three_bullets_and_topics"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()