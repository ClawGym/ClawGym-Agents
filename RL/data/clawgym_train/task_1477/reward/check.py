import json
import csv
import re
import sys
from collections import Counter
from pathlib import Path


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_parse_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def _compute_expected_validation(puzzles: Path, scenes: Path):
    puzzles_data = _safe_load_json(puzzles)
    scenes_data = _safe_load_json(scenes)
    if puzzles_data is None or scenes_data is None:
        return None

    allowed_types = {"riddle", "maze", "cipher"}
    allowed_difficulties = {"easy", "medium", "hard"}
    id_pattern = re.compile(r'^PZ-\d{3}$')

    issues = []
    seen_ids = {}

    for idx, p in enumerate(puzzles_data):
        pid = p.get('id')
        ptype = p.get('type')
        pdiff = p.get('difficulty')
        pans = p.get('answer')

        if not isinstance(pid, str) or not id_pattern.match(pid):
            issues.append({
                'category': 'id_invalid_format',
                'puzzle_id': pid,
                'scene_id': None,
                'message': f"puzzle id '{pid}' does not match required pattern PZ-###"
            })

        if ptype not in allowed_types:
            issues.append({
                'category': 'invalid_type',
                'puzzle_id': pid,
                'scene_id': None,
                'message': f"puzzle '{pid}' has invalid type '{ptype}'"
            })

        if pdiff not in allowed_difficulties:
            issues.append({
                'category': 'invalid_difficulty',
                'puzzle_id': pid,
                'scene_id': None,
                'message': f"puzzle '{pid}' has invalid difficulty '{pdiff}'"
            })

        if ptype == 'riddle':
            if not isinstance(pans, str) or re.fullmatch(r'[a-z]+', pans) is None:
                issues.append({
                    'category': 'answer_format',
                    'puzzle_id': pid,
                    'scene_id': None,
                    'message': f"riddle '{pid}' answer should be lowercase letters only"
                })

        if pid in seen_ids:
            first_idx = seen_ids[pid]
            issues.append({
                'category': 'duplicate_id',
                'puzzle_id': pid,
                'scene_id': None,
                'message': f"duplicate puzzle id '{pid}' also seen at index {first_idx}"
            })
        else:
            seen_ids[pid] = idx

    existing_ids = set(seen_ids.keys())

    for s in scenes_data:
        sid = s.get('id')
        for ref in s.get('puzzles', []):
            if ref not in existing_ids:
                issues.append({
                    'category': 'missing_reference',
                    'puzzle_id': ref,
                    'scene_id': sid,
                    'message': f"scene '{sid}' references unknown puzzle id '{ref}'"
                })

    counts = Counter(i['category'] for i in issues)
    summary = {
        'errors': len(issues),
        'categories': dict(sorted(counts.items()))
    }

    # Build expected stdout
    cat_parts = [f"{k}={v}" for k, v in sorted(counts.items())]
    first_line = f"Validation complete: {len(issues)} error(s) found. Categories: {', '.join(cat_parts) if cat_parts else 'none'}"
    lines = [first_line]
    for i in issues:
        loc = i.get('puzzle_id') if i.get('puzzle_id') else '(no puzzle)'
        if i.get('scene_id'):
            loc += f" / scene {i.get('scene_id')}"
        lines.append(f"- [{i.get('category')}] {loc}: {i.get('message')}")
    stdout_text = "\n".join(lines) + ("\n" if lines else "")

    return {
        'issues': issues,
        'summary': summary,
        'stdout': stdout_text
    }


def _load_roles_names(roles_path: Path):
    # Minimal YAML parser for the specific roles.yaml structure
    text = _safe_read_text(roles_path)
    if not text:
        return None
    names = {}
    current_role = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if re.match(r'^\s*roles:\s*$', line):
            continue
        m_role = re.match(r'^\s{2}([a-zA-Z_]+):\s*$', line)
        if m_role:
            current_role = m_role.group(1)
            continue
        m_name = re.match(r'^\s{4}name:\s*(.+?)\s*$', line)
        if m_name and current_role:
            names[current_role] = m_name.group(1)
            continue
    # Return only if we have at least teacher, illustrator, editor
    required = ['teacher', 'illustrator', 'editor']
    if not all(r in names for r in required):
        return None
    return names


def _normalize_none_field(val):
    if val is None:
        return ''
    s = str(val)
    if s.strip().lower() in ('none', 'null'):
        return ''
    return s


def _issues_to_tuples(issues):
    result = []
    for i in issues:
        result.append((
            i.get('category'),
            _normalize_none_field(i.get('puzzle_id')),
            _normalize_none_field(i.get('scene_id')),
            i.get('message')
        ))
    return result


def _read_email(path: Path) -> str:
    return _safe_read_text(path)


def _extract_bullets_after_heading(text: str, heading: str):
    # Find heading case-insensitively; return bullet lines (- or *)
    lines = text.splitlines()
    idx = -1
    for i, line in enumerate(lines):
        if re.search(rf'^\s*{re.escape(heading)}\s*:?\s*$', line, flags=re.IGNORECASE):
            idx = i
            break
    if idx == -1:
        return []
    bullets = []
    for j in range(idx + 1, len(lines)):
        line = lines[j]
        if re.match(r'^\s*[-*]\s+', line):
            bullets.append(line.strip())
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validation_report_exists_and_parseable": 0.0,
        "validation_report_summary_counts_correct": 0.0,
        "validation_report_issues_match": 0.0,
        "run_log_stdout_matches": 0.0,
        "issue_summary_csv_exists_and_header": 0.0,
        "issue_summary_csv_rows_align_with_report": 0.0,
        "email_subject_and_greeting": 0.0,
        "email_issue_summary_counts": 0.0,
        "email_action_items_quality": 0.0,
    }

    # Compute expected from inputs
    puzzles_path = workspace / "data" / "puzzles.json"
    scenes_path = workspace / "data" / "story_scenes.json"
    expected = _compute_expected_validation(puzzles_path, scenes_path)

    out_dir = workspace / "out"
    report_path = out_dir / "validation_report.json"
    log_path = out_dir / "run_log.txt"
    csv_path = out_dir / "issue_summary.csv"
    email_path = out_dir / "email_to_team.txt"
    roles_path = workspace / "team" / "roles.yaml"

    # Load student's report
    report = _safe_load_json(report_path)
    if isinstance(report, dict) and 'issues' in report and 'summary' in report:
        scores["validation_report_exists_and_parseable"] = 1.0

    if expected is not None and report is not None:
        exp_summary = expected['summary']
        rep_summary = report.get('summary', {})
        if isinstance(rep_summary, dict):
            rep_errors = rep_summary.get('errors')
            rep_categories = rep_summary.get('categories')
            if rep_errors == exp_summary.get('errors') and rep_categories == exp_summary.get('categories'):
                scores["validation_report_summary_counts_correct"] = 1.0

        # Compare issues set
        rep_issues = report.get('issues') if isinstance(report.get('issues'), list) else None
        if rep_issues is not None:
            exp_tuples = sorted(_issues_to_tuples(expected['issues']))
            rep_tuples = sorted(_issues_to_tuples(rep_issues))
            if exp_tuples == rep_tuples:
                scores["validation_report_issues_match"] = 1.0

    # Check stdout log
    if expected is not None and log_path.exists():
        actual_log = _safe_read_text(log_path)
        # Normalize by stripping trailing whitespace on each line
        exp_lines = expected['stdout'].splitlines()
        act_lines = actual_log.splitlines()
        exp_norm = [l.rstrip() for l in exp_lines]
        act_norm = [l.rstrip() for l in act_lines]
        if exp_norm == act_norm:
            scores["run_log_stdout_matches"] = 1.0

    # Check CSV header
    rows = _safe_parse_csv(csv_path) if csv_path.exists() else None
    if rows is not None and len(rows) >= 1:
        header = rows[0]
        if header == ["category", "puzzle_id", "scene_id", "message"]:
            scores["issue_summary_csv_exists_and_header"] = 1.0

    # Check CSV rows align with issues in report
    if rows is not None and report is not None and expected is not None and len(rows) >= 1:
        data_rows = rows[1:]
        rep_issues = report.get('issues') if isinstance(report.get('issues'), list) else None
        if rep_issues is not None:
            # Build expected multiset
            exp_tuples = _issues_to_tuples(rep_issues)  # Use student's own report issues to ensure alignment
            # Build csv tuples
            csv_tuples = []
            ok_parse = True
            for r in data_rows:
                if len(r) != 4:
                    ok_parse = False
                    break
                cat, pid, sid, msg = r
                csv_tuples.append((
                    cat,
                    _normalize_none_field(pid),
                    _normalize_none_field(sid),
                    msg
                ))
            if ok_parse:
                # Compare multisets
                exp_counter = Counter(exp_tuples)
                csv_counter = Counter(csv_tuples)
                if exp_counter == csv_counter:
                    scores["issue_summary_csv_rows_align_with_report"] = 1.0

    # Email checks
    email_text = _read_email(email_path) if email_path.exists() else ""
    roles = _load_roles_names(roles_path) if roles_path.exists() else None

    # Subject and greeting
    if email_text and roles is not None:
        subject_line = "Subject: Draft — Puzzle validation findings"
        has_subject = any(line.strip() == subject_line for line in email_text.splitlines())
        # Greeting includes names
        teacher_name = roles.get('teacher')
        illustrator_name = roles.get('illustrator')
        editor_name = roles.get('editor')
        names_present = all(n and (n in email_text) for n in [teacher_name, illustrator_name, editor_name])
        if has_subject and names_present:
            scores["email_subject_and_greeting"] = 1.0

    # Issue summary counts
    if email_text and report is not None and expected is not None:
        has_issue_summary_heading = re.search(r'\bIssue\s+summary\b', email_text, flags=re.IGNORECASE) is not None
        rep_summary = report.get('summary', {})
        total_errors = rep_summary.get('errors')
        categories = rep_summary.get('categories', {}) if isinstance(rep_summary.get('categories'), dict) else {}
        # Find total errors mention
        total_ok = False
        if isinstance(total_errors, int):
            # patterns like "6 errors" or "errors: 6"
            if re.search(rf'\b{total_errors}\s+errors?\b', email_text, flags=re.IGNORECASE):
                total_ok = True
            elif re.search(rf'\berrors?\s*:\s*{total_errors}\b', email_text, flags=re.IGNORECASE):
                total_ok = True
        # Check per-category counts
        cats_ok = True
        for cat, cnt in categories.items():
            found = False
            # cat followed by number
            if re.search(rf'\b{re.escape(cat)}\b[^\d]{{0,10}}{cnt}\b', email_text):
                found = True
            # number followed by cat
            elif re.search(rf'\b{cnt}\b[^\w]{{0,10}}\b{re.escape(cat)}\b', email_text):
                found = True
            if not found:
                cats_ok = False
                break
        if has_issue_summary_heading and total_ok and cats_ok:
            scores["email_issue_summary_counts"] = 1.0

    # Action items quality
    if email_text and roles is not None and expected is not None:
        bullets = _extract_bullets_after_heading(email_text, "Action items")
        # Collect IDs from expected issues
        exp_issue_ids = set()
        exp_scene_ids = set()
        for i in expected['issues']:
            pid = i.get('puzzle_id')
            sid = i.get('scene_id')
            if isinstance(pid, str):
                exp_issue_ids.add(pid)
            if isinstance(sid, str):
                exp_scene_ids.add(sid)
        id_patterns = [re.escape(x) for x in sorted(exp_issue_ids | exp_scene_ids)]
        # Owners
        owner_names = {roles.get('teacher'), roles.get('illustrator'), roles.get('editor')}
        owner_names = {n for n in owner_names if n}
        # Validate bullets: at least three and each has an ID and an owner
        if len(bullets) >= 3:
            all_bullets_valid = True
            valid_count = 0
            teacher_confirm_ok = False
            for b in bullets:
                has_id = any(re.search(rf'\b{p}\b', b) for p in id_patterns)
                has_owner = any(n in b for n in owner_names)
                if has_id and has_owner:
                    valid_count += 1
                else:
                    all_bullets_valid = False
                # Teacher confirmation check
                teacher_name = roles.get('teacher')
                if teacher_name and (teacher_name in b) and re.search(r'\bconfirm\b', b, flags=re.IGNORECASE):
                    if re.search(r'\briddle\b', b, flags=re.IGNORECASE) and (
                        re.search(r'\bformat\b', b, flags=re.IGNORECASE) or
                        re.search(r'\bformatting\b', b, flags=re.IGNORECASE) or
                        re.search(r'\blowercase\b', b, flags=re.IGNORECASE)
                    ):
                        teacher_confirm_ok = True
            # Require at least three valid bullets and teacher confirm bullet
            if valid_count >= 3 and teacher_confirm_ok and all_bullets_valid:
                scores["email_action_items_quality"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()