import json
import sys
import subprocess
import re
import csv
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory


OPEN_ITEM_RE = re.compile(r"^\s*-\s\[ \]\s")
OWNER_DUE_RE = re.compile(r"^\s*-\s\[ \]\s(.+?)\s*\(Owner:\s*([^;\)]+)\s*;\s*Due:\s*(\d{4}-\d{2}-\d{2})\)\s*$")
ACTION_MD_ITEM_RE = re.compile(r"^-\s\[\s\]\s(.+?)\s+\(Due:\s(\d{4}-\d{2}-\d{2})\)\s+—\s+Source:\s+([^\s)]+)\s*$")


def safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_read_lines(path: Path):
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None


def safe_load_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as fp:
            reader = csv.DictReader(fp)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def find_md_files(notes_dir: Path):
    if not notes_dir.is_dir():
        return []
    md_files = []
    for p in notes_dir.rglob("*.md"):
        if p.is_file():
            md_files.append(p)
    md_files.sort()
    return md_files


def parse_note_like_indexer(path: Path):
    lines = safe_read_lines(path)
    if lines is None:
        return None
    title = None
    date_str = None
    tags = []

    # First non-empty must be level-1 title
    for raw in lines:
        s = raw.strip()
        if s == "":
            continue
        if s.startswith("# "):
            title = s[2:].strip()
        else:
            return None
        break

    for raw in lines:
        s = raw.strip()
        if s.startswith("Date:"):
            value = s[len("Date:"):].strip()
            try:
                datetime.strptime(value, "%Y-%m-%d")
                date_str = value
            except Exception:
                return None
        elif s.startswith("Tags:"):
            value = s[len("Tags:"):].strip()
            tags = [t.strip() for t in value.split(",") if t.strip()]

    if title is None:
        return None
    if date_str is None:
        return None

    open_items = 0
    for raw in lines:
        if OPEN_ITEM_RE.search(raw):
            open_items += 1

    return {
        "file": path.name,
        "date": date_str,
        "title": title,
        "tags": ";".join(tags),
        "open_action_items": str(open_items),
    }


def extract_open_items_from_notes(md_paths):
    items = []
    all_ok = True
    for p in md_paths:
        lines = safe_read_lines(p)
        if lines is None:
            all_ok = False
            continue
        for raw in lines:
            if OPEN_ITEM_RE.search(raw):
                m = OWNER_DUE_RE.match(raw)
                if not m:
                    # Found an open item that doesn't match expected owner/due format
                    all_ok = False
                    continue
                desc = m.group(1).strip()
                owner = m.group(2).strip()
                due = m.group(3).strip()
                items.append({
                    "owner": owner,
                    "desc": desc,
                    "due": due,
                    "file": p.name
                })
    return items, all_ok


def run_indexer_in_temp(workspace: Path):
    script = workspace / "input" / "scripts" / "build_summary.py"
    src = workspace / "input" / "notes"
    if not script.is_file() or not src.is_dir():
        return False, "", "", None
    with TemporaryDirectory() as td:
        out_path = Path(td) / "out.csv"
        try:
            result = subprocess.run(
                [sys.executable, str(script), "--src", str(src), "--out", str(out_path)],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=30
            )
        except Exception as e:
            return False, "", f"{e}", None
        ok = (result.returncode == 0) and ("ERROR" not in (result.stderr or ""))
        return ok, result.stdout or "", result.stderr or "", out_path if out_path.exists() else None


def parse_action_items_md(path: Path):
    lines = safe_read_lines(path)
    if lines is None:
        return {
            "title_ok": False,
            "owners_order": [],
            "owner_items": {},
            "has_counts_section": False,
            "counts_by_note": {},
            "troubleshooting_present": False,
            "troubleshooting_lines": []
        }
    # Check top heading
    title_ok = False
    for raw in lines:
        if raw.strip() == "":
            continue
        if raw.strip() == "# Next Meeting Action Items":
            title_ok = True
        break

    owners_order = []
    owner_items = {}
    has_counts_section = False
    counts_by_note = {}
    troubleshooting_present = False
    troubleshooting_lines = []

    mode = None
    current_owner = None

    for raw in lines:
        s = raw.strip()
        if s.startswith("## "):
            if s.startswith("## Owner: "):
                current_owner = s[len("## Owner: "):].strip()
                if current_owner not in owner_items:
                    owner_items[current_owner] = []
                    owners_order.append(current_owner)
                mode = "owner"
            elif s == "## Action Item Counts by Note":
                mode = "counts"
                current_owner = None
                has_counts_section = True
            elif s == "## Troubleshooting Notes":
                mode = "troubleshooting"
                current_owner = None
                troubleshooting_present = True
            else:
                mode = None
                current_owner = None
            continue

        if mode == "owner" and current_owner:
            if s.startswith("- [ ] "):
                m = ACTION_MD_ITEM_RE.match(s)
                if m:
                    desc = m.group(1).strip()
                    due = m.group(2).strip()
                    src_file = m.group(3).strip()
                    owner_items[current_owner].append({
                        "desc": desc,
                        "due": due,
                        "file": src_file
                    })
                else:
                    # Badly formatted item line under owner
                    owner_items.setdefault(current_owner, [])
                    owner_items[current_owner].append({
                        "desc": None,
                        "due": None,
                        "file": None
                    })
        elif mode == "counts":
            if s == "":
                continue
            cm = re.match(r"^([^\s:]+\.md):\s+(\d+)\s*$", s)
            if cm:
                counts_by_note[cm.group(1)] = int(cm.group(2))
        elif mode == "troubleshooting":
            troubleshooting_lines.append(raw)

    return {
        "title_ok": title_ok,
        "owners_order": owners_order,
        "owner_items": owner_items,
        "has_counts_section": has_counts_section,
        "counts_by_note": counts_by_note,
        "troubleshooting_present": troubleshooting_present,
        "troubleshooting_lines": troubleshooting_lines
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "indexer_runs_without_errors": 0.0,
        "notes_summary_csv_present_and_header": 0.0,
        "notes_summary_csv_matches_parsed_notes": 0.0,
        "action_items_md_heading": 0.0,
        "action_items_grouping_and_items_correct": 0.0,
        "action_item_counts_section_matches": 0.0,
        "troubleshooting_section_present": 0.0,
        "troubleshooting_includes_errors_and_resolutions": 0.0,
    }

    # 1) Check indexer runs cleanly with temp output (no workspace modifications)
    ok, out_stdout, out_stderr, _ = run_indexer_in_temp(workspace)
    if ok:
        scores["indexer_runs_without_errors"] = 1.0
    else:
        scores["indexer_runs_without_errors"] = 0.0

    # 2) Validate workspace/notes_summary.csv existence and header
    summary_csv_path = workspace / "workspace" / "notes_summary.csv"
    header, rows = safe_load_csv(summary_csv_path)
    expected_header = ['file', 'date', 'title', 'tags', 'open_action_items']
    if header is not None and rows is not None and header == expected_header and len(rows) >= 1:
        scores["notes_summary_csv_present_and_header"] = 1.0

    # 3) Compare CSV rows to parsed notes content
    notes_dir = workspace / "input" / "notes"
    md_files = find_md_files(notes_dir)
    expected_recs = []
    parse_all_ok = True
    for p in md_files:
        rec = parse_note_like_indexer(p)
        if rec is None:
            parse_all_ok = False
            break
        expected_recs.append(rec)
    if parse_all_ok and header == expected_header and rows is not None:
        # Build mapping by file
        expected_by_file = {r['file']: r for r in expected_recs}
        actual_by_file = {r.get('file', ''): r for r in rows if 'file' in r}
        if set(expected_by_file.keys()) == set(actual_by_file.keys()) and len(rows) == len(expected_recs):
            match_all = True
            for f, exp in expected_by_file.items():
                act = actual_by_file.get(f)
                if act is None:
                    match_all = False
                    break
                # Compare all fields exactly
                for k in expected_header:
                    if k not in act:
                        match_all = False
                        break
                    if str(act[k]) != str(exp[k]):
                        match_all = False
                        break
                if not match_all:
                    break
            if match_all:
                scores["notes_summary_csv_matches_parsed_notes"] = 1.0

    # 4) Validate next_meeting_action_items.md
    actions_md_path = workspace / "workspace" / "next_meeting_action_items.md"
    action_parse = parse_action_items_md(actions_md_path)

    # Heading check
    if action_parse["title_ok"]:
        scores["action_items_md_heading"] = 1.0

    # Build expected open items from notes
    open_items, open_items_format_ok = extract_open_items_from_notes(md_files)
    # Owners expected
    expected_owners = sorted({it["owner"] for it in open_items}, key=lambda s: s.lower()) if open_items else []
    owners_order = action_parse["owners_order"]
    owner_items = action_parse["owner_items"]

    grouping_ok = False
    items_ok = False
    if open_items and open_items_format_ok and owners_order and owner_items:
        # Check owners set and order
        owners_set_ok = set(owners_order) == set(expected_owners)
        order_ok = owners_order == expected_owners
        grouping_ok = owners_set_ok and order_ok

        # Build expected set of items (owner, desc, due, file)
        expected_item_set = set((it["owner"], it["desc"], it["due"], it["file"]) for it in open_items)
        # Build actual set from actions md
        actual_item_set = set()
        actual_items_well_formed = True
        for owner, items in owner_items.items():
            for it in items:
                if it["desc"] is None or it["due"] is None or it["file"] is None:
                    actual_items_well_formed = False
                    continue
                actual_item_set.add((owner, it["desc"], it["due"], it["file"]))

        items_ok = (expected_item_set == actual_item_set) and actual_items_well_formed

    if grouping_ok and items_ok:
        scores["action_items_grouping_and_items_correct"] = 1.0

    # 5) Validate Action Item Counts by Note section and alignment with CSV and notes
    counts_section_ok = False
    if action_parse["has_counts_section"]:
        counts_in_md = action_parse["counts_by_note"]
        # Compute expected counts from notes
        expected_counts = {}
        for it in open_items:
            expected_counts[it["file"]] = expected_counts.get(it["file"], 0) + 1
        # Load counts from CSV
        csv_counts = {}
        if rows is not None and header == expected_header:
            try:
                for r in rows:
                    f = r["file"]
                    c = int(r["open_action_items"])
                    csv_counts[f] = c
            except Exception:
                csv_counts = {}
        # Compare all three (keys and values)
        if counts_in_md and expected_counts and csv_counts:
            counts_section_ok = (counts_in_md == expected_counts == csv_counts)
    if counts_section_ok:
        scores["action_item_counts_section_matches"] = 1.0

    # 6) Troubleshooting Notes section presence and content
    if action_parse["troubleshooting_present"]:
        scores["troubleshooting_section_present"] = 1.0
        # Look for at least one line with "ERROR" and at least one line mentioning resolution
        has_error_line = any("ERROR" in (ln or "") for ln in action_parse["troubleshooting_lines"])
        resolution_keywords = ("resolve", "resolved", "fix", "fixed", "correct", "corrected", "change", "changed")
        has_resolution_note = any(
            any(k in (ln or "").lower() for k in resolution_keywords) for ln in action_parse["troubleshooting_lines"]
        )
        if has_error_line and has_resolution_note:
            scores["troubleshooting_includes_errors_and_resolutions"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()