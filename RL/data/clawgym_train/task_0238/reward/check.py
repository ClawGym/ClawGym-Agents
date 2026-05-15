import json
import sys
import re
import csv
import subprocess
from pathlib import Path
from typing import List, Tuple, Set, Optional, Dict


DATE_RE = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_input_csv(path: Path) -> Set[Tuple[str, str]]:
    result: Set[Tuple[str, str]] = set()
    if not path.exists():
        return result
    try:
        with path.open(encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                title = (row.get('deliverable') or '').strip()
                date = (row.get('due_date') or '').strip()
                if title and DATE_RE.fullmatch(date):
                    result.add((title, date))
    except Exception:
        return set()
    return result


def _strip_tags(s: str) -> str:
    return re.sub(r'<[^>]+>', '', s)


def _parse_input_html(path: Path) -> Set[Tuple[str, str]]:
    result: Set[Tuple[str, str]] = set()
    if not path.exists():
        return result
    html = _read_text(path)
    if html is None:
        return set()
    m = re.search(r'<ul[^>]*id=["\']milestones["\'][^>]*>(.*?)</ul>', html, flags=re.S | re.I)
    if not m:
        return result
    ul = m.group(1)
    lis = re.findall(r'<li([^>]*)>(.*?)</li>', ul, flags=re.S | re.I)
    for attrs, inner in lis:
        date = None
        mdate = re.search(r'data-date=["\'](\d{4}-\d{2}-\d{2})["\']', attrs)
        if mdate:
            date = mdate.group(1)
        else:
            t = _strip_tags(inner)
            mdate2 = DATE_RE.search(t)
            if mdate2:
                date = mdate2.group(1)
        text = _strip_tags(inner)
        text = re.sub(r'\s*\(\d{4}-\d{2}-\d{2}\)\s*', ' ', text)
        title = re.sub(r'\s+', ' ', text).strip()
        if title and date and DATE_RE.fullmatch(date):
            result.add((title, date))
    return result


def _load_milestones_json(path: Path) -> Tuple[bool, Optional[List[Dict]], Optional[Set[Tuple[str, str]]]]:
    if not path.exists():
        return False, None, None
    data = _safe_load_json(path)
    if not isinstance(data, list):
        return False, None, None
    out_set: Set[Tuple[str, str]] = set()
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return False, None, None
        for k in ('title', 'date', 'source'):
            if k not in item:
                return False, None, None
        title = str(item['title']).strip()
        date = str(item['date']).strip()
        source = str(item['source']).strip().lower()
        if source not in {'csv', 'html'}:
            return False, None, None
        if not title or not DATE_RE.fullmatch(date):
            return False, None, None
        out_set.add((title, date))
    return True, data, out_set


def _find_section(text: str, heading: str) -> Optional[str]:
    # Find section starting at exact top-level heading line and ending before next top-level heading
    pattern = re.compile(rf'(?m)^#\s+{re.escape(heading.lstrip("# ").strip())}\s*$')
    m = pattern.search(text)
    if not m:
        return None
    start = m.end()
    m2 = re.search(r'(?m)^#\s+', text[start:])
    end = start + m2.start() if m2 else len(text)
    return text[start:end]


def _extract_bullet_lines(section_text: str) -> List[str]:
    bullets: List[str] = []
    for line in section_text.splitlines():
        m = re.match(r'^\s*[-*+]\s+(.*\S)\s*$', line)
        if m:
            bullets.append(m.group(1))
    return bullets


def _word_count(text: str) -> int:
    words = re.findall(r'\b\w+\b', text)
    return len(words)


def _top_level_headings(text: str) -> List[str]:
    # Return list of top-level heading lines content
    return [line.strip() for line in text.splitlines() if re.match(r'^\s*#\s+', line)]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "milestones_json_structure": 0.0,
        "milestones_json_matches_expected_union": 0.0,
        "plan_headings_required_present": 0.0,
        "plan_headings_exact_top_level_four": 0.0,
        "plan_includes_all_milestones": 0.0,
        "tasks_timeline_chronological_bullets": 0.0,
        "plan_no_todo_and_concise": 0.0,
        "validation_script_passes": 0.0,
    }

    # Compute expected union from inputs
    input_csv = workspace / "input" / "deliverables.csv"
    input_html = workspace / "input" / "research_notes.html"
    expected_csv = _parse_input_csv(input_csv)
    expected_html = _parse_input_html(input_html)
    expected_union = expected_csv | expected_html

    # Load and validate milestones.json
    out_json_path = workspace / "output" / "milestones.json"
    ok_struct, data_json, out_pairs = _load_milestones_json(out_json_path)
    if ok_struct:
        scores["milestones_json_structure"] = 1.0
    else:
        scores["milestones_json_structure"] = 0.0

    if ok_struct and out_pairs is not None and out_pairs == expected_union:
        scores["milestones_json_matches_expected_union"] = 1.0
    else:
        scores["milestones_json_matches_expected_union"] = 0.0

    # Validate project_plan.md
    out_plan_path = workspace / "output" / "project_plan.md"
    txt = _read_text(out_plan_path) or ""
    required_headings = ['# Objectives', '# Data Sources', '# Tasks & Timeline', '# Risks & Assumptions']
    if txt and all(h in txt for h in required_headings):
        scores["plan_headings_required_present"] = 1.0
    else:
        scores["plan_headings_required_present"] = 0.0

    # Exact top-level heading check: exactly the four required and no others
    if txt:
        headings_lines = _top_level_headings(txt)
        normalized = [re.sub(r'\s+', ' ', h).strip() for h in headings_lines]
        required_set = set(required_headings)
        if set(normalized) == required_set and len(normalized) == 4:
            scores["plan_headings_exact_top_level_four"] = 1.0
        else:
            scores["plan_headings_exact_top_level_four"] = 0.0
    else:
        scores["plan_headings_exact_top_level_four"] = 0.0

    # Plan includes all milestones (title and date anywhere)
    if txt and expected_union:
        all_present = True
        for title, date in expected_union:
            if title not in txt or date not in txt:
                all_present = False
                break
        scores["plan_includes_all_milestones"] = 1.0 if all_present else 0.0
    elif txt and not expected_union:
        # If there are no expected milestones, consider this condition trivially satisfied
        scores["plan_includes_all_milestones"] = 1.0
    else:
        scores["plan_includes_all_milestones"] = 0.0

    # Tasks & Timeline section chronological bullet list covering every milestone
    chrono_ok = False
    if txt and expected_union:
        section = _find_section(txt, "# Tasks & Timeline")
        if section is None:
            section = _find_section(txt, "Tasks & Timeline")
        if section:
            bullets = _extract_bullet_lines(section)
            # For each expected milestone in chronological order, find matching bullet line in order
            sorted_expected = sorted(list(expected_union), key=lambda x: x[1])
            idx = 0
            last_found_index = -1
            matched_count = 0
            # Build list of (title, date) found in bullets for order checking
            for title, date in sorted_expected:
                found_here = False
                for i in range(last_found_index + 1, len(bullets)):
                    b = bullets[i]
                    if (title in b) and (date in b):
                        # Ensure bullet contains both title and date
                        last_found_index = i
                        matched_count += 1
                        found_here = True
                        break
                if not found_here:
                    break
            # Check matched all and order (since we progressed last_found_index monotonically)
            if matched_count == len(sorted_expected):
                chrono_ok = True
    else:
        # If no expected milestones, treat as trivially OK
        chrono_ok = bool(txt)

    scores["tasks_timeline_chronological_bullets"] = 1.0 if chrono_ok else 0.0

    # No TODO markers and conciseness (<= 400 words)
    if txt:
        todo_free = ("todo" not in txt.lower())
        concise = (_word_count(txt) <= 400)
        # Split score: 0.5 for TODO-free, 0.5 for conciseness
        subs = 0.0
        subs += 0.5 if todo_free else 0.0
        subs += 0.5 if concise else 0.0
        scores["plan_no_todo_and_concise"] = subs
    else:
        scores["plan_no_todo_and_concise"] = 0.0

    # Run validation script
    tests_script = workspace / "tests" / "validate_outputs.py"
    if tests_script.exists():
        try:
            proc = subprocess.run([sys.executable, str(tests_script)], cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode == 0:
                scores["validation_script_passes"] = 1.0
            else:
                scores["validation_script_passes"] = 0.0
        except Exception:
            scores["validation_script_passes"] = 0.0
    else:
        scores["validation_script_passes"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()