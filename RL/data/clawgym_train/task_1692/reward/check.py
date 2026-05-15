import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _compute_week_summary_from_readings(readings: List[Dict[str, str]]) -> Dict[int, Dict[str, object]]:
    weeks: Dict[int, Dict[str, object]] = {}
    # initialize structure
    for row in readings:
        w = _safe_int(row.get("week", ""))
        if w is None:
            continue
        if w not in weeks:
            weeks[w] = {
                "fiction_count": 0,
                "nonfiction_count": 0,
                "total_pages": 0,
                "motif_counts": {},
            }
        rtype = (row.get("type") or "").strip()
        length = _safe_int(row.get("length_pages", "0")) or 0
        weeks[w]["total_pages"] += length
        if rtype.lower() == "fiction":
            weeks[w]["fiction_count"] += 1
        elif rtype.lower() == "nonfiction":
            weeks[w]["nonfiction_count"] += 1
        motifs_str = row.get("motifs") or ""
        motifs = [m.strip() for m in motifs_str.split(";") if m.strip()]
        mcounts: Dict[str, int] = weeks[w]["motif_counts"]  # type: ignore
        for m in motifs:
            mcounts[m] = mcounts.get(m, 0) + 1
    # finalize top motifs
    result: Dict[int, Dict[str, object]] = {}
    for w, data in weeks.items():
        mcounts: Dict[str, int] = data["motif_counts"]  # type: ignore
        # sort by descending frequency then alphabetically
        sorted_motifs = sorted(mcounts.items(), key=lambda kv: (-kv[1], kv[0]))
        top = [m for m, c in sorted_motifs[:3]]
        top_str = ",".join(top)
        result[w] = {
            "week": w,
            "fiction_count": data["fiction_count"],
            "nonfiction_count": data["nonfiction_count"],
            "total_pages": data["total_pages"],
            "top_motifs": top_str,
        }
    return result


def _parse_week_summary_file(path: Path) -> Optional[Dict[int, Dict[str, object]]]:
    rows = _load_csv_dicts(path)
    if rows is None:
        return None
    # Ensure columns exactly
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return None
    if header is None:
        return None
    expected_header = ["week", "fiction_count", "nonfiction_count", "total_pages", "top_motifs"]
    if header != expected_header:
        return None
    mapping: Dict[int, Dict[str, object]] = {}
    for r in rows:
        w = _safe_int(r.get("week", ""))
        fc = _safe_int(r.get("fiction_count", ""))
        nfc = _safe_int(r.get("nonfiction_count", ""))
        tp = _safe_int(r.get("total_pages", ""))
        tm = (r.get("top_motifs") or "").strip()
        if w is None or fc is None or nfc is None or tp is None:
            return None
        mapping[w] = {
            "week": w,
            "fiction_count": fc,
            "nonfiction_count": nfc,
            "total_pages": tp,
            "top_motifs": tm,
        }
    return mapping


def _word_count(text: str) -> int:
    # count tokens as words (letters, digits, underscores, hyphens, apostrophes within words)
    tokens = re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)
    return len(tokens)


def _find_bullet_lines(text: str) -> List[str]:
    lines = _normalize_newlines(text).split("\n")
    bullets = []
    for ln in lines:
        s = ln.lstrip()
        if s.startswith("- ") or s.startswith("* ") or s.startswith("• "):
            bullets.append(ln)
    return bullets


def _contains_number_with_context(text: str, number: int, context_keywords: List[str], window: int = 60) -> bool:
    txt = text
    num_pattern = re.compile(rf"\b{number}\b")
    for m in num_pattern.finditer(txt):
        start = max(0, m.start() - window)
        end = min(len(txt), m.end() + window)
        snippet = txt[start:end].lower()
        if any(k.lower() in snippet for k in context_keywords):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "week_summary_exists_and_columns": 0.0,
        "week_summary_content_correct": 0.0,
        "syllabus_contains_title": 0.0,
        "syllabus_contains_learning_outcomes_verbatim": 0.0,
        "syllabus_contains_policies_verbatim": 0.0,
        "syllabus_lists_readings_with_details": 0.0,
        "syllabus_reflective_prompts_correct": 0.0,
        "validation_report_structure_and_values": 0.0,
        "student_email_word_count_and_bullets": 0.0,
        "student_email_avg_pages_matches_summary": 0.0,
        "student_email_titles_match_syllabus": 0.0,
        "chair_email_word_count_and_requirements": 0.0,
        "chair_email_total_pages_matches_summary": 0.0,
        "announcement_rewrite_formal_word_count": 0.0,
        "announcement_rewrite_friendly_word_count": 0.0,
        "announcement_rewrite_concise_word_count": 0.0,
    }

    # Load inputs
    readings_path = workspace / "input" / "readings.csv"
    lo_path = workspace / "input" / "learning_outcomes.json"
    policies_path = workspace / "input" / "course_policies.md"

    readings_rows = _load_csv_dicts(readings_path) or []
    lo_json = _load_json(lo_path)
    policies_text = _read_text(policies_path)
    policies_text_norm = _normalize_newlines(policies_text) if policies_text is not None else None

    expected_summary = _compute_week_summary_from_readings(readings_rows) if readings_rows else {}

    # Check week_summary.csv
    week_summary_path = workspace / "output" / "week_summary.csv"
    week_summary_map = None
    exists_and_columns = False
    if week_summary_path.exists():
        # Verify header exactly
        try:
            with week_summary_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
            if header == ["week", "fiction_count", "nonfiction_count", "total_pages", "top_motifs"]:
                exists_and_columns = True
        except Exception:
            exists_and_columns = False
    scores["week_summary_exists_and_columns"] = 1.0 if exists_and_columns else 0.0

    week_summary_map = _parse_week_summary_file(week_summary_path) if exists_and_columns else None
    if week_summary_map is not None and expected_summary:
        # Compare content strictly
        # Create simplified comparables
        def simplify(m: Dict[int, Dict[str, object]]) -> Dict[int, Tuple[int, int, int, str]]:
            return {w: (int(v["fiction_count"]), int(v["nonfiction_count"]), int(v["total_pages"]), str(v["top_motifs"])) for w, v in m.items()}

        got = simplify(week_summary_map)
        exp = simplify(expected_summary)
        if got == exp:
            scores["week_summary_content_correct"] = 1.0
        else:
            scores["week_summary_content_correct"] = 0.0
    else:
        scores["week_summary_content_correct"] = 0.0

    # syllabus.md checks
    syllabus_path = workspace / "output" / "syllabus.md"
    syllabus_text = _read_text(syllabus_path)
    syllabus_text_norm = _normalize_newlines(syllabus_text) if syllabus_text is not None else None

    # title check
    title_ok = False
    if syllabus_text_norm is not None and lo_json and "course_title" in lo_json:
        title_str = lo_json.get("course_title", "")
        if title_str and title_str in syllabus_text_norm:
            title_ok = True
    scores["syllabus_contains_title"] = 1.0 if title_ok else 0.0

    # learning outcomes verbatim check
    lo_ok = False
    if syllabus_text_norm is not None and lo_json and isinstance(lo_json.get("outcomes"), list):
        outcomes = lo_json.get("outcomes", [])
        if outcomes:
            present = sum(1 for o in outcomes if isinstance(o, str) and o in syllabus_text_norm)
            lo_ok = (present == len(outcomes))
    scores["syllabus_contains_learning_outcomes_verbatim"] = 1.0 if lo_ok else 0.0

    # policies verbatim check
    policies_ok = False
    if syllabus_text_norm is not None and policies_text_norm is not None:
        if policies_text_norm in syllabus_text_norm:
            policies_ok = True
    scores["syllabus_contains_policies_verbatim"] = 1.0 if policies_ok else 0.0

    # readings listing with details
    readings_details_score = 0.0
    if syllabus_text_norm is not None and readings_rows:
        lines = syllabus_text_norm.split("\n")
        found_count = 0
        total = len(readings_rows)
        for r in readings_rows:
            title = r.get("title", "").strip()
            author = r.get("author", "").strip()
            rtype = (r.get("type", "")).strip()
            length = str(_safe_int(r.get("length_pages", "0")) or 0)
            blurb = (r.get("blurb") or "").strip()
            # find a line containing both title and author
            idxs = [i for i, ln in enumerate(lines) if title in ln and author in ln]
            match_found = False
            for i in idxs:
                window = "\n".join(lines[i:i+6])
                if rtype in window and re.search(rf"\b{re.escape(length)}\b", window) and blurb in window:
                    match_found = True
                    break
            if match_found:
                found_count += 1
        if total > 0:
            readings_details_score = found_count / total
    scores["syllabus_lists_readings_with_details"] = readings_details_score

    # reflective prompts check
    prompts_score = 0.0
    if syllabus_text_norm is not None and week_summary_map:
        total_weeks = len(week_summary_map)
        found_prompts = 0
        for w, data in week_summary_map.items():
            top_motifs = str(data.get("top_motifs", ""))
            parts = [p for p in top_motifs.split(",") if p]
            if len(parts) >= 2:
                m1, m2 = parts[0], parts[1]
                sentence = f"Reflect on how {m1} and {m2} complicate the boundary between reality and fiction."
                if sentence in syllabus_text_norm:
                    found_prompts += 1
        if total_weeks > 0:
            prompts_score = found_prompts / total_weeks
    scores["syllabus_reflective_prompts_correct"] = prompts_score

    # validation_report.json check
    validation_path = workspace / "output" / "validation_report.json"
    val_json = _load_json(validation_path)
    val_ok = False
    if val_json is not None and isinstance(val_json, dict) and expected_summary:
        # expected lists
        weeks_missing_types = []
        weeks_over_page_limit = []
        for w in sorted(expected_summary.keys()):
            entry = expected_summary[w]
            if int(entry["fiction_count"]) == 0 or int(entry["nonfiction_count"]) == 0:
                weeks_missing_types.append(w)
            if int(entry["total_pages"]) > 120:
                weeks_over_page_limit.append(w)
        expected_valid = (len(weeks_missing_types) == 0 and len(weeks_over_page_limit) == 0)
        got_valid = val_json.get("valid", None)
        got_missing = val_json.get("weeks_missing_types", None)
        got_over = val_json.get("weeks_over_page_limit", None)
        if isinstance(got_valid, bool) and isinstance(got_missing, list) and isinstance(got_over, list):
            try:
                got_missing_ints = [int(x) for x in got_missing]
                got_over_ints = [int(x) for x in got_over]
                val_ok = (got_missing_ints == weeks_missing_types and got_over_ints == weeks_over_page_limit and got_valid == expected_valid)
            except Exception:
                val_ok = False
    scores["validation_report_structure_and_values"] = 1.0 if val_ok else 0.0

    # emails paths
    students_email_path = workspace / "output" / "emails" / "students_announcement.txt"
    chair_email_path = workspace / "output" / "emails" / "chair_request.txt"
    announce_formal_path = workspace / "output" / "emails" / "announcement_rewrite_formal.txt"
    announce_friendly_path = workspace / "output" / "emails" / "announcement_rewrite_friendly.txt"
    announce_concise_path = workspace / "output" / "emails" / "announcement_rewrite_concise.txt"

    students_email_text = _read_text(students_email_path) or ""
    chair_email_text = _read_text(chair_email_path) or ""
    announce_formal_text = _read_text(announce_formal_path) or ""
    announce_friendly_text = _read_text(announce_friendly_path) or ""
    announce_concise_text = _read_text(announce_concise_path) or ""

    # Student email: word count and bullets
    student_wc = _word_count(students_email_text) if students_email_text else 0
    bullets = _find_bullet_lines(students_email_text) if students_email_text else []
    # Determine week 1 and 2 titles
    week_titles: Dict[int, List[str]] = {}
    for r in readings_rows:
        w = _safe_int(r.get("week", ""))
        if w is None:
            continue
        week_titles.setdefault(w, []).append((r.get("title") or "").strip())
    week1_titles = week_titles.get(1, [])
    week2_titles = week_titles.get(2, [])

    # Check that there is a bullet with "Week 1" and all week1 titles, and a bullet with "Week 2" and all week2 titles
    def _has_week_bullet(week_label: str, titles: List[str], bullet_lines: List[str]) -> bool:
        for ln in bullet_lines:
            if re.search(rf"\b{re.escape(week_label)}\b", ln, flags=re.IGNORECASE):
                if all(t in ln for t in titles):
                    return True
        return False

    bullets_ok = False
    if students_email_text and bullets:
        w1_ok = _has_week_bullet("Week 1", week1_titles, bullets) if week1_titles else False
        w2_ok = _has_week_bullet("Week 2", week2_titles, bullets) if week2_titles else False
        bullets_ok = w1_ok and w2_ok

    wc_ok = 160 <= student_wc <= 220
    scores["student_email_word_count_and_bullets"] = 1.0 if (wc_ok and bullets_ok) else 0.0

    # Student email: average weekly page count matches week_summary.csv totals
    avg_match = 0.0
    if week_summary_map and students_email_text:
        totals = [int(v["total_pages"]) for v in week_summary_map.values()]
        if totals:
            avg = sum(totals) / len(totals)
            avg_rounded = int(round(avg))
            # require number appears near "average" or "weekly" or "per week" and "page"
            context_ok = _contains_number_with_context(students_email_text, avg_rounded, ["average", "weekly", "per week", "page", "pages"])
            avg_match = 1.0 if context_ok else 0.0
    scores["student_email_avg_pages_matches_summary"] = avg_match

    # Student email: titles match syllabus (exact strings used)
    titles_match = 0.0
    if syllabus_text_norm and students_email_text and bullets and week1_titles and week2_titles:
        # Confirm titles appear in syllabus
        t1_in_syllabus = all(t in syllabus_text_norm for t in week1_titles)
        t2_in_syllabus = all(t in syllabus_text_norm for t in week2_titles)
        # Confirm bullets include the exact titles
        b1_ok = _has_week_bullet("Week 1", week1_titles, bullets)
        b2_ok = _has_week_bullet("Week 2", week2_titles, bullets)
        if t1_in_syllabus and t2_in_syllabus and b1_ok and b2_ok:
            titles_match = 1.0
    scores["student_email_titles_match_syllabus"] = titles_match

    # Chair email: word count and requirements (learning outcome verbatim, projector, movable chairs)
    chair_wc = _word_count(chair_email_text) if chair_email_text else 0
    lo_quote_ok = False
    if chair_email_text and lo_json and isinstance(lo_json.get("outcomes"), list):
        for o in lo_json.get("outcomes", []):
            if isinstance(o, str) and o in chair_email_text:
                lo_quote_ok = True
                break
    projector_ok = "projector" in chair_email_text.lower()
    movable_chairs_ok = "movable chairs" in chair_email_text.lower()
    chair_req_ok = (120 <= chair_wc <= 180) and lo_quote_ok and projector_ok and movable_chairs_ok
    scores["chair_email_word_count_and_requirements"] = 1.0 if chair_req_ok else 0.0

    # Chair email: total page count matches week_summary.csv totals
    chair_total_ok = 0.0
    if week_summary_map and chair_email_text:
        totals_sum = sum(int(v["total_pages"]) for v in week_summary_map.values())
        context_ok = _contains_number_with_context(chair_email_text, totals_sum, ["total", "page", "pages"])
        chair_total_ok = 1.0 if context_ok else 0.0
    scores["chair_email_total_pages_matches_summary"] = chair_total_ok

    # Announcement rewrites word count checks
    if announce_formal_text:
        wc = _word_count(announce_formal_text)
        scores["announcement_rewrite_formal_word_count"] = 1.0 if 150 <= wc <= 220 else 0.0
    else:
        scores["announcement_rewrite_formal_word_count"] = 0.0

    if announce_friendly_text:
        wc = _word_count(announce_friendly_text)
        scores["announcement_rewrite_friendly_word_count"] = 1.0 if 150 <= wc <= 220 else 0.0
    else:
        scores["announcement_rewrite_friendly_word_count"] = 0.0

    if announce_concise_text:
        wc = _word_count(announce_concise_text)
        scores["announcement_rewrite_concise_word_count"] = 1.0 if wc <= 120 and wc > 0 else 0.0
    else:
        scores["announcement_rewrite_concise_word_count"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()