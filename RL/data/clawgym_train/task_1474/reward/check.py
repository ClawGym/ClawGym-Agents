import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def safe_read_text(path: Path) -> Tuple[str, bool]:
    try:
        text = path.read_text(encoding="utf-8")
        return text, True
    except Exception:
        return "", False


def safe_load_json(path: Path) -> Tuple[dict, bool]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return {}, False


def safe_read_csv(path: Path) -> Tuple[List[Dict[str, str]], List[str], bool]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames if reader.fieldnames is not None else []
            return rows, headers, True
    except Exception:
        return [], [], False


def parse_notes_file(path: Path) -> Optional[dict]:
    text, ok = safe_read_text(path)
    if not ok or not text.strip():
        return None
    date_match = re.search(r"^Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text, flags=re.MULTILINE)
    dur_match = re.search(r"^Duration:\s*([0-9]+)\s*minutes", text, flags=re.MULTILINE | re.IGNORECASE)
    attendees_match = re.search(r"^Attendees:\s*(.+)$", text, flags=re.MULTILINE)
    if not date_match or not dur_match or not attendees_match:
        return None
    date = date_match.group(1).strip()
    try:
        duration = int(dur_match.group(1))
    except Exception:
        return None
    attendees_line = attendees_match.group(1).strip()
    attendees = [a.strip() for a in attendees_line.split(",") if a.strip()]
    decisions = []
    for m in re.finditer(r"^\s*-\s*Decision:\s*(.+)$", text, flags=re.MULTILINE):
        decisions.append(m.group(1).strip())
    action_items = []
    for m in re.finditer(r"^\s*-\s*AI:\s*(.+)$", text, flags=re.MULTILINE):
        line = m.group(1).strip()
        if "—" in line:
            owner_part, item_part = line.split("—", 1)
        elif "-" in line:
            parts = re.split(r"\s-\s", line, 1)
            if len(parts) == 2:
                owner_part, item_part = parts
            else:
                continue
        else:
            continue
        owner = owner_part.strip().rstrip(":")
        item_text = item_part.strip()
        action_items.append({"owner": owner, "text": item_text, "date": date})
    return {
        "file": path,
        "date": date,
        "duration": duration,
        "attendees": attendees,
        "decisions": decisions,
        "action_items": action_items,
    }


def collect_all_notes(workspace: Path) -> List[dict]:
    notes_dir = workspace / "input" / "notes"
    results = []
    if not notes_dir.exists():
        return results
    for p in sorted(notes_dir.glob("*_salonsession.md")):
        parsed = parse_notes_file(p)
        if parsed:
            results.append(parsed)
    return results


def compute_expected_stats(notes: List[dict]) -> dict:
    dates = [n["date"] for n in notes]
    durations = [n["duration"] for n in notes]
    attendees_all = set()
    for n in notes:
        for a in n["attendees"]:
            attendees_all.add(a)
    earliest = min(dates) if dates else None
    latest = max(dates) if dates else None
    avg_duration = round(sum(durations) / len(durations)) if durations else None
    return {
        "earliest_date": earliest,
        "latest_date": latest,
        "sessions_count": len(notes),
        "avg_duration": avg_duration,
        "unique_attendees_count": len(attendees_all),
        "unique_attendees_sorted": sorted(attendees_all),
    }


def split_sections_by_headings(text: str, section_names: List[str]) -> Dict[str, str]:
    lines = text.splitlines()
    indices = {}
    for idx, line in enumerate(lines):
        for sec in section_names:
            if re.match(rf"^\s*#*\s*{re.escape(sec)}\s*:?\s*$", line, flags=re.IGNORECASE):
                indices.setdefault(sec, idx)
    sections = {}
    for i, sec in enumerate(section_names):
        if sec not in indices:
            sections[sec] = ""
            continue
        start = indices[sec] + 1
        next_idx = None
        for j in range(len(lines)):
            if j <= indices[sec]:
                continue
            for other in section_names:
                if other == sec:
                    continue
                if re.match(rf"^\s*#*\s*{re.escape(other)}\s*:?\s*$", lines[j], flags=re.IGNORECASE):
                    next_idx = j
                    break
            if next_idx is not None:
                break
        end = next_idx if next_idx is not None else len(lines)
        sections[sec] = "\n".join(lines[start:end]).strip()
    return sections


def compute_keyword_counts(workspace: Path, notes: List[dict]) -> Tuple[List[str], Dict[str, int]]:
    keywords_json_path = workspace / "input" / "keywords.json"
    data, ok = safe_load_json(keywords_json_path)
    if not ok or "keywords" not in data or not isinstance(data["keywords"], list):
        return [], {}
    keywords = [str(k) for k in data["keywords"]]
    combined_texts = []
    for n in notes:
        t, ok2 = safe_read_text(n["file"])
        if ok2:
            combined_texts.append(t)
    combined = "\n".join(combined_texts)
    counts = {}
    for kw in keywords:
        pattern = re.compile(re.escape(kw), flags=re.IGNORECASE)
        counts[kw] = len(list(pattern.finditer(combined)))
    return keywords, counts


def find_paragraphs(text: str) -> List[str]:
    paras = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in paras if p.strip()]


def count_sentences(paragraph: str) -> int:
    matches = re.findall(r"[A-Za-z0-9][\.!\?](?:\s|$)", paragraph)
    return len(matches)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "combined_summary_sections_present": 0.0,
        "overview_date_range_and_session_count": 0.0,
        "overview_average_duration": 0.0,
        "overview_unique_attendees_list": 0.0,
        "key_decisions_completeness_and_grouping": 0.0,
        "action_items_grouped_by_owner_and_counts": 0.0,
        "keyword_frequencies_list_in_summary": 0.0,
        "meeting_stats_csv_structure": 0.0,
        "meeting_stats_csv_rows": 0.0,
        "keyword_counts_csv_structure": 0.0,
        "keyword_counts_csv_totals": 0.0,
        "preface_title_preserved": 0.0,
        "preface_no_todo_lines": 0.0,
        "preface_triad_quoted_once": 0.0,
        "preface_weaving_paragraph": 0.0,
    }

    notes = collect_all_notes(workspace)
    if not notes:
        return scores

    expected_stats = compute_expected_stats(notes)
    keywords_list, expected_kw_counts = compute_keyword_counts(workspace, notes)

    combined_path = workspace / "output" / "combined_summary.md"
    combined_text, combined_ok = safe_read_text(combined_path)
    if combined_ok and combined_text.strip():
        section_names = ["Overview", "Key Decisions", "Action Items by Owner", "Keyword Frequencies"]
        sections = split_sections_by_headings(combined_text, section_names)
        if all(sections.get(name, "") != "" or re.search(rf"^\s*#*\s*{re.escape(name)}\s*:?\s*$", combined_text, flags=re.IGNORECASE | re.MULTILINE) for name in section_names):
            scores["combined_summary_sections_present"] = 1.0

        overview = sections.get("Overview", combined_text)
        if expected_stats["earliest_date"] and expected_stats["latest_date"]:
            date_ok = (expected_stats["earliest_date"] in overview) and (expected_stats["latest_date"] in overview)
        else:
            date_ok = False

        sessions_count = expected_stats["sessions_count"]
        sess_ok = False
        if sessions_count is not None:
            for line in overview.splitlines():
                if re.search(r"(?i)session", line) and re.search(rf"\b{sessions_count}\b", line):
                    sess_ok = True
                    break

        if date_ok and sess_ok:
            scores["overview_date_range_and_session_count"] = 1.0

        avg = expected_stats["avg_duration"]
        avg_ok = False
        if avg is not None:
            for line in overview.splitlines():
                if re.search(r"(?i)average", line) and re.search(rf"\b{avg}\b", line) and re.search(r"(?i)minute", line):
                    avg_ok = True
                    break
        if avg_ok:
            scores["overview_average_duration"] = 1.0

        attendees_ok = False
        names = expected_stats["unique_attendees_sorted"]
        count = expected_stats["unique_attendees_count"]
        if names and count is not None:
            idxs = []
            all_present = True
            pos = 0
            overview_lower = overview
            for name in names:
                i = overview_lower.find(name, pos)
                if i == -1:
                    all_present = False
                    break
                idxs.append(i)
                pos = i + len(name)
            order_ok = all_present and all(i < j for i, j in zip(idxs, idxs[1:]))
            count_ok = False
            for line in overview.splitlines():
                if re.search(r"(?i)unique|attendees?", line) and re.search(rf"\b{count}\b", line):
                    count_ok = True
                    break
            attendees_ok = order_ok and count_ok
        if attendees_ok:
            scores["overview_unique_attendees_list"] = 1.0

        key_decisions_text = sections.get("Key Decisions", "")
        if key_decisions_text:
            total_decisions = sum(len(n["decisions"]) for n in notes)
            correct_placed = 0
            kd_lines = key_decisions_text.splitlines()
            date_positions = []
            for i, line in enumerate(kd_lines):
                for n in notes:
                    if n["date"] in line:
                        date_positions.append((i, n["date"]))
                        break
            date_positions_sorted = sorted(date_positions, key=lambda x: x[0])
            date_blocks = {}
            for idx, (pos, d) in enumerate(date_positions_sorted):
                start = pos
                end = date_positions_sorted[idx + 1][0] if idx + 1 < len(date_positions_sorted) else len(kd_lines)
                date_blocks[d] = "\n".join(kd_lines[start:end])
            for n in notes:
                decs = n["decisions"]
                block = date_blocks.get(n["date"], key_decisions_text)
                for dec in decs:
                    if dec and (dec in block):
                        correct_placed += 1
            if total_decisions > 0:
                scores["key_decisions_completeness_and_grouping"] = correct_placed / total_decisions

        action_items_text = sections.get("Action Items by Owner", "")
        if action_items_text:
            all_items = []
            owners_counts = {}
            for n in notes:
                for ai in n["action_items"]:
                    all_items.append(ai)
                    owners_counts[ai["owner"]] = owners_counts.get(ai["owner"], 0) + 1
            lines = action_items_text.splitlines()
            item_hits = 0
            for ai in all_items:
                date = ai["date"]
                text = ai["text"]
                words = re.findall(r"[A-Za-z0-9\-']+", text)
                snippet = " ".join(words[:5]) if words else text[:15]
                found = False
                for line in lines:
                    if date in line and re.search(re.escape(snippet), line, flags=re.IGNORECASE):
                        found = True
                        break
                if found:
                    item_hits += 1
            items_score = item_hits / len(all_items) if all_items else 0.0

            owner_hits = 0
            for owner, cnt in owners_counts.items():
                found_owner_count = False
                for line in lines:
                    if owner in line and re.search(rf"\b{cnt}\b", line):
                        found_owner_count = True
                        break
                if found_owner_count:
                    owner_hits += 1
            owner_score = owner_hits / len(owners_counts) if owners_counts else 0.0
            scores["action_items_grouped_by_owner_and_counts"] = (items_score + owner_score) / 2 if (all_items and owners_counts) else 0.0

        kw_section = sections.get("Keyword Frequencies", "")
        if kw_section and expected_kw_counts:
            lines = kw_section.splitlines()
            correct = 0
            for kw, expected in expected_kw_counts.items():
                found = False
                for line in lines:
                    if re.search(re.escape(kw), line, flags=re.IGNORECASE) and re.search(rf"\b{expected}\b", line):
                        found = True
                        break
                if found:
                    correct += 1
            scores["keyword_frequencies_list_in_summary"] = correct / len(expected_kw_counts) if expected_kw_counts else 0.0

    stats_path = workspace / "output" / "meeting_stats.csv"
    rows, headers, ok_csv = safe_read_csv(stats_path)
    expected_headers = ["meeting_file", "date", "duration_minutes", "attendee_count", "decision_count", "action_item_count"]
    if ok_csv and headers == expected_headers:
        scores["meeting_stats_csv_structure"] = 1.0
        expected_by_date = {}
        for n in notes:
            expected_by_date[n["date"]] = {
                "meeting_file": str(n["file"]),
                "date": n["date"],
                "duration_minutes": str(n["duration"]),
                "attendee_count": str(len(n["attendees"])),
                "decision_count": str(len(n["decisions"])),
                "action_item_count": str(len(n["action_items"])),
            }
        expected_count = len(notes)
        if len(rows) == expected_count:
            matched = 0
            actual_by_date = {}
            for r in rows:
                if "date" in r:
                    actual_by_date[r["date"]] = r
            for d, exp in expected_by_date.items():
                actual = actual_by_date.get(d)
                if not actual:
                    continue
                mf_ok = False
                try:
                    mf_ok = Path(actual["meeting_file"]).name == Path(exp["meeting_file"]).name
                except Exception:
                    mf_ok = False
                other_ok = (
                    actual.get("date") == exp["date"]
                    and actual.get("duration_minutes") == exp["duration_minutes"]
                    and actual.get("attendee_count") == exp["attendee_count"]
                    and actual.get("decision_count") == exp["decision_count"]
                    and actual.get("action_item_count") == exp["action_item_count"]
                )
                if mf_ok and other_ok:
                    matched += 1
            if expected_count > 0:
                scores["meeting_stats_csv_rows"] = matched / expected_count
        else:
            scores["meeting_stats_csv_rows"] = 0.0
    else:
        scores["meeting_stats_csv_structure"] = 0.0
        scores["meeting_stats_csv_rows"] = 0.0

    kw_counts_path = workspace / "output" / "keyword_counts.csv"
    rows_kw, headers_kw, ok_kw_csv = safe_read_csv(kw_counts_path)
    expected_kw_headers = ["keyword", "total_count"]
    if ok_kw_csv and headers_kw == expected_kw_headers:
        scores["keyword_counts_csv_structure"] = 1.0
        if expected_kw_counts and keywords_list:
            actual_map = {}
            for r in rows_kw:
                k = r.get("keyword")
                v = r.get("total_count")
                if k is not None and v is not None:
                    actual_map[k] = v
            if len(rows_kw) == len(keywords_list):
                correct = 0
                for kw in keywords_list:
                    expected_val = str(expected_kw_counts.get(kw, 0))
                    actual_val = actual_map.get(kw)
                    if actual_val == expected_val:
                        correct += 1
                scores["keyword_counts_csv_totals"] = correct / len(keywords_list) if keywords_list else 0.0
            else:
                scores["keyword_counts_csv_totals"] = 0.0
        else:
            scores["keyword_counts_csv_totals"] = 0.0
    else:
        scores["keyword_counts_csv_structure"] = 0.0
        scores["keyword_counts_csv_totals"] = 0.0

    preface_in_path = workspace / "input" / "draft_preface.md"
    preface_out_path = workspace / "output" / "preface_rewrite.md"
    in_text, in_ok = safe_read_text(preface_in_path)
    out_text, out_ok = safe_read_text(preface_out_path)
    if in_ok and out_ok and out_text.strip():
        in_lines = in_text.splitlines()
        out_lines = out_text.splitlines()
        title_ok = False
        if len(in_lines) >= 2 and len(out_lines) >= 2:
            title_ok = (in_lines[0].strip() == out_lines[0].strip()) and (in_lines[1].strip() == out_lines[1].strip())
        scores["preface_title_preserved"] = 1.0 if title_ok else 0.0

        todo_ok = ("TODO:" not in out_text)
        scores["preface_no_todo_lines"] = 1.0 if todo_ok else 0.0

        triad = '"bio-abundance, equity, governance"'
        triad_count = len(re.findall(re.escape(triad), out_text))
        scores["preface_triad_quoted_once"] = 1.0 if triad_count == 1 else 0.0

        required_phrases = [
            "CRISPR-enabled public health cooperatives",
            "open-source synthetic biology",
            "community biomanufacturing",
            "bioeconomy",
            "longevity",
            "governance",
        ]
        weaving_ok = False
        for para in find_paragraphs(out_text):
            sent_count = count_sentences(para)
            if 3 <= sent_count <= 5:
                has_all = True
                for rp in required_phrases:
                    if re.search(re.escape(rp), para, flags=re.IGNORECASE) is None:
                        has_all = False
                        break
                if has_all:
                    weaving_ok = True
                    break
        scores["preface_weaving_paragraph"] = 1.0 if weaving_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()