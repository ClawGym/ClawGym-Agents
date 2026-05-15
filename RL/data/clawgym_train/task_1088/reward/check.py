import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def parse_meetings(meetings_dir: Path) -> Tuple[Dict[str, int], List[Tuple[str, str]]]:
    votes: Dict[str, int] = {}
    decisions: List[Tuple[str, str]] = []
    if not meetings_dir.exists() or not meetings_dir.is_dir():
        return votes, decisions

    vote_re = re.compile(r'^VOTE\s+([A-Za-z0-9\-]+)\s+\+([0-9]+)\s*$')
    date_re = re.compile(r'^Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$')
    decision_re = re.compile(r'^\s*DECISION:\s*(.+)\s*$')

    for md_path in sorted(meetings_dir.glob("*.md")):
        text = read_text_safe(md_path)
        if text is None:
            continue
        lines = text.splitlines()
        current_date = None
        for line in lines:
            stripped = line.strip()
            m_date = date_re.match(stripped)
            if m_date:
                current_date = m_date.group(1)
            m_vote = vote_re.match(stripped)
            if m_vote:
                item_id = m_vote.group(1).strip()
                amount = int(m_vote.group(2))
                votes[item_id] = votes.get(item_id, 0) + amount
            m_dec = decision_re.match(line)
            if m_dec:
                decision_text = "DECISION: " + m_dec.group(1).strip()
                decisions.append((current_date if current_date else "", decision_text))
    return votes, decisions


def parse_backlog(backlog_path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    header, rows = load_csv_safe(backlog_path)
    if header is None or rows is None:
        return None
    dedup: Dict[str, Dict[str, str]] = {}
    for row in rows:
        if 'id' not in row or 'status' not in row:
            return None
        dedup[row['id']] = row
    result: Dict[str, Dict[str, str]] = {}
    for k, row in dedup.items():
        status = (row.get('status') or '').strip()
        if status not in {"proposed", "candidate"}:
            continue
        if 'title' not in row or 'estimated_hours' not in row:
            return None
        try:
            int(str(row['estimated_hours']).strip())
        except Exception:
            return None
        result[k] = {
            'id': row['id'],
            'title': row['title'],
            'status': status,
            'estimated_hours': str(int(str(row['estimated_hours']).strip()))
        }
    return result


def compute_top5(votes: Dict[str, int], backlog: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for item_id, total in votes.items():
        if item_id in backlog and total > 0:
            b = backlog[item_id]
            items.append({
                'id': item_id,
                'title': b['title'],
                'estimated_hours': str(int(b['estimated_hours'])),
                'votes_total': str(int(total))
            })
    def sort_key(d: Dict[str, str]):
        return (-int(d['votes_total']), int(d['estimated_hours']), d['id'])
    items.sort(key=sort_key)
    return items[:5]


def extract_section(text: str, heading: str) -> Tuple[Optional[str], int, int]:
    lines = text.splitlines(keepends=True)
    heading_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading:
            heading_idx = i
            break
    if heading_idx is None:
        return None, -1, -1
    # section starts after heading line
    start_line = heading_idx + 1
    end_line = len(lines)
    for j in range(start_line, len(lines)):
        if lines[j].lstrip().startswith("## ") and j != start_line:
            end_line = j
            break
    # compute char indices
    start_char = sum(len(lines[k]) for k in range(0, start_line))
    end_char = sum(len(lines[k]) for k in range(0, end_line))
    section_text = "".join(lines[start_line:end_line])
    return section_text, start_char, end_char


def original_constraints_suffix() -> str:
    # Original tail from "## Constraints" to end, as provided
    return (
        "## Constraints\n"
        "- Keep scope small enough for a 2–3 week sprint.\n"
        "- All content must be OK to share with classmates.\n"
    )


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "prioritized_csv_exists_and_header": 0.0,
        "prioritized_csv_top5_rows_correct": 0.0,
        "overview_meeting_summary_replaced_and_top_mention": 0.0,
        "overview_decisions_section_bullets_with_dates": 0.0,
        "overview_prioritized_backlog_contains_top5": 0.0,
        "overview_prioritized_backlog_order_correct": 0.0,
        "constraints_section_unchanged_if_edited": 0.0,
    }

    # Prepare expected data from inputs
    meetings_dir = workspace / "input" / "meetings"
    votes, decisions = parse_meetings(meetings_dir)

    backlog_path = workspace / "input" / "backlog.csv"
    backlog = parse_backlog(backlog_path) if backlog_path.exists() else None

    expected_top5: List[Dict[str, str]] = []
    if backlog is not None and votes:
        expected_top5 = compute_top5(votes, backlog)

    # Check output/prioritized_backlog.csv
    prioritized_path = workspace / "output" / "prioritized_backlog.csv"
    header, rows = load_csv_safe(prioritized_path)
    expected_header = ["id", "title", "estimated_hours", "votes_total"]
    if header is not None and rows is not None and header == expected_header and len(rows) == 5:
        scores["prioritized_csv_exists_and_header"] = 1.0
        # Validate correctness if we can compute expected
        if expected_top5 and len(expected_top5) == 5:
            all_match = True
            for i, exp in enumerate(expected_top5):
                row = rows[i]
                for k in expected_header:
                    if (row.get(k) or "").strip() != exp[k]:
                        all_match = False
                        break
                if not all_match:
                    break
            scores["prioritized_csv_top5_rows_correct"] = 1.0 if all_match else 0.0
        else:
            scores["prioritized_csv_top5_rows_correct"] = 0.0
    else:
        scores["prioritized_csv_exists_and_header"] = 0.0
        scores["prioritized_csv_top5_rows_correct"] = 0.0

    # Check docs/project_overview.md modifications
    overview_path = workspace / "docs" / "project_overview.md"
    overview_text = read_text_safe(overview_path)
    if overview_text is not None:
        # Extract sections
        meeting_heading = "## Meeting Summary (to be generated)"
        backlog_heading = "## Prioritized Backlog (to be generated)"
        meeting_section, ms_start, ms_end = extract_section(overview_text, meeting_heading)
        backlog_section, pb_start, pb_end = extract_section(overview_text, backlog_heading)

        # Gate: ensure sections exist and TODOs removed to award doc-related points
        sections_present = (meeting_section is not None) and (backlog_section is not None)
        todos_removed = False
        if sections_present:
            ms_has_todo = "TODO:" in meeting_section
            pb_has_todo = "TODO:" in backlog_section
            todos_removed = (not ms_has_todo) and (not pb_has_todo)

        # Meeting summary replaced and mentions top
        if sections_present and todos_removed and meeting_section is not None and expected_top5:
            top_item = expected_top5[0]
            top_id = top_item['id']
            top_votes = top_item['votes_total']
            has_top = (top_id in meeting_section) and (str(top_votes) in meeting_section)
            # Mention across two meetings: require both dates to appear somewhere in section
            has_dates = ("2026-03-01" in meeting_section) and ("2026-03-08" in meeting_section)
            if has_top and has_dates:
                scores["overview_meeting_summary_replaced_and_top_mention"] = 1.0

        # Decisions bullets with dates and quotes
        if sections_present and todos_removed and meeting_section is not None and decisions:
            # Require a "Decisions" label (case-insensitive, whole word)
            has_label = re.search(r'\bDecisions\b', meeting_section, flags=re.IGNORECASE) is not None
            bullet_lines = [ln.strip() for ln in meeting_section.splitlines() if ln.strip().startswith("-")]
            all_decisions_found = True
            for dt, dec_text in decisions:
                found = False
                for b in bullet_lines:
                    if (dt in b) and (dec_text in b):
                        # Ensure date prefix occurs before DECISION:
                        idx_dec = b.find("DECISION:")
                        idx_dt = b.find(dt)
                        if idx_dec != -1 and idx_dt != -1 and idx_dt <= idx_dec:
                            found = True
                            break
                if not found:
                    all_decisions_found = False
                    break
            if has_label and all_decisions_found:
                scores["overview_decisions_section_bullets_with_dates"] = 1.0

        # Prioritized backlog section contains top5 and in correct order
        if sections_present and todos_removed and backlog_section is not None and expected_top5:
            contains_all = True
            positions: List[int] = []
            for item in expected_top5:
                id_ = item['id']
                title = item['title']
                votes_total = item['votes_total']
                hours = item['estimated_hours']
                # Find a line containing all fields
                lines = backlog_section.splitlines()
                matched_line_idx = None
                for idx, ln in enumerate(lines):
                    if (id_ in ln) and (title in ln) and (votes_total in ln) and (hours in ln):
                        matched_line_idx = idx
                        break
                if matched_line_idx is None:
                    contains_all = False
                    positions.append(10**9)
                else:
                    positions.append(matched_line_idx)
            if contains_all:
                scores["overview_prioritized_backlog_contains_top5"] = 1.0
                in_order = all(positions[i] < positions[i+1] for i in range(len(positions)-1))
                if in_order:
                    scores["overview_prioritized_backlog_order_correct"] = 1.0

        # Constraints section unchanged (only if edited sections are non-TODO to avoid baseline credit)
        if sections_present and todos_removed:
            # Compare suffix from "## Constraints" to end against original
            constraints_idx = overview_text.find("## Constraints")
            if constraints_idx != -1:
                current_suffix = overview_text[constraints_idx:]
                if current_suffix == original_constraints_suffix():
                    scores["constraints_section_unchanged_if_edited"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()