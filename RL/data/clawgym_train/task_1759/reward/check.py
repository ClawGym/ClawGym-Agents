import json
import re
import sys
import csv
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_lines(path: Path) -> Optional[List[str]]:
    txt = _read_text(path)
    if txt is None:
        return None
    return txt.splitlines()


def _load_csv_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None, None
    lines = text.splitlines()
    if not lines:
        return None, None
    header_line = lines[0]
    header = [h.strip() for h in header_line.split(",")]
    try:
        # Use csv.DictReader for rows
        rows = []
        reader = csv.DictReader(lines)
        for row in reader:
            rows.append({k: (v if v is not None else "") for k, v in row.items()})
        return header, rows
    except Exception:
        return None, None


def _iso8601_regex() -> re.Pattern:
    # Basic ISO8601 datetime: YYYY-MM-DDTHH:MM:SS(.sss)?(Z|±HH:MM)?
    return re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b")


def _parse_action_items_from_notes(notes_dir: Path) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    if not notes_dir.exists():
        return items
    pattern = re.compile(
        r'^\s*-\s*\[\s*\]\s*Owner:\s*(?P<owner>[^;]+);\s*Task:\s*(?P<task>[^;]+);\s*Due:\s*(?P<due>\d{4}-\d{2}-\d{2});\s*Priority:\s*(?P<priority>High|Medium|Low)\s*$'
    )
    for md in sorted(notes_dir.glob("*.md")):
        content = _read_lines(md)
        if content is None:
            continue
        for line in content:
            m = pattern.match(line)
            if m:
                d = m.groupdict()
                items.append(
                    {
                        "source_file": md.name,
                        "owner": d["owner"].strip(),
                        "task": d["task"].strip(),
                        "due": d["due"].strip(),
                        "priority": d["priority"].strip(),
                    }
                )
    return items


def _count_lines_starting_with_keywords(text: str, keyword: str) -> int:
    count = 0
    for line in text.splitlines():
        if re.match(r"^\s*" + re.escape(keyword) + r"\b", line):
            count += 1
    return count


def _load_glossary(glossary_path: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    try:
        with glossary_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                acr = (row.get("acronym") or "").strip()
                exp = (row.get("expansion") or "").strip()
                if acr and exp:
                    mapping[acr] = exp
    except Exception:
        return {}
    return mapping


def _load_idioms(idioms_path: Path) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    try:
        with idioms_path.open("r", encoding="utf-8") as f:
            # TSV with header idiom <tab> replacement
            reader = csv.reader(f, delimiter="\t")
            rows = list(reader)
            if not rows:
                return []
            # Skip header
            for row in rows[1:]:
                if len(row) >= 2:
                    idiom = (row[0] or "").strip()
                    repl = (row[1] or "").strip()
                    if idiom and repl:
                        pairs.append((idiom, repl))
    except Exception:
        return []
    return pairs


def _find_all_occurrences(haystack: str, needle: str) -> List[int]:
    # Return start indices of all occurrences of needle in haystack
    if not needle:
        return []
    indices: List[int] = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            break
        indices.append(idx)
        start = idx + 1
    return indices


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "action_items_csv_header_ok": 0.0,
        "action_items_row_count_matches_note_items": 0.0,
        "action_items_csv_content_match": 0.0,
        "consolidated_top_line_matches_total": 0.0,
        "consolidated_sections_present_for_each_note": 0.0,
        "run_log_has_command": 0.0,
        "run_log_has_iso8601_timestamp": 0.0,
        "run_log_has_total_count_and_matches": 0.0,
        "talking_points_headings_preserved": 0.0,
        "talking_points_bullet_positions_preserved": 0.0,
        "talking_points_idioms_replaced": 0.0,
        "talking_points_acronyms_first_expanded": 0.0,
    }

    # Paths
    notes_dir = workspace / "input" / "notes"
    action_csv = workspace / "output" / "Action_Items.csv"
    consolidated_md = workspace / "output" / "Consolidated_Notes.md"
    run_log = workspace / "output" / "run_log.txt"
    tp_input = workspace / "input" / "TalkingPoints.md"
    tp_output = workspace / "output" / "TalkingPoints_Clean.md"
    glossary_path = workspace / "input" / "glossary.csv"
    idioms_path = workspace / "input" / "idioms.tsv"

    # Compute expected action items from input notes
    expected_items = _parse_action_items_from_notes(notes_dir)
    expected_n = len(expected_items)

    # Load CSV
    header, rows = _load_csv_rows(action_csv)
    if header is not None:
        required_header = ["source_file", "owner", "task", "due", "priority"]
        if header == required_header:
            scores["action_items_csv_header_ok"] = 1.0

    # Row count match
    if rows is not None:
        if len(rows) == expected_n:
            scores["action_items_row_count_matches_note_items"] = 1.0

    # Content match
    if rows is not None:
        # Normalize rows to tuples for comparison
        def row_to_tuple(r: Dict[str, str]) -> Tuple[str, str, str, str, str]:
            return (
                (r.get("source_file") or "").strip(),
                (r.get("owner") or "").strip(),
                (r.get("task") or "").strip(),
                (r.get("due") or "").strip(),
                (r.get("priority") or "").strip(),
            )

        actual_set = set(row_to_tuple(r) for r in rows)
        expected_set = set(
            (i["source_file"], i["owner"], i["task"], i["due"], i["priority"]) for i in expected_items
        )
        if actual_set == expected_set and len(actual_set) == len(rows) == expected_n:
            scores["action_items_csv_content_match"] = 1.0

    # Consolidated notes checks
    consolidated_text = _read_text(consolidated_md)
    if consolidated_text is not None:
        # First line check exact
        consolidated_lines = consolidated_text.splitlines()
        first_line = consolidated_lines[0] if consolidated_lines else ""
        expected_first_line = f"Total action items aggregated: {expected_n}"
        if first_line.strip() == expected_first_line:
            scores["consolidated_top_line_matches_total"] = 1.0

        # Sections presence: for each note expected, we expect at least that many occurrences of the subsections
        participants_count = _count_lines_starting_with_keywords(consolidated_text, "Participants")
        decisions_count = _count_lines_starting_with_keywords(consolidated_text, "Decisions")
        openq_count = _count_lines_starting_with_keywords(consolidated_text, "Open Questions")
        action_items_count = _count_lines_starting_with_keywords(consolidated_text, "Action Items")
        if (
            participants_count >= len(list(notes_dir.glob("*.md")))
            and decisions_count >= len(list(notes_dir.glob("*.md")))
            and openq_count >= len(list(notes_dir.glob("*.md")))
            and action_items_count >= len(list(notes_dir.glob("*.md")))
        ):
            scores["consolidated_sections_present_for_each_note"] = 1.0

    # Run log checks
    run_log_text = _read_text(run_log)
    if run_log_text is not None:
        # Command presence: allow python or python3 etc, and exact script and args
        command_pattern = re.compile(
            r"\bpython(?:\d(?:\.\d)?)?\s+tools/aggregate_actions\.py\s+input/notes\s+output\b"
        )
        if command_pattern.search(run_log_text):
            scores["run_log_has_command"] = 1.0

        # ISO 8601 timestamp
        if _iso8601_regex().search(run_log_text):
            scores["run_log_has_iso8601_timestamp"] = 1.0

        # Total count N presence: search line with 'total' and matching number
        count_ok = False
        for line in run_log_text.splitlines():
            if re.search(r"total", line, flags=re.IGNORECASE):
                nums = re.findall(r"\d+", line)
                for num in nums:
                    try:
                        if int(num) == expected_n:
                            count_ok = True
                            break
                    except Exception:
                        continue
            if count_ok:
                break
        if count_ok:
            scores["run_log_has_total_count_and_matches"] = 1.0

    # Talking points checks
    tp_in_text = _read_text(tp_input)
    tp_out_text = _read_text(tp_output)

    # Headings preserved
    if tp_in_text is not None and tp_out_text is not None:
        in_headings = [ln for ln in tp_in_text.splitlines() if ln.strip().startswith("#")]
        out_headings = [ln for ln in tp_out_text.splitlines() if ln.strip().startswith("#")]
        if in_headings == out_headings and len(in_headings) > 0:
            scores["talking_points_headings_preserved"] = 1.0

        # Bullet positions preserved: indices of lines starting with "- "
        in_lines = tp_in_text.splitlines()
        out_lines = tp_out_text.splitlines()
        in_bullets_idx = [i for i, ln in enumerate(in_lines) if ln.strip().startswith("- ")]
        out_bullets_idx = [i for i, ln in enumerate(out_lines) if ln.strip().startswith("- ")]
        if in_bullets_idx == out_bullets_idx and len(in_bullets_idx) > 0:
            scores["talking_points_bullet_positions_preserved"] = 1.0

    # Idioms replaced
    if tp_in_text is not None and tp_out_text is not None:
        idioms = _load_idioms(idioms_path)
        if idioms:
            all_ok = True
            for idiom, repl in idioms:
                # Check if idiom appears in original (case-insensitive)
                if re.search(re.escape(idiom), tp_in_text, flags=re.IGNORECASE):
                    # In cleaned, idiom should not appear
                    if re.search(re.escape(idiom), tp_out_text, flags=re.IGNORECASE):
                        all_ok = False
                        break
                    # Replacement should appear
                    if not re.search(re.escape(repl), tp_out_text, flags=re.IGNORECASE):
                        all_ok = False
                        break
            if all_ok:
                scores["talking_points_idioms_replaced"] = 1.0

    # Acronyms expansion checks
    if tp_in_text is not None and tp_out_text is not None:
        glossary = _load_glossary(glossary_path)
        if glossary:
            all_ok = True
            for acr, exp in glossary.items():
                # Check only if acronym appears in the input
                if re.search(re.escape(acr), tp_in_text):
                    # In output, ensure first occurrence of acronym is part of "Expansion (ACR)"
                    # Occurrences of acronym as substring positions
                    acr_positions = _find_all_occurrences(tp_out_text, acr)
                    if not acr_positions:
                        all_ok = False
                        break
                    exp_phrase = f"{exp} ({acr})"
                    exp_positions = _find_all_occurrences(tp_out_text, exp_phrase)
                    # Must appear exactly once
                    if len(exp_positions) != 1:
                        all_ok = False
                        break
                    first_acr_pos = min(acr_positions)
                    exp_pos = exp_positions[0]
                    # Verify that the first acronym occurrence is inside the expansion phrase
                    # Index of the acronym within the phrase is exp_pos + len(exp) + 2
                    expected_first_acr_pos = exp_pos + len(exp) + 2
                    if first_acr_pos != expected_first_acr_pos:
                        all_ok = False
                        break
            if all_ok:
                scores["talking_points_acronyms_first_expanded"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()