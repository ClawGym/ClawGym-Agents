import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple, Dict


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Ensure headers exist if file is empty
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _find_latest_notes_file(notes_dir: Path) -> Tuple[Optional[Path], Optional[str]]:
    if not notes_dir.exists() or not notes_dir.is_dir():
        return None, None
    latest_path = None
    latest_date = None
    for p in notes_dir.iterdir():
        if not p.is_file():
            continue
        m = re.match(r"^(\d{4}-\d{2}-\d{2})_meeting_notes\.md$", p.name)
        if not m:
            continue
        date_str = m.group(1)
        # validate date
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        if latest_date is None or dt > latest_date:
            latest_date = dt
            latest_path = p
    if latest_path is None or latest_date is None:
        return None, None
    return latest_path, latest_date.strftime("%Y-%m-%d")


def _parse_notes_agenda(notes_text: str) -> List[str]:
    # Extract bullets under "## Agenda" until next "##" or EOF
    lines = notes_text.splitlines()
    agenda_items: List[str] = []
    in_agenda = False
    for line in lines:
        if re.match(r"^##\s+Agenda\s*$", line.strip(), flags=re.I):
            in_agenda = True
            continue
        if in_agenda and re.match(r"^##\s+", line.strip()):
            break
        if in_agenda:
            m = re.match(r"^\s*-\s+(.*\S)\s*$", line)
            if m:
                agenda_items.append(m.group(1).strip())
    return agenda_items


def _parse_notes_attendees_line(notes_text: str) -> Optional[str]:
    # Find line starting with "Attendees:"
    for line in notes_text.splitlines():
        if line.strip().lower().startswith("attendees:"):
            # Return the portion after "Attendees:"
            rest = line.split(":", 1)[1].strip()
            return rest
    return None


def _parse_notes_decisions(notes_text: str) -> List[str]:
    decisions: List[str] = []
    for line in notes_text.splitlines():
        m = re.match(r"^\s*Decision:\s*(.+?)\s*$", line, flags=re.I)
        if m:
            decisions.append(m.group(1).strip())
    return decisions


def _parse_notes_actions(notes_text: str) -> List[Dict[str, str]]:
    actions: List[Dict[str, str]] = []
    for line in notes_text.splitlines():
        m = re.match(r"^\s*Action:\s*(.+?)\s*$", line, flags=re.I)
        if not m:
            continue
        payload = m.group(1).strip()
        # Split on first ' to ' (case-insensitive)
        parts = re.split(r"\s+to\s+", payload, maxsplit=1, flags=re.I)
        if len(parts) == 2:
            owner_part = parts[0].strip()
            task_part = parts[1].strip().rstrip(".")
        else:
            # Fallback: owner unknown, entire text as task
            owner_part = ""
            task_part = payload.strip().rstrip(".")
        # Extract owner name (first word before any parenthesis)
        owner_match = re.match(r"^\s*([A-Za-z\-]+)", owner_part)
        owner_name = owner_match.group(1) if owner_match else owner_part.strip()
        actions.append({
            "owner_raw": owner_part,
            "owner_name": owner_name,
            "task": task_part,
            "raw": payload,
        })
    return actions


def _month_add(year: int, month: int, delta: int) -> Tuple[int, int]:
    # Add delta months to year-month
    total = year * 12 + (month - 1) + delta
    y = total // 12
    m = total % 12 + 1
    return y, m


def _compute_metrics_snapshot(rows: List[Dict[str, str]], meeting_date: str) -> Optional[Dict[str, str]]:
    try:
        dt = datetime.strptime(meeting_date, "%Y-%m-%d")
    except Exception:
        return None
    y, m = dt.year, dt.month
    months = []
    for d in (-2, -1, 0):
        yy, mm = _month_add(y, m, d)
        months.append(f"{yy:04d}-{mm:02d}")
    # Filter rows for these months
    selected = [r for r in rows if r.get("month") in months]
    if not selected:
        return None
    # Sort by month order months list for consistent calc
    selected_sorted = sorted(selected, key=lambda r: months.index(r.get("month")) if r.get("month") in months else 0)
    # Aggregate
    try:
        sum_sub = sum(int(r["submissions"]) for r in selected_sorted)
        sum_acc = sum(int(r["acceptances"]) for r in selected_sorted)
        mean_oa = sum(float(r["oa_share"]) for r in selected_sorted) / len(selected_sorted)
        mean_rev = sum(float(r["avg_review_days"]) for r in selected_sorted) / len(selected_sorted)
    except Exception:
        return None
    acceptance_rate = 0.0 if sum_sub == 0 else (sum_acc / sum_sub)
    snapshot = {
        "period_start": months[0],
        "period_end": months[-1],
        "submissions_total": str(sum_sub),
        "acceptance_rate": f"{acceptance_rate:.2f}",
        "oa_share_mean": f"{mean_oa:.2f}",
        "avg_review_days_mean": f"{mean_rev:.1f}",
        "meeting_date": meeting_date,
    }
    return snapshot


def _extract_summary_sections(summary_text: str) -> Dict[str, Dict[str, List[str]]]:
    # Returns a dict with:
    # "title": {"lines": [str]}
    # For each header: key is header label (with colon), with "inline" content (from same line), and "lines" subsequent lines
    headers = ["Attendees:", "Agenda:", "Decisions:", "Action Items:", "Discussion Highlights:", "Metrics Snapshot:"]
    lines = summary_text.splitlines()
    # Find first non-empty line as title
    first_non_empty = None
    for line in lines:
        if line.strip() != "":
            first_non_empty = line.strip()
            break
    sections: Dict[str, Dict[str, List[str]]] = {}
    sections["__title__"] = {"lines": [first_non_empty] if first_non_empty is not None else []}
    # Find header indices
    header_positions: List[Tuple[str, int, str]] = []
    for idx, line in enumerate(lines):
        for h in headers:
            if line.startswith(h):
                inline = line[len(h):].strip()
                header_positions.append((h, idx, inline))
                break
    # Sort by occurrence
    header_positions.sort(key=lambda x: x[1])
    # Extract contents between headers
    for i, (h, idx, inline) in enumerate(header_positions):
        next_idx = header_positions[i + 1][1] if i + 1 < len(header_positions) else len(lines)
        content_lines = []
        # Include same-line inline content if any as first content line
        if inline:
            content_lines.append(inline)
        # Lines after header till next header
        for j in range(idx + 1, next_idx):
            content_lines.append(lines[j])
        sections[h] = {"lines": content_lines}
    return sections


def _normalize_comma_list(s: str) -> str:
    # Normalize comma-separated list to consistent spacing: "a, b, c"
    parts = [p.strip() for p in s.split(",") if p.strip() != ""]
    return ", ".join(parts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "filenames_use_latest_meeting_date": 0.0,
        "summary_file_exists": 0.0,
        "summary_title_and_order": 0.0,
        "attendees_extracted_correctly": 0.0,
        "agenda_extracted_exact": 0.0,
        "decisions_extracted": 0.0,
        "action_items_normalized_and_complete": 0.0,
        "discussion_highlights_present_limited": 0.0,
        "metrics_csv_exists_and_schema": 0.0,
        "metrics_csv_values_correct": 0.0,
        "metrics_snapshot_in_summary_correct": 0.0,
        "keyword_counts_in_summary_correct": 0.0,
    }

    notes_dir = workspace / "input" / "notes"
    latest_notes_path, latest_date = _find_latest_notes_file(notes_dir)

    # Expected output files
    expected_summary = workspace / "output" / f"meeting_summary_{latest_date}.md" if latest_date else None
    expected_metrics_csv = workspace / "output" / f"metrics_snapshot_{latest_date}.csv" if latest_date else None

    # Check filenames/date usage
    if latest_date and expected_summary and expected_metrics_csv:
        if expected_summary.exists() and expected_metrics_csv.exists():
            scores["filenames_use_latest_meeting_date"] = 1.0

    # Summary file existence
    summary_text = None
    if expected_summary and expected_summary.exists():
        summary_text = _safe_read_text(expected_summary)
        if summary_text is not None and summary_text != "":
            scores["summary_file_exists"] = 1.0

    # Parse summary for structure/order/title
    sections = {}
    if summary_text:
        sections = _extract_summary_sections(summary_text)
        # Check title equals "Meeting Summary — <YYYY-MM-DD>" allowing leading '#'
        title_lines = sections.get("__title__", {}).get("lines", [])
        title_ok = False
        if title_lines:
            t = title_lines[0]
            # Remove leading hashes and spaces
            t_norm = t.lstrip("#").strip()
            expected_title = f"Meeting Summary — {latest_date}" if latest_date else None
            if expected_title and t_norm == expected_title:
                title_ok = True

        # Check section order
        headers = ["Attendees:", "Agenda:", "Decisions:", "Action Items:", "Discussion Highlights:", "Metrics Snapshot:"]
        # Determine order by their first occurrence line index
        lines = summary_text.splitlines()
        header_indices = []
        order_ok = True
        last_idx = -1
        for h in headers:
            idx = None
            for i, line in enumerate(lines):
                if line.startswith(h):
                    idx = i
                    break
            if idx is None:
                order_ok = False
                break
            if idx <= last_idx:
                order_ok = False
                break
            last_idx = idx
            header_indices.append(idx)
        if title_ok and order_ok:
            scores["summary_title_and_order"] = 1.0

    # Load notes text
    notes_text = _safe_read_text(latest_notes_path) if latest_notes_path else None

    # Attendees check
    if summary_text and notes_text:
        expected_attendees = _parse_notes_attendees_line(notes_text)
        attendees_section = sections.get("Attendees:", {})
        attendees_lines = attendees_section.get("lines", []) if attendees_section else []
        attendees_joined = " ".join([l.strip() for l in attendees_lines]).strip()
        # If attendees provided inline on header line, it's already included
        if expected_attendees is not None and attendees_joined:
            if _normalize_comma_list(expected_attendees) == _normalize_comma_list(attendees_joined):
                scores["attendees_extracted_correctly"] = 1.0

    # Agenda exact extraction check
    if summary_text and notes_text:
        expected_agenda = _parse_notes_agenda(notes_text)
        agenda_section = sections.get("Agenda:", {})
        agenda_lines = agenda_section.get("lines", []) if agenda_section else []
        agenda_bullets = []
        for ln in agenda_lines:
            m = re.match(r"^\s*-\s+(.*\S)\s*$", ln)
            if m:
                agenda_bullets.append(m.group(1).strip())
        if expected_agenda and agenda_bullets and agenda_bullets == expected_agenda:
            scores["agenda_extracted_exact"] = 1.0
        # If notes had no agenda but summary kept header with no bullets, we could pass;
        # but in this dataset agenda exists; we keep strict check.

    # Decisions extraction check
    if summary_text and notes_text:
        expected_decisions = _parse_notes_decisions(notes_text)
        decisions_section = sections.get("Decisions:", {})
        decisions_lines = decisions_section.get("lines", []) if decisions_section else []
        decisions_bullets = []
        for ln in decisions_lines:
            m = re.match(r"^\s*-\s*(.*\S)\s*$", ln)
            if m:
                decisions_bullets.append(m.group(1).strip())
        ok_decisions = False
        if expected_decisions:
            # Check count matches and each expected decision text appears in any bullet (case-insensitive)
            if len(decisions_bullets) == len(expected_decisions):
                lower_bullets = [b.lower() for b in decisions_bullets]
                ok = True
                for d in expected_decisions:
                    if not any(d.lower() in b for b in lower_bullets):
                        ok = False
                        break
                ok_decisions = ok
        if ok_decisions:
            scores["decisions_extracted"] = 1.0

    # Action items check with normalization for parentheses owner
    if summary_text and notes_text:
        expected_actions = _parse_notes_actions(notes_text)
        actions_section = sections.get("Action Items:", {})
        actions_lines = actions_section.get("lines", []) if actions_section else []
        action_bullets = []
        for ln in actions_lines:
            m = re.match(r"^\s*-\s*(.*\S)\s*$", ln)
            if m:
                action_bullets.append(m.group(1).strip())
        ok_actions = False
        if expected_actions and action_bullets:
            ok = True
            # Build helper to find bullet for an action by owner name presence
            def find_bullet_for_owner(name: str) -> Optional[str]:
                for b in action_bullets:
                    if re.search(rf"\b{name}\b", b):
                        return b
                return None

            for act in expected_actions:
                owner_name = act["owner_name"]
                task = act["task"]
                b = find_bullet_for_owner(owner_name)
                if not b:
                    ok = False
                    break
                # Check that task core phrase appears (case-insensitive); look for a few keywords from task
                # Use main verb phrase (first ~8 words)
                task_phrase = task.lower()
                # Simplify: ensure at least 3-word sequence appears if possible
                words = [w for w in re.split(r"\s+", task_phrase) if w]
                check_phrase = " ".join(words[:5]) if len(words) >= 5 else task_phrase
                if check_phrase and check_phrase not in b.lower():
                    # Try to check presence of two key words from task
                    key_words = words[:3]
                    if not all(kw in b.lower() for kw in key_words if kw):
                        ok = False
                        break
                # Normalization check: if original owner had parentheses, ensure parentheses removed and pattern includes 'Owner -'
                if "(" in act["owner_raw"] and ")" in act["owner_raw"]:
                    if "(" in b or ")" in b:
                        ok = False
                        break
                    # Ensure "Owner - " pattern
                    if not re.search(rf"^-?\s*{re.escape(owner_name)}\s*-\s*", "- " + b):
                        ok = False
                        break
            # Also ensure counts match
            if len(action_bullets) != len(expected_actions):
                ok = False
            ok_actions = ok
        if ok_actions:
            scores["action_items_normalized_and_complete"] = 1.0

    # Discussion highlights present and limited (1-5 bullets)
    if summary_text:
        highlights_section = sections.get("Discussion Highlights:", {})
        hl_lines = highlights_section.get("lines", []) if highlights_section else []
        hl_bullets = [re.match(r"^\s*-\s*(.*\S)\s*$", ln).group(1).strip() for ln in hl_lines if re.match(r"^\s*-\s*(.*\S)\s*$", ln)]
        if 1 <= len(hl_bullets) <= 5:
            scores["discussion_highlights_present_limited"] = 1.0

    # Metrics CSV exists and schema
    metrics_rows = None
    if expected_metrics_csv and expected_metrics_csv.exists():
        rows = _safe_read_csv(expected_metrics_csv)
        if rows is not None:
            # read header fields by opening file again with csv.reader
            try:
                with expected_metrics_csv.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
            except Exception:
                header = None
            required_header = ["period_start", "period_end", "submissions_total", "acceptance_rate", "oa_share_mean", "avg_review_days_mean", "meeting_date"]
            if header == required_header and len(rows) == 1:
                metrics_rows = rows
                scores["metrics_csv_exists_and_schema"] = 1.0

    # Compute expected metrics from input CSV
    expected_snapshot = None
    input_metrics_path = workspace / "input" / "publishing_metrics.csv"
    input_metrics_rows = _safe_read_csv(input_metrics_path) if input_metrics_path.exists() else None
    if input_metrics_rows and latest_date:
        expected_snapshot = _compute_metrics_snapshot(input_metrics_rows, latest_date)

    # Metrics CSV values correct
    if metrics_rows and expected_snapshot:
        row = metrics_rows[0]
        values_ok = (
            row.get("period_start") == expected_snapshot["period_start"] and
            row.get("period_end") == expected_snapshot["period_end"] and
            row.get("submissions_total") == expected_snapshot["submissions_total"] and
            row.get("acceptance_rate") == expected_snapshot["acceptance_rate"] and
            row.get("oa_share_mean") == expected_snapshot["oa_share_mean"] and
            row.get("avg_review_days_mean") == expected_snapshot["avg_review_days_mean"] and
            row.get("meeting_date") == expected_snapshot["meeting_date"]
        )
        if values_ok:
            scores["metrics_csv_values_correct"] = 1.0

    # Metrics snapshot text and keyword counts in summary
    if summary_text and notes_text and expected_snapshot:
        metrics_section = sections.get("Metrics Snapshot:", {})
        metrics_lines = metrics_section.get("lines", []) if metrics_section else []
        metrics_paragraph = " ".join([ln.strip() for ln in metrics_lines]).strip().lower()

        # Check presence of numbers and period range
        numbers_ok = True
        if str(expected_snapshot["submissions_total"]) not in metrics_paragraph:
            numbers_ok = False
        if expected_snapshot["acceptance_rate"] not in metrics_paragraph:
            numbers_ok = False
        if expected_snapshot["oa_share_mean"] not in metrics_paragraph:
            numbers_ok = False
        if expected_snapshot["avg_review_days_mean"] not in metrics_paragraph:
            numbers_ok = False
        if expected_snapshot["period_start"] not in metrics_paragraph or expected_snapshot["period_end"] not in metrics_paragraph:
            numbers_ok = False
        if numbers_ok:
            scores["metrics_snapshot_in_summary_correct"] = 1.0

        # Keyword counts
        notes_lower = notes_text.lower()
        kw_counts = {
            "open access": notes_lower.count("open access"),
            "preprint": notes_lower.count("preprint"),
            "peer review": notes_lower.count("peer review"),
        }

        # Extract reported counts near keywords from metrics paragraph
        def find_count_for_kw(paragraph: str, kw: str) -> Optional[int]:
            # Find the first number following the keyword within 50 chars
            m = re.search(rf"{re.escape(kw)}[^0-9]{{0,50}}(\d+)", paragraph, flags=re.I)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
            return None

        reported_ok = True
        for kw, cnt in kw_counts.items():
            reported = find_count_for_kw(metrics_paragraph, kw)
            if reported is None or reported != cnt:
                reported_ok = False
                break
        if reported_ok:
            scores["keyword_counts_in_summary_correct"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()