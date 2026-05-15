import json
import sys
import re
import csv
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            return rows
    except Exception:
        return None


def _extract_numbers(line: str) -> List[float]:
    nums = []
    for m in re.finditer(r"[-+]?\d+(?:\.\d+)?", line):
        try:
            nums.append(float(m.group(0)))
        except ValueError:
            continue
    return nums


def _line_has_number_close(line: str, target: float, tol: float = 0.01) -> bool:
    for n in _extract_numbers(line):
        if abs(n - target) <= tol:
            return True
    return False


def _content_has_number_close(content: str, target: float, tol: float = 0.01) -> bool:
    for line in content.splitlines():
        if _line_has_number_close(line, target, tol):
            return True
    return False


def _has_standalone_int(line: str, value: int) -> bool:
    pattern = rf"(?<!\d){value}(?!\d)"
    return re.search(pattern, line) is not None


def _parse_notes_markdown(md_text: str) -> Dict[str, Dict[str, object]]:
    notes: Dict[str, Dict[str, object]] = {}
    lines = md_text.splitlines()
    current_id = None
    current_content_lines: List[str] = []
    current_tags: List[str] = []

    def commit_note():
        nonlocal current_id, current_content_lines, current_tags
        if current_id is None:
            return
        content_text = "\n".join(current_content_lines).strip()
        first_sentence = content_text
        idx = content_text.find(".")
        if idx != -1:
            first_sentence = content_text[: idx + 1].strip()
        notes[current_id] = {
            "tags": current_tags[:],
            "content": content_text,
            "first_sentence": first_sentence,
        }
        current_id = None
        current_content_lines = []
        current_tags = []

    for line in lines:
        header_match = re.match(r"^\s*#\s*Note\s+(N\d+)\s*$", line.strip())
        if header_match:
            commit_note()
            current_id = header_match.group(1)
            current_content_lines = []
            current_tags = []
            continue
        if current_id:
            tag_match = re.match(r"^\s*Tags:\s*(.+?)\s*$", line)
            if tag_match:
                tags_str = tag_match.group(1)
                tags = [t.strip() for t in tags_str.split(",") if t.strip()]
                current_tags = tags
            else:
                if line.strip() != "":
                    current_content_lines.append(line.strip())

    commit_note()
    return notes


def _compute_expected_metrics(rows: List[Dict[str, str]], guidelines: dict, notes_md: str):
    dates = [r["date"] for r in rows if r.get("date")]
    min_date = min(dates) if dates else None
    max_date = max(dates) if dates else None

    total_books = len(rows)

    def _to_float(val: str) -> float:
        try:
            return float(val)
        except Exception:
            return 0.0

    total_hours = sum(_to_float(r.get("hours", "0")) for r in rows)
    total_cost = sum(_to_float(r.get("materials_cost", "0")) for r in rows)

    treatments = guidelines.get("treatments", []) if isinstance(guidelines, dict) else []
    code_to_expected = {}
    for t in treatments:
        code = t.get("code")
        exp = t.get("expected_hours")
        if code is not None and isinstance(exp, (int, float)):
            code_to_expected[code] = float(exp)

    code_hours: Dict[str, List[float]] = {}
    for r in rows:
        code = r.get("treatment_code", "")
        h = _to_float(r.get("hours", "0"))
        code_hours.setdefault(code, []).append(h)
    avg_hours = {code: (sum(vals) / len(vals) if vals else 0.0) for code, vals in code_hours.items()}

    code_counts = {code: len(vals) for code, vals in code_hours.items()}
    top_counts_sorted = sorted(code_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top3_codes = [c for c, _ in top_counts_sorted[:3]]
    top3_counts = {c: code_counts[c] for c in top3_codes}

    known_codes = set(code_to_expected.keys())
    unknown_code_counts: Dict[str, int] = {}
    for code, cnt in code_counts.items():
        if code not in known_codes:
            unknown_code_counts[code] = cnt

    outliers = []
    for r in rows:
        code = r.get("treatment_code", "")
        if code in code_to_expected:
            hours = _to_float(r.get("hours", "0"))
            exp_hours = code_to_expected[code]
            if hours > 1.5 * exp_hours:
                ratio = hours / exp_hours if exp_hours > 0 else float("inf")
                outliers.append({
                    "date": r.get("date", ""),
                    "book_title": r.get("book_title", ""),
                    "treatment_code": code,
                    "hours": hours,
                    "expected_hours": exp_hours,
                    "ratio": ratio
                })

    referenced_note_ids = [r.get("note_id", "") for r in rows if r.get("note_id")]
    notes = _parse_notes_markdown(notes_md)
    missing_notes = [nid for nid in referenced_note_ids if nid not in notes]

    tag_counts: Dict[str, int] = {}
    tag_to_note_ids: Dict[str, List[str]] = {}
    for nid in referenced_note_ids:
        if nid in notes:
            tags = notes[nid]["tags"]
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                tag_to_note_ids.setdefault(tag, []).append(nid)
    top_tags_sorted = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    top3_tags = [t for t, _ in top_tags_sorted[:3]]
    top3_tags_info = []
    for tag in top3_tags:
        nids = sorted(tag_to_note_ids.get(tag, []))
        freq = tag_counts[tag]
        smallest_nid = min(nids) if nids else None
        first_sentence = ""
        if smallest_nid and smallest_nid in notes:
            first_sentence = notes[smallest_nid]["first_sentence"]
        top3_tags_info.append({
            "tag": tag,
            "frequency": freq,
            "note_ids": nids,
            "first_sentence": first_sentence
        })

    return {
        "min_date": min_date,
        "max_date": max_date,
        "total_books": total_books,
        "total_hours": total_hours,
        "total_cost": total_cost,
        "avg_hours": avg_hours,
        "top3_counts": top3_counts,
        "unknown_code_counts": unknown_code_counts,
        "outliers": outliers,
        "missing_notes": missing_notes,
        "top3_tags_info": top3_tags_info,
        "referenced_note_ids": referenced_note_ids,
        "notes_parsed": notes
    }


def _find_section(content: str, section_name: str) -> str:
    lines = content.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if section_name.lower() in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return ""
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        l = lines[j]
        if (":" in l and l.strip().endswith(":") and j > start_idx + 1) or l.strip().startswith("# "):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "weekly_summary_exists": 0.0,
        "weekly_summary_overview_metrics_dates_and_totals": 0.0,
        "weekly_summary_averages_by_code": 0.0,
        "weekly_summary_top3_codes_with_counts": 0.0,
        "weekly_summary_unknown_codes": 0.0,
        "weekly_summary_outliers_listed": 0.0,
        "weekly_summary_notes_cross_reference": 0.0,
        "notes_insights_top_tags": 0.0,
        "notes_insights_first_sentences": 0.0,
        "email_exists": 0.0,
        "email_subject_with_date_range": 0.0,
        "email_includes_key_metrics": 0.0,
        "email_mentions_unknown_and_outliers": 0.0,
        "email_next_steps_and_feedback": 0.0,
    }

    csv_path = workspace / "input" / "restoration_log.csv"
    json_path = workspace / "input" / "treatment_guidelines.json"
    md_path = workspace / "input" / "session_notes.md"

    rows = _safe_read_csv(csv_path) or []
    guidelines = _safe_load_json(json_path) or {}
    notes_md = _safe_read_text(md_path) or ""

    if not rows or not isinstance(guidelines, dict) or not notes_md:
        expected = None
    else:
        expected = _compute_expected_metrics(rows, guidelines, notes_md)

    weekly_path = workspace / "output" / "weekly_summary.md"
    email_path = workspace / "output" / "email_to_marta.txt"

    weekly_text = _safe_read_text(weekly_path)
    email_text = _safe_read_text(email_path)

    if weekly_text is not None:
        scores["weekly_summary_exists"] = 1.0
    if email_text is not None:
        scores["email_exists"] = 1.0

    if expected is None or weekly_text is None:
        pass
    else:
        overview_ok = False
        if "Overview Metrics" in weekly_text:
            has_min_date = expected["min_date"] and expected["min_date"] in weekly_text
            has_max_date = expected["max_date"] and expected["max_date"] in weekly_text
            books_ok = False
            for line in weekly_text.splitlines():
                if "Total number of books processed" in line and _has_standalone_int(line, expected["total_books"]):
                    books_ok = True
                    break
            hours_ok = _content_has_number_close(weekly_text, float(f"{expected['total_hours']:.2f}")) or _content_has_number_close(weekly_text, expected["total_hours"])
            cost_ok = _content_has_number_close(weekly_text, float(f"{expected['total_cost']:.2f}")) or _content_has_number_close(weekly_text, expected["total_cost"])
            if has_min_date and has_max_date and books_ok and hours_ok and cost_ok:
                overview_ok = True
        scores["weekly_summary_overview_metrics_dates_and_totals"] = 1.0 if overview_ok else 0.0

        avg_ok = True
        for code, avg in expected["avg_hours"].items():
            found = False
            for line in weekly_text.splitlines():
                if (code in line and _line_has_number_close(line, float(f"{avg:.2f}"))) or (code in line and _line_has_number_close(line, avg)):
                    found = True
                    break
            if not found:
                avg_ok = False
                break
        scores["weekly_summary_averages_by_code"] = 1.0 if avg_ok else 0.0

        top3_ok = False
        if "Top 3 treatment_codes" in weekly_text:
            all_present = True
            for code, cnt in expected["top3_counts"].items():
                found = False
                for line in weekly_text.splitlines():
                    if code in line and _has_standalone_int(line, cnt):
                        found = True
                        break
                if not found:
                    all_present = False
                    break
            if all_present:
                top3_ok = True
        scores["weekly_summary_top3_codes_with_counts"] = 1.0 if top3_ok else 0.0

        unknown_ok = False
        comp_section = _find_section(weekly_text, "Compliance Checks")
        if comp_section:
            if expected["unknown_code_counts"]:
                phr = re.search(r"unknown", comp_section, re.IGNORECASE) is not None
                code_cnt_ok = True
                for code, cnt in expected["unknown_code_counts"].items():
                    found = False
                    for line in comp_section.splitlines():
                        if code in line and _has_standalone_int(line, cnt):
                            found = True
                            break
                    if not found:
                        code_cnt_ok = False
                        break
                unknown_ok = phr and code_cnt_ok
            else:
                none_stmt = re.search(r"\b(no|none|0)\b.*unknown", comp_section, re.IGNORECASE) is not None
                unknown_ok = bool(none_stmt)
        scores["weekly_summary_unknown_codes"] = 1.0 if unknown_ok else 0.0

        outliers_ok = False
        if expected["outliers"]:
            all_outliers_present = True
            for o in expected["outliers"]:
                found = False
                for line in weekly_text.splitlines():
                    if (o["book_title"] in line) and (o["treatment_code"] in line) and (o["date"] in line):
                        has_hours = _line_has_number_close(line, o["hours"])
                        has_expected = _line_has_number_close(line, o["expected_hours"])
                        has_ratio = _line_has_number_close(line, float(f"{o['ratio']:.3f}")) or _line_has_number_close(line, o["ratio"])
                        if has_hours and has_expected and has_ratio:
                            found = True
                            break
                if not found:
                    all_outliers_present = False
                    break
            outliers_ok = all_outliers_present
        else:
            outliers_ok = re.search(r"\b(no|none|0)\b.*outlier", comp_section, re.IGNORECASE) is not None if comp_section else False
        scores["weekly_summary_outliers_listed"] = 1.0 if outliers_ok else 0.0

        notes_xref_ok = False
        if comp_section:
            if expected["missing_notes"]:
                listed_all = True
                for nid in expected["missing_notes"]:
                    if nid not in comp_section:
                        listed_all = False
                        break
                notes_xref_ok = listed_all
            else:
                notes_xref_ok = re.search(r"\b(no|none)\b.*\bmissing\b", comp_section, re.IGNORECASE) is not None
        scores["weekly_summary_notes_cross_reference"] = 1.0 if notes_xref_ok else 0.0

        notes_section = _find_section(weekly_text, "Notes Insights")
        top_tags_ok = False
        first_sentences_ok = False
        if notes_section:
            tt_ok = True
            fs_ok = True
            for info in expected["top3_tags_info"]:
                tag = info["tag"]
                freq = info["frequency"]
                nids = info["note_ids"]
                tag_and_freq_found = False
                for line in notes_section.splitlines():
                    if tag in line and _has_standalone_int(line, freq):
                        tag_and_freq_found = True
                        break
                nids_found = all(nid in notes_section for nid in nids)
                if not (tag_and_freq_found and nids_found):
                    tt_ok = False
                first_sentence = info["first_sentence"]
                if first_sentence:
                    if first_sentence not in weekly_text:
                        fs_ok = False
                else:
                    fs_ok = False
            top_tags_ok = tt_ok
            first_sentences_ok = fs_ok
        scores["notes_insights_top_tags"] = 1.0 if top_tags_ok else 0.0
        scores["notes_insights_first_sentences"] = 1.0 if first_sentences_ok else 0.0

    if expected is not None and email_text is not None:
        subject_ok = False
        for line in email_text.splitlines():
            if re.match(r"(?i)^\s*subject\s*:", line):
                if re.search(r"Weekly restoration update\s*\(", line):
                    paren_match = re.search(r"\((.*)\)", line)
                    if paren_match:
                        inside = paren_match.group(1)
                        if (str(expected["min_date"]) in inside) and (str(expected["max_date"]) in inside):
                            subject_ok = True
                break
        scores["email_subject_with_date_range"] = 1.0 if subject_ok else 0.0

        metrics_ok = False
        has_books = _content_has_number_close(email_text, expected["total_books"])
        has_hours = _content_has_number_close(email_text, float(f"{expected['total_hours']:.2f}")) or _content_has_number_close(email_text, expected["total_hours"])
        top_codes = list(expected["top3_counts"].keys())
        has_top_codes = all(code in email_text for code in top_codes)
        if has_books and has_hours and has_top_codes:
            metrics_ok = True
        scores["email_includes_key_metrics"] = 1.0 if metrics_ok else 0.0

        unknown_and_outliers_ok = False
        if expected["unknown_code_counts"]:
            unknown_present = any(code in email_text for code in expected["unknown_code_counts"].keys())
        else:
            unknown_present = re.search(r"\b(no|none|0)\b.*unknown", email_text, re.IGNORECASE) is not None
        outlier_present = True
        for o in expected["outliers"]:
            if o["book_title"] not in email_text:
                outlier_present = False
                break
        unknown_and_outliers_ok = unknown_present and outlier_present
        scores["email_mentions_unknown_and_outliers"] = 1.0 if unknown_and_outliers_ok else 0.0

        has_reviewish = re.search(r"\b(review|discuss|next steps|follow[- ]?up|address)\b", email_text, re.IGNORECASE) is not None
        has_feedbackish = re.search(r"\b(feedback|let me know|thoughts|comments|advise)\b", email_text, re.IGNORECASE) is not None
        next_steps_ok = has_reviewish and has_feedbackish
        scores["email_next_steps_and_feedback"] = 1.0 if next_steps_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()