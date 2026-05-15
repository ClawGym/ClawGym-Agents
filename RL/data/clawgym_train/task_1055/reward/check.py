import json
import sys
import csv
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional


RE_FILENAME = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<context>.+)\.md$")
RE_TRAILING_PAREN = re.compile(r"\((.*?)\)\s*$", re.DOTALL)


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def normalize_output(s: str) -> str:
    s_norm = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = s_norm.split("\n")
    lines = [ln.rstrip() for ln in lines]
    out = "\n".join(lines).strip("\n")
    if s_norm.endswith("\n"):
        out += "\n"
    return out


def parse_metadata_from_parens(s: str) -> Tuple[str, str]:
    owner = ""
    due = ""
    m = RE_TRAILING_PAREN.search(s)
    if not m:
        return owner, due
    inner = m.group(1)
    parts = [p.strip() for p in inner.split(",")]
    for p in parts:
        if ":" not in p:
            continue
        key, val = p.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        if key == "owner":
            if val.lower() == "tbd" or val == "":
                owner = ""
            else:
                owner = val
        elif key == "due":
            due = val
    return owner, due


def strip_marker_and_metadata(line: str) -> Tuple[str, str, str]:
    content = line.strip()
    marker_removed = content
    if content.startswith("- [ ]"):
        marker_removed = content[len("- [ ]"):].lstrip()
    elif content.startswith("- [x]"):
        marker_removed = content[len("- [x]"):].lstrip()
    elif content.startswith("ACTION:"):
        marker_removed = content[len("ACTION:"):].lstrip()
    elif content.startswith("TODO:"):
        marker_removed = content[len("TODO:"):].lstrip()
    owner, due = parse_metadata_from_parens(marker_removed)
    task_text = RE_TRAILING_PAREN.sub("", marker_removed).rstrip()
    return task_text, owner, due


def extract_expected_from_notes(workspace: Path) -> Tuple[List[Dict[str, str]], Dict[str, int], List[Path]]:
    notes_dir = workspace / "notes"
    rows: List[Dict[str, str]] = []
    counts: Dict[str, int] = {}
    files_processed: List[Path] = []
    if not notes_dir.exists():
        return rows, counts, files_processed

    md_files = sorted([p for p in notes_dir.glob("*.md") if p.is_file()])
    markers = ("- [ ]", "- [x]", "ACTION:", "TODO:")
    for path in md_files:
        name = path.name
        files_processed.append(path)
        counts[name] = 0
        text = read_text(path) or ""
        lines = text.splitlines()
        m = RE_FILENAME.match(name)
        meeting_date = ""
        context = ""
        if m:
            meeting_date = m.group("date")
            context = m.group("context")
        for ln in lines:
            ln_lstrip = ln.lstrip()
            if any(ln_lstrip.startswith(mrk) for mrk in markers):
                counts[name] += 1
                status = "open"
                if ln_lstrip.startswith("- [x]"):
                    status = "done"
                task_text, owner, due = strip_marker_and_metadata(ln_lstrip)
                row = {
                    "meeting_date": meeting_date,
                    "context": context,
                    "task": task_text,
                    "owner": owner,
                    "due_date": due,
                    "status": status,
                }
                rows.append(row)
    return rows, counts, files_processed


def rows_to_tuple_set(rows: List[Dict[str, str]]) -> set:
    key_order = ["meeting_date", "context", "task", "owner", "due_date", "status"]
    return {tuple((r.get(k) or "") for k in key_order) for r in rows}


def parse_meetings_index_counts(index_text: str, filenames: List[str]) -> Dict[str, Optional[int]]:
    result: Dict[str, Optional[int]] = {}
    lines = index_text.splitlines()
    for fn in filenames:
        found_count: Optional[int] = None
        pattern = re.compile(rf".*{re.escape(fn)}.*?(\d+).*")
        for ln in lines:
            if fn in ln:
                m = pattern.match(ln)
                if m:
                    try:
                        found_count = int(m.group(1))
                    except Exception:
                        found_count = None
        result[fn] = found_count
    return result


def find_bullet_lines(text: str) -> List[str]:
    bullets = []
    for ln in text.splitlines():
        sl = ln.lstrip()
        if sl.startswith("- ") or sl.startswith("* "):
            bullets.append(sl)
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "csv_file_exists_and_header": 0.0,
        "csv_row_count_correct": 0.0,
        "csv_rows_match_expected": 0.0,
        "meetings_index_counts_match": 0.0,
        "validation_report_exists": 0.0,
        "validation_report_matches_rerun": 0.0,
        "next_steps_covers_open_items": 0.0,
        "next_steps_validation_notes_section": 0.0,
    }

    expected_rows, expected_counts, files_processed = extract_expected_from_notes(workspace)
    expected_row_count = len(expected_rows)
    expected_filenames = [p.name for p in files_processed]

    csv_path = workspace / "out" / "action_items.csv"
    header, rows = load_csv(csv_path)
    required_header = ["meeting_date", "context", "task", "owner", "due_date", "status"]

    if header is not None:
        if header == required_header:
            scores["csv_file_exists_and_header"] = 1.0
        else:
            scores["csv_file_exists_and_header"] = 0.0
    else:
        scores["csv_file_exists_and_header"] = 0.0

    if header == required_header and rows is not None and expected_row_count > 0:
        scores["csv_row_count_correct"] = 1.0 if len(rows) == expected_row_count else 0.0
    else:
        scores["csv_row_count_correct"] = 0.0

    if header == required_header and rows is not None and expected_row_count > 0:
        got_set = rows_to_tuple_set(rows)
        exp_set = rows_to_tuple_set(expected_rows)
        scores["csv_rows_match_expected"] = 1.0 if got_set == exp_set else 0.0
    else:
        scores["csv_rows_match_expected"] = 0.0

    meetings_index_path = workspace / "out" / "meetings_index.md"
    idx_text = read_text(meetings_index_path)
    if idx_text is not None and expected_counts and expected_filenames:
        extracted = parse_meetings_index_counts(idx_text, expected_filenames)
        ok = True
        for fn in expected_filenames:
            exp = expected_counts.get(fn, None)
            got = extracted.get(fn, None)
            if got is None or exp is None or int(got) != int(exp):
                ok = False
                break
        scores["meetings_index_counts_match"] = 1.0 if ok else 0.0
    else:
        scores["meetings_index_counts_match"] = 0.0

    validation_report_path = workspace / "out" / "validation_report.txt"
    val_text = read_text(validation_report_path)
    if val_text is not None:
        scores["validation_report_exists"] = 1.0
    else:
        scores["validation_report_exists"] = 0.0

    if csv_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, "tools/check_actions.py", str(csv_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
            tool_out = proc.stdout
            if val_text is not None:
                scores["validation_report_matches_rerun"] = 1.0 if normalize_output(tool_out) == normalize_output(val_text) else 0.0
            else:
                scores["validation_report_matches_rerun"] = 0.0
        except Exception:
            scores["validation_report_matches_rerun"] = 0.0
    else:
        scores["validation_report_matches_rerun"] = 0.0

    next_steps_path = workspace / "out" / "next_steps.md"
    next_text = read_text(next_steps_path)
    if next_text is not None and header == required_header and rows is not None:
        open_rows = [r for r in rows if (r.get("status") or "").strip().lower() == "open"]
        bullets = find_bullet_lines(next_text)
        owners = set((r.get("owner") or "").strip() for r in open_rows)
        display_owners = set(o if o else "Unassigned" for o in owners)
        owners_present = all(any(o in line for line in next_text.splitlines()) for o in display_owners)

        def bullet_has_substrings(bul: str, subs: List[str]) -> bool:
            return all(s in bul for s in subs)

        all_items_listed = True
        for r in open_rows:
            md = (r.get("meeting_date") or "").strip()
            ctx = (r.get("context") or "").strip()
            task = (r.get("task") or "").strip()
            due = (r.get("due_date") or "").strip()
            substrings = [md, ctx, task]
            if due:
                substrings.append(due)
            found = any(bullet_has_substrings(b, substrings) for b in bullets)
            if not found:
                all_items_listed = False
                break

        scores["next_steps_covers_open_items"] = 1.0 if (owners_present and all_items_listed) else 0.0
    else:
        scores["next_steps_covers_open_items"] = 0.0

    if next_text is not None:
        idx = next_text.lower().find("validation notes")
        if idx != -1:
            after = next_text[idx:]
            after_lines = after.splitlines()
            if after_lines:
                content_lines = after_lines[1:]
                content_text = "\n".join(content_lines).strip()
            else:
                content_text = ""
            sentences = re.findall(r"[^\s].*?[\.!?](?:\s|$)", content_text, flags=re.DOTALL)
            count = len(sentences)
            mentions = re.search(r"(error|warning|valid|invalid|checker|due_date|owner|blank|tbd)", content_text, flags=re.IGNORECASE) is not None
            if 3 <= count <= 5 and mentions:
                scores["next_steps_validation_notes_section"] = 1.0
            else:
                scores["next_steps_validation_notes_section"] = 0.0
        else:
            scores["next_steps_validation_notes_section"] = 0.0
    else:
        scores["next_steps_validation_notes_section"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()