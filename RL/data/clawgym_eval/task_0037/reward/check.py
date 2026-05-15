import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            rows = []
            for row in rdr:
                clean_row = {k: (v if v is not None else "") for k, v in row.items()}
                rows.append(clean_row)
            return rows
    except Exception:
        return None


def parse_date(d: str) -> Optional[datetime]:
    try:
        return datetime.strptime(d.strip(), "%Y-%m-%d")
    except Exception:
        return None


def parse_week_context_yaml(path: Path) -> Optional[datetime]:
    txt = read_text(path)
    if txt is None:
        return None
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^report_week_end\s*:\s*['\"]?(\d{4}-\d{2}-\d{2})['\"]?\s*$", line)
        if m:
            d = parse_date(m.group(1))
            return d
    return None


def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def strip_trailing_punct(s: str) -> str:
    return re.sub(r"[\.!\?]+$", "", s.strip())


def remove_priority_parenthetical(s: str) -> str:
    return re.sub(r"\(\s*priority\s*:\s*(high|medium|low)\s*\)", "", s, flags=re.IGNORECASE).strip()


def canonicalize_note(s: str) -> str:
    s2 = strip_trailing_punct(s)
    s2 = remove_priority_parenthetical(s2)
    s2 = normalize_whitespace(s2)
    return s2


def extract_review_items_from_md(md_text: str) -> List[Dict[str, Any]]:
    items = []
    lines = md_text.splitlines()
    for line in lines:
        if "[SHOT:" not in line:
            continue
        tag_match = re.search(r"\[SHOT:\s*([A-Za-z0-9]+)\]", line)
        if not tag_match:
            continue
        shot_id = tag_match.group(1).strip()
        prio_match = re.search(r"\(\s*priority\s*:\s*(high|medium|low)\s*\)", line, flags=re.IGNORECASE)
        priority = prio_match.group(1).lower() if prio_match else "unspecified"
        frames_range = None
        m_range = re.search(r"frames\s+(\d+)\s*-\s*(\d+)", line, flags=re.IGNORECASE)
        m_single = re.search(r"frame\s+(\d+)", line, flags=re.IGNORECASE)
        if m_range:
            start = int(m_range.group(1))
            end = int(m_range.group(2))
            frames_range = {"start": start, "end": end}
        elif m_single:
            n = int(m_single.group(1))
            frames_range = {"start": n, "end": n}
        else:
            frames_range = None
        after = line
        after = re.sub(r"^\s*[-*]\s*", "", after)
        after = re.sub(r"\[SHOT:\s*[A-Za-z0-9]+\]\s*", "", after)
        note_raw = strip_trailing_punct(after).strip()
        items.append({
            "shot_id": shot_id,
            "priority": priority,
            "note": note_raw,
            "frames_range": frames_range
        })
    return items


def compute_rollup(tasks: List[Dict[str, str]], report_week_end: datetime,
                   review_items: List[Dict[str, Any]],
                   standups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    review_count: Dict[str, int] = {}
    for it in review_items:
        sid = it.get("shot_id")
        if sid:
            review_count[sid] = review_count.get(sid, 0) + 1

    shots = sorted({t["shot_id"] for t in tasks})
    blockers_per_shot: Dict[str, List[str]] = {sid: [] for sid in shots}
    seen_blocker_pairs = set()
    for rec in standups:
        blockers = rec.get("blockers", "")
        if not isinstance(blockers, str):
            continue
        for sid in shots:
            if sid in blockers:
                if (sid, blockers) not in seen_blocker_pairs:
                    blockers_per_shot[sid].append(blockers)
                    seen_blocker_pairs.add((sid, blockers))

    rollups: List[Dict[str, Any]] = []
    for sid in shots:
        shot_tasks = [t for t in tasks if t["shot_id"] == sid]
        total_tasks = len(shot_tasks)
        status_counts: Dict[str, int] = {}
        owners_set = set()
        overdue_count = 0
        blocked_count = 0
        for t in shot_tasks:
            status = t.get("status", "")
            due_date_str = t.get("due_date", "").strip()
            due = parse_date(due_date_str)
            status_counts[status] = status_counts.get(status, 0) + 1
            owner = t.get("owner", "")
            if owner:
                owners_set.add(owner)
            if status == "Blocked":
                blocked_count += 1
            if due is not None and due < report_week_end and status != "Done":
                overdue_count += 1
        owners = sorted(list(owners_set), key=lambda x: x)
        ru = {
            "shot_id": sid,
            "total_tasks": total_tasks,
            "status_counts": status_counts,
            "owners": owners,
            "overdue_count": overdue_count,
            "blocked_count": blocked_count,
            "review_comments": review_count.get(sid, 0),
            "standup_blockers": blockers_per_shot.get(sid, [])
        }
        rollups.append(ru)
    return rollups


def compute_overdue_tasks(tasks: List[Dict[str, str]], report_week_end: datetime) -> List[Dict[str, str]]:
    out = []
    for t in tasks:
        due = parse_date(t.get("due_date", "").strip())
        status = t.get("status", "")
        if due is not None and due < report_week_end and status != "Done":
            out.append({
                "task_id": t.get("task_id", ""),
                "title": t.get("title", ""),
                "owner": t.get("owner", ""),
                "due_date": t.get("due_date", ""),
                "status": status,
                "shot_id": t.get("shot_id", "")
            })
    return out


def parse_sections(md_text: str) -> Dict[str, str]:
    labels = ["Summary Metrics:", "Per Shot Highlights:", "Risks & Blockers:", "Next Steps:"]
    positions = {}
    for label in labels:
        idx = md_text.find(label)
        if idx != -1:
            positions[label] = idx
    sections = {}
    if not positions:
        return sections
    ordered = sorted(positions.items(), key=lambda kv: kv[1])
    for i, (label, start) in enumerate(ordered):
        end = len(md_text) if i + 1 == len(ordered) else ordered[i + 1][1]
        sections[label] = md_text[start + len(label):end].strip()
    return sections


def extract_metric_value(section_text: str, key: str) -> Optional[int]:
    m = re.search(rf"{re.escape(key)}\s*[:\-]\s*(\d+)", section_text, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def bullets_in_text(section_text: str) -> List[str]:
    lines = [ln.strip() for ln in section_text.splitlines()]
    return [ln for ln in lines if re.match(r"^[-*]\s+", ln)]


def words_count(s: str) -> int:
    return len([w for w in re.findall(r"\b\w+\b", s)])


def find_labeled_block(full_text: str, label: str) -> Optional[str]:
    pattern = rf"^\s*{re.escape(label)}\s*$"
    lines = full_text.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if re.match(pattern, ln.strip(), flags=re.IGNORECASE):
            start_idx = i
            break
    if start_idx is None:
        return None
    content_lines = []
    for j in range(start_idx + 1, len(lines)):
        if re.match(r"^\s*(Slack post for #animation|Weekly email draft)\s*$", lines[j].strip(), flags=re.IGNORECASE):
            break
        content_lines.append(lines[j])
    return "\n".join(content_lines).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "extracted_review_comments_valid_structure": 0.0,
        "extracted_review_comments_items_correct": 0.0,
        "rollup_by_shot_valid_structure": 0.0,
        "rollup_by_shot_counts_correct": 0.0,
        "tasks_overdue_csv_correct": 0.0,
        "weekly_sync_report_sections_present": 0.0,
        "weekly_sync_report_summary_metrics_consistent": 0.0,
        "weekly_sync_report_per_shot_highlights_quality": 0.0,
        "weekly_sync_report_risks_blockers_coverage": 0.0,
        "weekly_sync_report_next_steps_per_shot": 0.0,
        "rewritten_messages_labels_present": 0.0,
        "rewritten_messages_length_ok": 0.0,
        "rewritten_messages_metrics_consistency": 0.0,
    }

    tasks_path = workspace / "input" / "tasks.csv"
    standup_path = workspace / "input" / "standup_notes.jsonl"
    review_md_path = workspace / "input" / "review_comments.md"
    week_yaml_path = workspace / "input" / "week_context.yaml"
    draft_messages_path = workspace / "input" / "draft_messages.md"

    tasks = load_csv(tasks_path) or []
    standups = load_jsonl(standup_path) or []
    review_md = read_text(review_md_path) or ""
    report_week_end = parse_week_context_yaml(week_yaml_path)
    if report_week_end is None:
        report_week_end = datetime(1900, 1, 1)

    expected_review_items = extract_review_items_from_md(review_md) if review_md else []
    expected_rollup = compute_rollup(tasks, report_week_end, expected_review_items, standups) if tasks else []
    expected_overdue = compute_overdue_tasks(tasks, report_week_end) if tasks else []

    extracted_path = workspace / "output" / "extracted_review_comments.json"
    extracted = load_json(extracted_path)
    if isinstance(extracted, list):
        struct_ok = True
        for it in extracted:
            if not isinstance(it, dict):
                struct_ok = False
                break
            for key in ["shot_id", "priority", "note", "frames_range"]:
                if key not in it:
                    struct_ok = False
                    break
            if not struct_ok:
                break
            if it["frames_range"] is not None:
                fr = it["frames_range"]
                if not (isinstance(fr, dict) and "start" in fr and "end" in fr and isinstance(fr["start"], int) and isinstance(fr["end"], int)):
                    struct_ok = False
                    break
            if it["priority"] not in ["high", "medium", "low", "unspecified"]:
                struct_ok = False
                break
        scores["extracted_review_comments_valid_structure"] = 1.0 if struct_ok else 0.0

        def canon_list(lst):
            by_shot = {}
            for it in lst:
                sid = it.get("shot_id")
                if not sid:
                    continue
                by_shot[sid] = it
            return by_shot

        exp_map = canon_list(expected_review_items)
        got_map = canon_list(extracted)

        items_ok = True
        if set(exp_map.keys()) != set(got_map.keys()):
            items_ok = False
        else:
            for sid, exp in exp_map.items():
                got = got_map.get(sid, {})
                if got.get("priority") != exp.get("priority"):
                    items_ok = False
                    break
                if got.get("frames_range") != exp.get("frames_range"):
                    items_ok = False
                    break
                exp_note_c = canonicalize_note(exp.get("note", ""))
                got_note_c = canonicalize_note(got.get("note", ""))
                if exp_note_c.lower() != got_note_c.lower():
                    items_ok = False
                    break
        scores["extracted_review_comments_items_correct"] = 1.0 if items_ok else 0.0
    else:
        scores["extracted_review_comments_valid_structure"] = 0.0
        scores["extracted_review_comments_items_correct"] = 0.0

    rollup_path = workspace / "output" / "rollup_by_shot.json"
    rollup = load_json(rollup_path)
    if isinstance(rollup, list):
        struct_ok = True
        for it in rollup:
            if not isinstance(it, dict):
                struct_ok = False
                break
            for key in ["shot_id", "total_tasks", "status_counts", "owners", "overdue_count", "blocked_count", "review_comments", "standup_blockers"]:
                if key not in it:
                    struct_ok = False
                    break
            if not struct_ok:
                break
            if not isinstance(it.get("status_counts"), dict):
                struct_ok = False
                break
            if not isinstance(it.get("owners"), list):
                struct_ok = False
                break
            if not isinstance(it.get("standup_blockers"), list):
                struct_ok = False
                break
            owners = it.get("owners", [])
            if owners != sorted(list(set(owners))):
                struct_ok = False
                break
        scores["rollup_by_shot_valid_structure"] = 1.0 if struct_ok else 0.0

        content_ok = True
        exp_map = {it["shot_id"]: it for it in expected_rollup}
        got_map = {it.get("shot_id"): it for it in rollup if isinstance(it, dict) and "shot_id" in it}
        if set(exp_map.keys()) != set(got_map.keys()):
            content_ok = False
        else:
            for sid, exp in exp_map.items():
                got = got_map.get(sid, {})
                if got.get("total_tasks") != exp.get("total_tasks"):
                    content_ok = False
                    break
                if got.get("status_counts") != exp.get("status_counts"):
                    content_ok = False
                    break
                if got.get("owners") != exp.get("owners"):
                    content_ok = False
                    break
                if got.get("overdue_count") != exp.get("overdue_count"):
                    content_ok = False
                    break
                if got.get("blocked_count") != exp.get("blocked_count"):
                    content_ok = False
                    break
                if got.get("review_comments") != exp.get("review_comments"):
                    content_ok = False
                    break
                got_blk = got.get("standup_blockers", [])
                exp_blk = exp.get("standup_blockers", [])
                if set(got_blk) != set(exp_blk):
                    content_ok = False
                    break
        scores["rollup_by_shot_counts_correct"] = 1.0 if content_ok else 0.0
    else:
        scores["rollup_by_shot_valid_structure"] = 0.0
        scores["rollup_by_shot_counts_correct"] = 0.0

    overdue_path = workspace / "output" / "tasks_overdue.csv"
    overdue_rows = load_csv(overdue_path)
    if isinstance(overdue_rows, list):
        headers_ok = True
        try:
            with overdue_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            expected_header = "task_id,title,owner,due_date,status,shot_id"
            headers_ok = (header_line == expected_header)
        except Exception:
            headers_ok = False

        def row_key(r: Dict[str, str]) -> tuple:
            return (r.get("task_id", ""), r.get("title", ""), r.get("owner", ""), r.get("due_date", ""), r.get("status", ""), r.get("shot_id", ""))

        got_set = set(row_key(r) for r in overdue_rows)
        exp_set = set(row_key(r) for r in expected_overdue)
        rows_ok = (got_set == exp_set)
        scores["tasks_overdue_csv_correct"] = 1.0 if (headers_ok and rows_ok) else 0.0
    else:
        scores["tasks_overdue_csv_correct"] = 0.0

    weekly_path = workspace / "output" / "weekly_sync_report.md"
    weekly_text = read_text(weekly_path)
    if isinstance(weekly_text, str):
        sections = parse_sections(weekly_text)
        presence = all(label in sections for label in ["Summary Metrics:", "Per Shot Highlights:", "Risks & Blockers:", "Next Steps:"])
        scores["weekly_sync_report_sections_present"] = 1.0 if presence else 0.0

        total_tasks = len(tasks)
        open_tasks = sum(1 for t in tasks if t.get("status") != "Done")
        overdue_count_total = len(expected_overdue)
        blocked_count_total = sum(1 for t in tasks if t.get("status") == "Blocked")
        metrics_ok = False
        if "Summary Metrics:" in sections:
            summ = sections["Summary Metrics:"]
            tt = extract_metric_value(summ, "total_tasks")
            ot = extract_metric_value(summ, "open_tasks")
            oc = extract_metric_value(summ, "overdue_count")
            bc = extract_metric_value(summ, "blocked_count")
            if tt == total_tasks and ot == open_tasks and oc == overdue_count_total and bc == blocked_count_total:
                metrics_ok = True
        scores["weekly_sync_report_summary_metrics_consistent"] = 1.0 if metrics_ok else 0.0

        psh_ok = False
        if "Per Shot Highlights:" in sections:
            psh = sections["Per Shot Highlights:"]
            bullets = bullets_in_text(psh)
            priority_needed = {it["shot_id"]: it["priority"] for it in expected_review_items if it.get("priority") in ("high", "medium", "low")}
            shots_in_tasks = sorted({t["shot_id"] for t in tasks})
            conds = []
            for sid in shots_in_tasks:
                b_sid = [b for b in bullets if sid in b]
                count_ok = 1 <= len(b_sid) <= 2
                prio = priority_needed.get(sid)
                prio_ok = True
                if prio:
                    prio_ok = any(re.search(rf"\b{prio}\b", b, flags=re.IGNORECASE) for b in b_sid)
                conds.append(count_ok and prio_ok)
            psh_ok = all(conds) if conds else False
        scores["weekly_sync_report_per_shot_highlights_quality"] = 1.0 if psh_ok else 0.0

        rb_ok = False
        if "Risks & Blockers:" in sections:
            rb = sections["Risks & Blockers:"]
            has_s010 = "S010" in rb
            has_s020 = "S020" in rb
            blocked_indicators = ["Blocked", "blocked", "S010-RENDER-007", "S020-COMP-004", "render farm", "updated plates"]
            has_indicators = any(ind in rb for ind in blocked_indicators)
            rb_ok = has_s010 and has_s020 and has_indicators
        scores["weekly_sync_report_risks_blockers_coverage"] = 1.0 if rb_ok else 0.0

        ns_ok = False
        if "Next Steps:" in sections:
            ns = sections["Next Steps:"]
            lines = [ln.strip() for ln in ns.splitlines() if ln.strip()]
            shots_in_tasks = sorted({t["shot_id"] for t in tasks})
            conds = []
            for sid in shots_in_tasks:
                conds.append(any(sid in ln for ln in lines))
            ns_ok = all(conds) if conds else False
        scores["weekly_sync_report_next_steps_per_shot"] = 1.0 if ns_ok else 0.0
    else:
        scores["weekly_sync_report_sections_present"] = 0.0
        scores["weekly_sync_report_summary_metrics_consistent"] = 0.0
        scores["weekly_sync_report_per_shot_highlights_quality"] = 0.0
        scores["weekly_sync_report_risks_blockers_coverage"] = 0.0
        scores["weekly_sync_report_next_steps_per_shot"] = 0.0

    rewritten_path = workspace / "output" / "rewritten_messages.md"
    rewritten_text = read_text(rewritten_path)
    if isinstance(rewritten_text, str):
        label1 = "Slack post for #animation"
        label2 = "Weekly email draft"
        has_labels = (re.search(rf"^\s*{re.escape(label1)}\s*$", rewritten_text, flags=re.IGNORECASE | re.MULTILINE) is not None and
                      re.search(rf"^\s*{re.escape(label2)}\s*$", rewritten_text, flags=re.IGNORECASE | re.MULTILINE) is not None)
        scores["rewritten_messages_labels_present"] = 1.0 if has_labels else 0.0

        block1 = find_labeled_block(rewritten_text, label1) or ""
        block2 = find_labeled_block(rewritten_text, label2) or ""
        len_ok = words_count(block1) <= 120 and words_count(block2) <= 120 and words_count(block1) > 0 and words_count(block2) > 0
        scores["rewritten_messages_length_ok"] = 1.0 if len_ok else 0.0

        total_tasks = len(tasks)
        open_tasks = sum(1 for t in tasks if t.get("status") != "Done")
        overdue_count_total = len(expected_overdue)
        blocked_count_total = sum(1 for t in tasks if t.get("status") == "Blocked")

        def check_metrics_consistency(text: str) -> bool:
            ok = True
            pairs = [
                ("total", total_tasks),
                ("open", open_tasks),
                ("overdue", overdue_count_total),
                ("blocked", blocked_count_total),
            ]
            for key, val in pairs:
                for m in re.finditer(rf"{key}\s*(?:tasks?|count|:|-)?\s*(\d+)", text, flags=re.IGNORECASE):
                    num = int(m.group(1))
                    if num != val:
                        ok = False
                        break
                if not ok:
                    break
            return ok

        metrics_ok = check_metrics_consistency(block1) and check_metrics_consistency(block2)
        scores["rewritten_messages_metrics_consistency"] = 1.0 if metrics_ok else 0.0
    else:
        scores["rewritten_messages_labels_present"] = 0.0
        scores["rewritten_messages_length_ok"] = 0.0
        scores["rewritten_messages_metrics_consistency"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()