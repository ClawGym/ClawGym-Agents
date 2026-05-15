import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional


def norm_title(s: str) -> str:
    if s is None:
        return ""
    return " ".join(s.strip().split()).lower()


def safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_jsonl(p: Path) -> Optional[List[dict]]:
    if not p.exists():
        return None
    items = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def safe_read_csv_dicts(p: Path) -> Optional[List[dict]]:
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def parse_watchlist(p: Path) -> Optional[List[dict]]:
    rows = safe_read_csv_dicts(p)
    if rows is None:
        return None
    parsed = []
    try:
        for row in rows:
            title = (row.get("title") or "").strip()
            year_str = (row.get("year") or "").strip()
            runtime_str = (row.get("runtime_min") or "").strip()
            priority = (row.get("priority") or "").strip()
            seen_date = (row.get("seen_date") or "").strip()
            if not title or not year_str or not runtime_str:
                # malformed row; treat parse failure
                return None
            year = int(year_str)
            runtime = int(runtime_str)
            parsed.append({
                "title": title,
                "title_norm": norm_title(title),
                "year": year,
                "priority": priority,
                "owned": (row.get("owned") or "").strip(),
                "seen_date": seen_date,
                "runtime_min": runtime,
            })
        return parsed
    except Exception:
        return None


def parse_ebert_html(p: Path) -> Optional[Dict[Tuple[str, int], dict]]:
    txt = safe_read_text(p)
    if txt is None:
        return None
    items = {}
    try:
        pattern = re.compile(
            r'<li[^>]*>.*?<span[^>]*class=["\']title["\'][^>]*>\s*(.*?)\s*</span>\s*<span[^>]*class=["\']year["\'][^>]*>\s*\((\d{4})\)\s*</span>.*?</li>',
            re.IGNORECASE | re.DOTALL,
        )
        for m in pattern.finditer(txt):
            title = m.group(1).strip()
            year = int(m.group(2))
            items[(norm_title(title), year)] = {"title": title, "year": year}
        return items
    except Exception:
        return None


def parse_ebert_notes(p: Path) -> Optional[Dict[Tuple[str, int], str]]:
    txt = safe_read_text(p)
    if txt is None:
        return None
    lines = txt.splitlines()
    quotes: Dict[Tuple[str, int], str] = {}
    header_re = re.compile(r'^\s*##\s*(.+?)\s*\((\d{4})\)\s*$')
    i = 0
    try:
        while i < len(lines):
            m = header_re.match(lines[i])
            if m:
                title = m.group(1).strip()
                year = int(m.group(2))
                # scan following lines for the first blockquote
                j = i + 1
                first_quote_line = None
                while j < len(lines):
                    if header_re.match(lines[j]):
                        break
                    if lines[j].lstrip().startswith(">"):
                        first_quote_line = lines[j]
                        break
                    j += 1
                if first_quote_line:
                    content = first_quote_line.lstrip().lstrip(">").strip()
                    # first sentence up to first period.
                    if "." in content:
                        idx = content.find(".")
                        sentence = content[: idx + 1].strip()
                    else:
                        sentence = content.strip()
                    quotes[(norm_title(title), year)] = sentence
                i = j
            else:
                i += 1
        return quotes
    except Exception:
        return None


def parse_viewing_log(p: Path) -> Optional[List[dict]]:
    items = safe_load_jsonl(p)
    if items is None:
        return None
    try:
        parsed = []
        for it in items:
            date_str = (it.get("date") or "").strip()
            title = (it.get("title") or "").strip()
            year = int(it.get("year"))
            rating = float(it.get("rating"))
            # validate date format
            datetime.strptime(date_str, "%Y-%m-%d")
            parsed.append({
                "date": date_str,
                "title": title,
                "title_norm": norm_title(title),
                "year": year,
                "rating": rating,
                "notes": it.get("notes"),
            })
        return parsed
    except Exception:
        return None


def parse_bool_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    v = s.strip().lower()
    if v in ("true", "t", "yes", "y", "1"):
        return True
    if v in ("false", "f", "no", "n", "0"):
        return False
    return None


def compute_expected_candidates(watchlist: List[dict], ebert_map: Dict[Tuple[str, int], dict], ebert_quotes: Dict[Tuple[str, int], str]) -> List[dict]:
    expected = []
    for w in watchlist:
        is_high = (w["priority"].strip().lower() == "high")
        not_seen = (w["seen_date"] == "")
        key = (w["title_norm"], w["year"])
        in_ebert = key in ebert_map
        if is_high and not_seen and in_ebert:
            expected.append({
                "title": w["title"],
                "year": w["year"],
                "runtime_min": w["runtime_min"],
                "priority": w["priority"],
                "has_ebert_quote": key in ebert_quotes,
            })
    expected.sort(key=lambda x: x["runtime_min"])
    return expected


def load_student_candidates(p: Path) -> Optional[List[dict]]:
    rows = safe_read_csv_dicts(p)
    if rows is None:
        return None
    # Expect header exactly: title,year,runtime_min,priority,has_ebert_quote
    try:
        with p.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
    except Exception:
        return None
    expected_header = "title,year,runtime_min,priority,has_ebert_quote"
    if header_line.replace(" ", "") != expected_header:
        # Header structure not exact; but still try to parse fields by names
        pass
    parsed = []
    try:
        for r in rows:
            title = (r.get("title") or "").strip()
            if not title:
                return None
            year = int((r.get("year") or "").strip())
            runtime = int((r.get("runtime_min") or "").strip())
            priority = (r.get("priority") or "").strip()
            has_quote_str = r.get("has_ebert_quote")
            has_quote = parse_bool_str(has_quote_str if has_quote_str is not None else "")
            if has_quote is None:
                return None
            parsed.append({
                "title": title,
                "year": year,
                "runtime_min": runtime,
                "priority": priority,
                "has_ebert_quote": has_quote,
            })
        return parsed
    except Exception:
        return None


def get_section_ranges(lines: List[str], names: List[str]) -> Dict[str, Tuple[int, int]]:
    # Return mapping from name to (start_index, end_index) where start is first content line after heading,
    # end is index of last line belonging to that section (exclusive).
    name_patterns = {name: re.compile(r'^\s{0,3}(?:#+\s*)?%s\s*:?\s*$' % re.escape(name), re.IGNORECASE) for name in names}
    indices = {}
    for idx, line in enumerate(lines):
        for name, pat in name_patterns.items():
            if pat.match(line):
                indices[name] = idx
    ranges = {}
    sorted_positions = sorted([(idx, name) for name, idx in indices.items()])
    for i, (start_idx, name) in enumerate(sorted_positions):
        content_start = start_idx + 1
        if i + 1 < len(sorted_positions):
            end_idx = sorted_positions[i + 1][0]
        else:
            end_idx = len(lines)
        ranges[name] = (content_start, end_idx)
    return ranges


def extract_numbers_from_text(text: str) -> List[int]:
    return [int(x) for x in re.findall(r'\b\d+\b', text)]


def section_text(lines: List[str], rng: Tuple[int, int]) -> str:
    s, e = rng
    return "\n".join(lines[s:e]).strip()


def compute_summary_counts(watchlist: Optional[List[dict]], ebert_map: Optional[Dict[Tuple[str, int], dict]]) -> Optional[Tuple[int, int, int]]:
    if watchlist is None or ebert_map is None:
        return None
    total = len(watchlist)
    high_unwatched = 0
    high_unwatched_in_ebert = 0
    for w in watchlist:
        if w["priority"].strip().lower() == "high" and w["seen_date"] == "":
            high_unwatched += 1
            if (w["title_norm"], w["year"]) in ebert_map:
                high_unwatched_in_ebert += 1
    return (total, high_unwatched, high_unwatched_in_ebert)


def compute_recent_watched(log: Optional[List[dict]], n: int = 2) -> Optional[List[dict]]:
    if log is None:
        return None
    try:
        # sort by date descending
        items = []
        for it in log:
            dt = datetime.strptime(it["date"], "%Y-%m-%d")
            items.append((dt, it))
        items.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in items[:n]]
    except Exception:
        return None


def contains_candidate_line_for(line: str, title: str, year: int, runtime: int) -> bool:
    # Must contain Title (Year) and runtime
    if norm_title(title) not in norm_title(line):
        return False
    if f"({year})" not in line:
        return False
    if str(runtime) not in line:
        return False
    return True


def normalize_sentence(s: str) -> str:
    # Lowercase and collapse whitespace and strip surrounding quotes
    s2 = s.strip().strip('"').strip("'")
    s2 = re.sub(r'\s+', ' ', s2)
    return s2.lower()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "next_candidates_file_present": 0.0,
        "next_candidates_header_structure": 0.0,
        "next_candidates_row_count_and_content": 0.0,
        "next_candidates_sort_order": 0.0,
        "next_candidates_has_ebert_quote_values": 0.0,
        "club_update_file_present": 0.0,
        "club_update_has_sections": 0.0,
        "club_update_summary_counts": 0.0,
        "club_update_recent_two": 0.0,
        "club_update_candidate_picks_section": 0.0,
        "club_update_candidate_order_matches_csv": 0.0,
        "club_update_data_checks": 0.0,
    }

    # Input paths
    watchlist_path = workspace / "input" / "watchlist.csv"
    ebert_html_path = workspace / "input" / "ebert_great_movies.html"
    ebert_notes_path = workspace / "input" / "ebert_notes.md"
    viewing_log_path = workspace / "input" / "viewing_log.jsonl"

    # Output paths
    candidates_path = workspace / "output" / "next_candidates.csv"
    update_path = workspace / "output" / "club_update.md"

    # Load inputs
    watchlist = parse_watchlist(watchlist_path)
    ebert_map = parse_ebert_html(ebert_html_path)
    ebert_quotes = parse_ebert_notes(ebert_notes_path)
    viewing_log = parse_viewing_log(viewing_log_path)

    # Compute expected artifacts where possible
    expected_candidates = None
    if watchlist is not None and ebert_map is not None and ebert_quotes is not None:
        expected_candidates = compute_expected_candidates(watchlist, ebert_map, ebert_quotes)

    # Check next_candidates.csv presence
    if candidates_path.exists():
        scores["next_candidates_file_present"] = 1.0

    # Load student candidates
    student_candidates = None
    student_header_ok = False
    if candidates_path.exists():
        try:
            with candidates_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            expected_header = "title,year,runtime_min,priority,has_ebert_quote"
            if header_line == expected_header:
                student_header_ok = True
        except Exception:
            student_header_ok = False
        if student_header_ok:
            scores["next_candidates_header_structure"] = 1.0
        student_candidates = load_student_candidates(candidates_path)

    # Verify next_candidates content and order
    if expected_candidates is not None and student_candidates is not None:
        # Check row count and exact content equality (ordered)
        if len(expected_candidates) == len(student_candidates):
            content_match = True
            has_quote_match = True
            for exp, got in zip(expected_candidates, student_candidates):
                if not (exp["title"] == got["title"]
                        and exp["year"] == got["year"]
                        and exp["runtime_min"] == got["runtime_min"]
                        and exp["priority"].strip().lower() == got["priority"].strip().lower()):
                    content_match = False
                if exp["has_ebert_quote"] != got["has_ebert_quote"]:
                    has_quote_match = False
            if content_match:
                scores["next_candidates_row_count_and_content"] = 1.0
            if has_quote_match:
                scores["next_candidates_has_ebert_quote_values"] = 1.0
        # Check sorting by runtime_min ascending independently
        if len(student_candidates) > 0:
            runtimes = [r["runtime_min"] for r in student_candidates]
            if runtimes == sorted(runtimes):
                scores["next_candidates_sort_order"] = 1.0

    # Check club_update.md presence
    if update_path.exists():
        scores["club_update_file_present"] = 1.0

    # Parse club_update sections
    update_text = safe_read_text(update_path) if update_path.exists() else None
    lines = update_text.splitlines() if isinstance(update_text, str) else []
    # Detect sections
    section_names = ["Summary", "Watched recently", "Candidate picks", "Data checks"]
    ranges = get_section_ranges(lines, section_names)
    if all(name in ranges for name in section_names):
        scores["club_update_has_sections"] = 1.0

    # Summary counts validation
    expected_summary = compute_summary_counts(watchlist, ebert_map)
    if expected_summary is not None and "Summary" in ranges:
        summary_text = section_text(lines, ranges["Summary"])
        nums = extract_numbers_from_text(summary_text)
        # We expect at least three numbers corresponding to a,b,c in order
        if len(nums) >= 3:
            a, b, c = nums[0], nums[1], nums[2]
            if (a, b, c) == expected_summary:
                scores["club_update_summary_counts"] = 1.0

    # Recent watched validation
    expected_recent = compute_recent_watched(viewing_log, 2) if viewing_log is not None else None
    if expected_recent is not None and "Watched recently" in ranges:
        recent_text = section_text(lines, ranges["Watched recently"])
        ok = True
        last_pos = -1
        for item in expected_recent:
            components = [
                item["date"],
                item["title"],
                f"({item['year']})",
                str(item["rating"]),
            ]
            # Ensure all components appear and maintain order by date occurrence
            pos = recent_text.find(item["date"])
            if pos == -1 or pos < last_pos:
                ok = False
                break
            # Check remaining components
            for comp in components[1:]:
                if comp not in recent_text:
                    ok = False
                    break
            if not ok:
                break
            last_pos = pos
        if ok:
            scores["club_update_recent_two"] = 1.0

    # Candidate picks section validation
    if expected_candidates is not None and "Candidate picks" in ranges and ebert_quotes is not None:
        picks_text = section_text(lines, ranges["Candidate picks"])
        pick_lines = [ln for ln in picks_text.splitlines() if ln.strip()]
        # We will try to find each expected candidate in order across the section lines
        ok = True
        line_idx = 0
        for exp in expected_candidates:
            found = False
            exp_title = exp["title"]
            exp_year = exp["year"]
            exp_runtime = exp["runtime_min"]
            exp_key = (norm_title(exp_title), exp_year)
            exp_quote_sentence = ebert_quotes.get(exp_key, "")
            exp_quote_norm = normalize_sentence(exp_quote_sentence)
            while line_idx < len(pick_lines):
                ln = pick_lines[line_idx]
                if contains_candidate_line_for(ln, exp_title, exp_year, exp_runtime):
                    # Check quote presence or missing notice
                    ln_norm = normalize_sentence(ln)
                    if exp_quote_norm:
                        # require presence of the first sentence (normalized) as substring
                        if exp_quote_norm not in ln_norm:
                            ok = False
                        found = True
                        line_idx += 1
                        break
                    else:
                        # must note quote missing
                        if "missing" not in ln_norm or "quote" not in ln_norm:
                            ok = False
                        found = True
                        line_idx += 1
                        break
                line_idx += 1
            if not found:
                ok = False
                break
            if not ok:
                break
        if ok:
            scores["club_update_candidate_picks_section"] = 1.0

    # Candidate order matches CSV
    if "Candidate picks" in ranges and student_candidates is not None:
        picks_text = section_text(lines, ranges["Candidate picks"])
        pick_lines = [ln for ln in picks_text.splitlines() if ln.strip()]
        titles_in_section = []
        for ln in pick_lines:
            # extract Title (Year)
            m = re.search(r'([^\n(]+)\((\d{4})\)', ln)
            if m:
                title = m.group(1).strip()
                year = int(m.group(2))
                titles_in_section.append((norm_title(title), year))
        student_order = [(norm_title(r["title"]), r["year"]) for r in student_candidates]
        # Ensure the sequence in section starts with the student order (same length and order)
        if len(student_order) > 0 and len(titles_in_section) >= len(student_order):
            if titles_in_section[:len(student_order)] == student_order:
                scores["club_update_candidate_order_matches_csv"] = 1.0
        elif len(student_order) == 0:
            # If no candidates in CSV, accept empty or no titles in section
            if len(titles_in_section) == 0:
                scores["club_update_candidate_order_matches_csv"] = 1.0

    # Data checks section
    if "Data checks" in ranges and watchlist is not None and viewing_log is not None:
        data_text = section_text(lines, ranges["Data checks"])
        # Compute expected sets
        wl_by_key = {(w["title_norm"], w["year"]): w for w in watchlist}
        log_keys = {(norm_title(r["title"]), r["year"]) for r in viewing_log}
        # a) in log but missing from watchlist
        missing_from_watchlist = {k for k in log_keys if k not in wl_by_key}
        # b) seen_date in watchlist but not in viewing log
        seen_in_wl = {(w["title_norm"], w["year"]) for w in watchlist if w["seen_date"] != ""}
        missing_from_log = {k for k in seen_in_wl if k not in log_keys}

        # Extract all title-year pairs from the section
        found_pairs = set()
        for m in re.finditer(r'([A-Za-z0-9\.\'\-:,&!?\s]+?)\s*\((\d{4})\)', data_text):
            title = m.group(1).strip()
            year = int(m.group(2))
            found_pairs.add((norm_title(title), year))

        ok = True
        # All expected missing_from_watchlist should be present in the section
        for k in missing_from_watchlist:
            if k not in found_pairs:
                ok = False
                break
        if ok:
            # Pairs that are in missing_from_log should NOT be present (i.e., should be empty here)
            for k in missing_from_log:
                if k in found_pairs:
                    ok = False
                    break
        if ok:
            # Also ensure there are no unexpected pairs beyond union of expected sets
            allowed = missing_from_watchlist.union(missing_from_log)
            unexpected = {p for p in found_pairs if p not in allowed}
            # tolerate descriptive text that might include candidate titles; be lenient: don't penalize unexpected in this case
            # We'll only fail if expected missing_from_watchlist not present or missing_from_log items incorrectly included.
            pass
        if ok:
            scores["club_update_data_checks"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()