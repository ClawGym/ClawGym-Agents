import json
import sys
import csv
import re
from pathlib import Path


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None


def _list_yaml_files(events_dir: Path):
    try:
        if not events_dir.exists():
            return []
        return sorted([p for p in events_dir.glob("*.yaml") if p.is_file()])
    except Exception:
        return []


def _parse_inline_list(s: str):
    items = []
    inner = s.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    parts = [p.strip() for p in inner.split(",")]
    for p in parts:
        if len(p) >= 2 and ((p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'"))):
            p = p[1:-1]
        if p != "":
            items.append(p)
    return items


def _parse_event_yaml(path: Path):
    text = _read_text(path)
    if text is None:
        return None
    m_date = re.search(r'(?m)^\s*date:\s*(?:"([^"]+)"|\'([^\']+)\'|([^\n#]+))', text)
    m_title = re.search(r'(?m)^\s*title:\s*(?:"([^"]+)"|\'([^\']+)\'|([^\n#]+))', text)
    m_summary = re.search(r'(?m)^\s*summary:\s*(?:"([^"]*)"|\'([^\']*)\'|([^\n#]*))', text)
    m_tags_line = re.search(r'(?m)^\s*tags:\s*(.+)$', text)
    if not (m_date and m_title and m_summary and m_tags_line):
        return None

    def _pick(grp):
        for g in grp.groups():
            if g is not None:
                return g.strip()
        return None

    date = _pick(m_date)
    title = _pick(m_title)
    summary = _pick(m_summary)
    tags_raw = m_tags_line.group(1).strip()
    tags_list = []
    if tags_raw.startswith("["):
        tags_list = _parse_inline_list(tags_raw)
    else:
        if (tags_raw.startswith('"') and tags_raw.endswith('"')) or (tags_raw.startswith("'") and tags_raw.endswith("'")):
            tags_raw = tags_raw[1:-1]
        tags_list = [t.strip() for t in tags_raw.split(",") if t.strip() != ""]
    return {"date": date, "title": title, "summary": summary, "tags": tags_list}


def _compute_expected_from_events_dir(events_dir: Path, max_len: int = 160):
    files = _list_yaml_files(events_dir)
    expected = {}
    for p in files:
        ev = _parse_event_yaml(p)
        if ev is None:
            return None
        date = ev.get("date")
        title = ev.get("title")
        summary = ev.get("summary") or ""
        tags = ev.get("tags") or []
        tags_str = ";".join([str(t).strip() for t in tags])
        if len(summary) > max_len:
            summary = summary[:max_len].rstrip()
        expected[title] = (date, title, tags_str, summary)
    return expected


def _check_tags_format(tags_str: str):
    if "," in tags_str:
        return False
    parts = [p for p in tags_str.split(";")]
    if any(p.strip() != p for p in parts):
        return False
    if any(p == "" for p in parts):
        return False
    return True


def _words_count(s: str):
    return len([w for w in s.strip().split() if w])


def _extract_subject_blocks(text: str):
    lines = text.splitlines()
    blocks = []
    current_subject = None
    current_body_lines = []
    for line in lines:
        if line.startswith("Subject: "):
            if current_subject is not None:
                blocks.append((current_subject, "\n".join(current_body_lines).strip()))
                current_body_lines = []
            current_subject = line.strip()
        else:
            if current_subject is not None:
                if line.strip() == "---":
                    continue
                current_body_lines.append(line)
    if current_subject is not None:
        blocks.append((current_subject, "\n".join(current_body_lines).strip()))
    return blocks


def _log_contains_explanations(log_text: str):
    lt = log_text.lower()
    cause1_tokens = ["config", "settings.yaml", "notes_dir", "notes directory", "path", "directory"]
    fix_tokens = ["fix", "fixed", "update", "updated", "change", "changed", "corrected", "adjust", "adjusted", "edit", "edited"]
    tags_tokens = ["tags"]
    type_tokens = ["string", "strings", "list"]
    fix2_tokens = fix_tokens + ["split", "parse", "convert", "handle", "handled"]
    cause1 = any(t in lt for t in cause1_tokens)
    fix1 = any(t in lt for t in fix_tokens)
    cause2 = all(any(t in lt for t in group) for group in [tags_tokens, type_tokens])
    fix2 = any(t in lt for t in fix2_tokens)
    return (cause1 and fix1) and (cause2 and fix2)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "events_csv_exists_and_readable": 0.0,
        "events_csv_header_valid": 0.0,
        "events_csv_row_count_correct": 0.0,
        "events_csv_tags_format": 0.0,
        "events_csv_summaries_max_len": 0.0,
        "events_csv_content_matches_expected": 0.0,
        "run_log_exists": 0.0,
        "run_log_contains_initial_error": 0.0,
        "run_log_contains_second_error": 0.0,
        "run_log_contains_success_line": 0.0,
        "run_log_explanations_present": 0.0,
        "drafts_rephrased_exists": 0.0,
        "drafts_subjects_preserved": 0.0,
        "drafts_bodies_word_count": 0.0,
        "drafts_avoid_banned_words": 0.0,
        "drafts_three_blocks_and_nonempty_bodies": 0.0,
    }

    events_dir = workspace / "workspace" / "input" / "events"
    out_csv_path = workspace / "workspace" / "output" / "events_index.csv"
    run_log_path = workspace / "workspace" / "output" / "run_log.txt"
    drafts_out_path = workspace / "workspace" / "output" / "rephrased_messages.md"

    expected_subjects = [
        "Subject: PAL Open Gym Night — June 5, 6:00 PM",
        "Subject: Youth Mentoring Kickoff — May 21, 3:30 PM",
        "Subject: Library Career Q&A — May 28, 4:00 PM",
    ]

    expected_events = _compute_expected_from_events_dir(events_dir, max_len=160)

    header, data = _read_csv_rows(out_csv_path)
    if header is not None and data is not None:
        scores["events_csv_exists_and_readable"] = 1.0
        if header == ["date", "title", "tags", "summary"]:
            scores["events_csv_header_valid"] = 1.0
        if expected_events is not None:
            if len(data) == len(expected_events):
                scores["events_csv_row_count_correct"] = 1.0
        tags_ok = True
        summaries_ok = True
        for row in data:
            if len(row) != 4:
                tags_ok = False
                summaries_ok = False
                break
            _, _, tags_str, summary = row
            if not _check_tags_format(tags_str):
                tags_ok = False
            if len(summary) > 160:
                summaries_ok = False
        scores["events_csv_tags_format"] = 1.0 if tags_ok else 0.0
        scores["events_csv_summaries_max_len"] = 1.0 if summaries_ok else 0.0

        if expected_events is not None and len(expected_events) > 0:
            csv_by_title = {}
            content_match = True
            for row in data:
                if len(row) != 4:
                    content_match = False
                    break
                d, t, tags_str, summ = row
                csv_by_title[t] = (d, t, tags_str, summ)
            for title, expected_row in expected_events.items():
                csv_row = csv_by_title.get(title)
                if csv_row is None:
                    content_match = False
                    break
                if csv_row != expected_row:
                    content_match = False
                    break
            if content_match and set(csv_by_title.keys()) != set(expected_events.keys()):
                content_match = False
            scores["events_csv_content_matches_expected"] = 1.0 if content_match else 0.0

    run_log_text = _read_text(run_log_path)
    if run_log_text is not None:
        scores["run_log_exists"] = 1.0
        if "Notes directory not found:" in run_log_text:
            scores["run_log_contains_initial_error"] = 1.0
        if "tags must be a list" in run_log_text:
            scores["run_log_contains_second_error"] = 1.0
        expected_count = 0
        if expected_events is not None:
            expected_count = len(expected_events)
        if expected_count > 0:
            success_line = f"Processed {expected_count} events."
            if success_line in run_log_text:
                scores["run_log_contains_success_line"] = 1.0
        scores["run_log_explanations_present"] = 1.0 if _log_contains_explanations(run_log_text) else 0.0

    drafts_text = _read_text(drafts_out_path)
    if drafts_text is not None:
        scores["drafts_rephrased_exists"] = 1.0
        blocks = _extract_subject_blocks(drafts_text)
        subjects_ok = all(s in drafts_text for s in expected_subjects)
        scores["drafts_subjects_preserved"] = 1.0 if subjects_ok else 0.0
        blocks_ok = False
        nonempty_bodies = True
        if len(blocks) == 3:
            subj_set = set(subj for subj, _ in blocks)
            if set(expected_subjects).issuperset(subj_set) or subj_set.issuperset(set(expected_subjects)):
                for subj, body in blocks:
                    if subj in expected_subjects:
                        if body.strip() == "":
                            nonempty_bodies = False
                            break
                blocks_ok = nonempty_bodies and subjects_ok
        scores["drafts_three_blocks_and_nonempty_bodies"] = 1.0 if blocks_ok else 0.0
        wc_ok = True
        subj_to_body = {s: b for s, b in blocks}
        for s in expected_subjects:
            b = subj_to_body.get(s, "")
            if _words_count(b) > 80:
                wc_ok = False
                break
        scores["drafts_bodies_word_count"] = 1.0 if wc_ok and blocks_ok else 0.0
        banned = ["enforcement", "juvenile", "at-risk", "offender", "compliance"]
        lt = drafts_text.lower()
        banned_ok = True
        for w in banned:
            if w.lower() in lt:
                banned_ok = False
                break
        scores["drafts_avoid_banned_words"] = 1.0 if banned_ok and blocks_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()