import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple


REQUIRED_KEYWORDS = [
    "spiritual",
    "spirituals",
    "Negro spirituals",
    "freedom song",
    "freedom songs",
    "We Shall Overcome",
]
REQUIRED_FIELDS = ["title", "text"]
REQUIRED_START_YEAR = 1860
REQUIRED_END_YEAR = 1970

MATCHES_HEADER = ['id', 'title', 'year', 'movement_type', 'field', 'keyword', 'match_start', 'match_excerpt']


def safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8")
        return True, text
    except Exception:
        return False, ""


def safe_load_json(path: Path) -> Tuple[bool, Dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return True, data
    except Exception:
        return False, {}


def safe_read_jsonl(path: Path) -> Tuple[bool, List[Dict]]:
    rows = []
    try:
        with path.open('r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    rows.append(json.loads(s))
                except json.JSONDecodeError:
                    return False, []
        return True, rows
    except Exception:
        return False, []


def read_csv_with_header(path: Path) -> Tuple[bool, List[str], List[Dict[str, str]]]:
    try:
        with path.open('r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = list(reader)
        return True, header, rows
    except Exception:
        return False, [], []


def recompute_expected_matches(corpus_path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    ok, records = safe_read_jsonl(corpus_path)
    if not ok:
        return False, []
    expected = []
    for rec in records:
        year = rec.get("year", None)
        try:
            y = int(year)
        except Exception:
            y = None
        if y is None:
            continue
        if y < REQUIRED_START_YEAR or y > REQUIRED_END_YEAR:
            continue
        for field in REQUIRED_FIELDS:
            text = rec.get(field, "")
            if not isinstance(text, str):
                continue
            base = text.lower()
            for kw in REQUIRED_KEYWORDS:
                target = kw.lower()
                idx = base.find(target)
                if idx != -1:
                    start = max(0, idx - 40)
                    end = min(len(text), idx + len(kw) + 40)
                    excerpt = ('' if start == 0 else '...') + text[start:end] + ('' if end == len(text) else '...')
                    expected.append({
                        'id': rec.get('id', ''),
                        'title': rec.get('title', ''),
                        'year': rec.get('year', ''),
                        'movement_type': rec.get('movement_type', ''),
                        'field': field,
                        'keyword': kw,
                        'match_start': str(idx),
                        'match_excerpt': excerpt
                    })
    return True, expected


def index_matches(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str, str, int], Dict[str, str]]:
    idx = {}
    for r in rows:
        try:
            ms = int(r.get('match_start', ''))
        except Exception:
            continue
        key = (r.get('id', ''), r.get('field', ''), r.get('keyword', ''), ms)
        idx[key] = r
    return idx


def parse_markdown_section(text: str, start_header: str) -> Tuple[str, str, str]:
    """
    Returns (before_section, section_content, after_section) by locating the header 'start_header'
    and the next header that starts with '## ' after it.
    """
    # Find the section header line
    lines = text.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if ln.strip().lower() == start_header.strip().lower():
            start_idx = i
            break
    if start_idx is None:
        # Try to find header with leading/trailing spaces
        for i, ln in enumerate(lines):
            if ln.strip().lower().startswith(start_header.strip().lower()):
                start_idx = i
                break
    if start_idx is None:
        return text, "", ""
    # Find next header
    end_idx = None
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip().startswith("## ") and j > start_idx:
            end_idx = j
            break
    if end_idx is None:
        end_idx = len(lines)
    before = "\n".join(lines[:start_idx])
    section = "\n".join(lines[start_idx:end_idx])
    after = "\n".join(lines[end_idx:])
    return before, section, after


def extract_bullets(section_text: str) -> List[str]:
    bullets = []
    for ln in section_text.splitlines():
        s = ln.strip()
        if s.startswith("- "):
            bullets.append(s[2:].strip())
        elif s.startswith("* "):
            bullets.append(s[2:].strip())
    return bullets


def has_movement_term(text: str) -> bool:
    t = text.lower()
    # Accept 'civil rights' with or without hyphen
    return ("abolition" in t) or ("labor" in t) or ("civil rights" in t) or ("civil-rights" in t)


def extract_doc_ids(text: str) -> List[str]:
    return re.findall(r"\bdoc\d+\b", text)


def extract_years(text: str) -> List[int]:
    years = []
    for m in re.findall(r"\b(18\d{2}|19\d{2}|20\d{2})\b", text):
        try:
            y = int(m)
            years.append(y)
        except Exception:
            pass
    return years


def extract_quotes(text: str) -> List[str]:
    quotes = []
    # Double quotes
    quotes += re.findall(r"\"([^\"]{1,200})\"", text)
    # Single quotes
    quotes += re.findall(r"'([^']{1,200})'", text)
    return quotes


def find_methods_note(section_text: str) -> str:
    # Return substring starting at "Methods" (case-insensitive) to end of section
    m = re.search(r'(?is)methods[:\s-]*', section_text)
    if not m:
        return ""
    start = m.start()
    return section_text[start:]


def split_into_sentences(text: str) -> List[str]:
    parts = re.split(r'[.!?]+', text)
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_has_required_fields": 0.0,
        "first_run_log_captured_failure": 0.0,
        "success_run_log_captured_success": 0.0,
        "matches_csv_covers_expected_required_keywords": 0.0,
        "match_counts_from_matches_csv": 0.0,
        "lit_review_bullets_count_and_replacement": 0.0,
        "lit_review_bullets_content_valid": 0.0,
        "lit_review_methods_note_valid": 0.0,
        "status_update_contents_valid": 0.0,
    }

    # 1) Check updated config
    cfg_path = workspace / "config" / "search_config.json"
    ok_cfg, cfg = safe_load_json(cfg_path)
    if ok_cfg:
        has_keywords = isinstance(cfg.get("keywords"), list)
        has_fields = isinstance(cfg.get("fields"), list)
        has_case_insensitive = cfg.get("case_sensitive", False) is False
        start_year_ok = int(cfg.get("start_year", -1)) == REQUIRED_START_YEAR if isinstance(cfg.get("start_year"), int) or isinstance(cfg.get("start_year"), str) else False
        end_year_ok = int(cfg.get("end_year", -1)) == REQUIRED_END_YEAR if isinstance(cfg.get("end_year"), int) or isinstance(cfg.get("end_year"), str) else False
        # Check that all required keywords are included
        kw_list = cfg.get("keywords", []) if has_keywords else []
        kw_includes = all(any(k == req for k in kw_list) for req in REQUIRED_KEYWORDS)
        fields_list = cfg.get("fields", []) if has_fields else []
        fields_ok = set(fields_list) == set(REQUIRED_FIELDS)
        if has_keywords and has_fields and has_case_insensitive and start_year_ok and end_year_ok and kw_includes and fields_ok:
            scores["config_has_required_fields"] = 1.0

    # 2) Logs checks
    first_log_path = workspace / "output" / "logs" / "first_run.txt"
    ok_first, first_log = safe_read_text(first_log_path)
    if ok_first:
        # Expect failure due to missing keywords/fields in original config
        if ("Config error:" in first_log) and ("Missing required config key(s)" in first_log):
            scores["first_run_log_captured_failure"] = 1.0

    success_log_path = workspace / "output" / "logs" / "success_run.txt"
    ok_succ, succ_log = safe_read_text(success_log_path)
    if ok_succ:
        if ("Processed" in succ_log) and ("matches" in succ_log) and ("Config error" not in succ_log):
            scores["success_run_log_captured_success"] = 1.0

    # 3) matches.csv validation and coverage
    matches_path = workspace / "output" / "matches.csv"
    ok_mat, header, rows = read_csv_with_header(matches_path)
    expected_coverage_score = 0.0
    if ok_mat and header == MATCHES_HEADER and len(rows) >= 0:
        # Validate row structure
        fields_valid = all(r.get('field', '') in set(REQUIRED_FIELDS) for r in rows)
        # Validate year ints and presence of required columns
        structure_ok = fields_valid and all(set(MATCHES_HEADER).issubset(set(r.keys())) for r in rows)
        # Title, movement, etc may be empty but header must be present
        if structure_ok:
            # Recompute expected required matches
            corpus_path = workspace / "input" / "sources" / "spirituals_corpus.jsonl"
            ok_exp, expected = recompute_expected_matches(corpus_path)
            if ok_exp:
                idx = index_matches(rows)
                found = 0
                for e in expected:
                    key = (e['id'], e['field'], e['keyword'], int(e['match_start']))
                    if key in idx:
                        # Also verify consistency of title/year/movement_type
                        mrow = idx[key]
                        try:
                            year_match = str(e['year']) == str(mrow.get('year', ''))
                            title_match = str(e['title']) == str(mrow.get('title', ''))
                            mv_match = str(e['movement_type']) == str(mrow.get('movement_type', ''))
                        except Exception:
                            year_match = title_match = mv_match = False
                        if year_match and title_match and mv_match:
                            found += 1
                expected_coverage_score = float(found) / float(len(expected)) if expected else 1.0
                # Cap between 0 and 1
                if expected_coverage_score < 0:
                    expected_coverage_score = 0.0
                if expected_coverage_score > 1:
                    expected_coverage_score = 1.0
                scores["matches_csv_covers_expected_required_keywords"] = expected_coverage_score
            else:
                scores["matches_csv_covers_expected_required_keywords"] = 0.0
        else:
            scores["matches_csv_covers_expected_required_keywords"] = 0.0
    else:
        scores["matches_csv_covers_expected_required_keywords"] = 0.0

    # 4) match_counts.csv computed from matches.csv
    counts_path = workspace / "output" / "match_counts.csv"
    ok_cnt, cnt_header, cnt_rows = read_csv_with_header(counts_path)
    if ok_mat and ok_cnt and cnt_header == ["movement_type", "count"]:
        # compute counts from matches.csv
        comp = {}
        for r in rows:
            key = r.get("movement_type", "")
            comp[key] = comp.get(key, 0) + 1
        # parse provided counts
        provided = {}
        valid_counts = True
        for r in cnt_rows:
            mt = r.get("movement_type", "")
            try:
                c = int(r.get("count", ""))
            except Exception:
                valid_counts = False
                break
            provided[mt] = c
        if valid_counts and provided == comp:
            scores["match_counts_from_matches_csv"] = 1.0

    # 5) lit_review_draft update checks
    draft_path = workspace / "input" / "docs" / "lit_review_draft.md"
    ok_md, md_text = safe_read_text(draft_path)
    if ok_md:
        before, section, after = parse_markdown_section(md_text, "## Evidence Summary (TO UPDATE)")
        # The updated file should no longer have the placeholder section title; it should likely have "## Evidence Summary" or similar
        # We will instead locate any "## Evidence Summary" section (updated) by trying without the placeholder note
        if not section.strip():
            # Try generic header
            before2, section2, after2 = parse_markdown_section(md_text, "## Evidence Summary")
            if section2.strip():
                section = section2

        # Check that placeholder text is removed
        placeholder_removed = "[Replace this section" not in section

        bullets = extract_bullets(section)
        bullets_count_ok = 3 <= len(bullets) <= 5

        # This score ensures replacement and bullet count
        if placeholder_removed and bullets_count_ok:
            scores["lit_review_bullets_count_and_replacement"] = 1.0

        # Build an index of matches by id for quotes verification and year check
        matches_by_id: Dict[str, List[Dict[str, str]]] = {}
        if ok_mat:
            for r in rows:
                did = r.get("id", "")
                matches_by_id.setdefault(did, []).append(r)

        # Validate bullets content: movement term, id+year pair, 1-2 quotes <= 100 chars drawn from match excerpts for that id
        all_bullets_valid = True
        for b in bullets:
            # movement term
            if not has_movement_term(b):
                all_bullets_valid = False
                break
            ids = extract_doc_ids(b)
            yrs = extract_years(b)
            if not ids or not yrs:
                all_bullets_valid = False
                break
            # At least one (id,year) pair must match matches.csv
            id_year_ok = False
            for did in ids:
                # find the canonical year for this id from matches.csv
                id_rows = matches_by_id.get(did, [])
                if not id_rows:
                    continue
                # All rows for that id should have same year
                try:
                    id_year = int(id_rows[0].get("year", ""))
                except Exception:
                    continue
                if id_year in yrs:
                    id_year_ok = True
                    break
            if not id_year_ok:
                all_bullets_valid = False
                break
            # Quotes
            quotes = extract_quotes(b)
            if len(quotes) < 1 or len(quotes) > 2:
                all_bullets_valid = False
                break
            # Each quote length <= 100 and appears in some match_excerpt for some cited id
            for q in quotes:
                if len(q) > 100:
                    all_bullets_valid = False
                    break
                # verify presence in matches excerpts for at least one cited id
                q_ok = False
                for did in ids:
                    for mr in matches_by_id.get(did, []):
                        excerpt = mr.get("match_excerpt", "")
                        if q.lower() in excerpt.lower():
                            q_ok = True
                            break
                    if q_ok:
                        break
                if not q_ok:
                    all_bullets_valid = False
                    break
            if not all_bullets_valid:
                break

        if bullets and all_bullets_valid:
            scores["lit_review_bullets_content_valid"] = 1.0

        # Methods note: two sentences; mentions 1860 and 1970, and mentions multiple keywords
        methods_text = find_methods_note(section)
        sentences = split_into_sentences(methods_text)
        has_years = ("1860" in methods_text) and ("1970" in methods_text)
        kw_mentions = sum(1 for kw in REQUIRED_KEYWORDS if kw.lower() in methods_text.lower())
        # Require exactly 2 sentences and at least 3 keyword mentions and both years
        if len(sentences) == 2 and has_years and kw_mentions >= 3:
            scores["lit_review_methods_note_valid"] = 1.0

    # 6) status_update.md content checks
    status_path = workspace / "output" / "status_update.md"
    ok_status, status_text = safe_read_text(status_path)
    if ok_status:
        # (a) what changed in configuration: look for 'keywords' and 'fields' and year range
        mentions_cfg = ("keywords" in status_text.lower()) and ("fields" in status_text.lower())
        mentions_years = ("1860" in status_text) and ("1970" in status_text)
        # (b) exact command(s) used to produce matches and match_counts
        cmd_search_ok = ("python3 scripts/search_spirituals.py" in status_text and
                         "--config" in status_text and
                         "config/search_config.json" in status_text and
                         "--input" in status_text and
                         "input/sources/spirituals_corpus.jsonl" in status_text and
                         "--output" in status_text and
                         "output/matches.csv" in status_text)
        # counts command evidence: presence of match_counts.csv mentioned and description text
        mentions_counts = "output/match_counts.csv" in status_text
        # (c) limitations or assumptions
        mentions_limitation = ("limitation" in status_text.lower()) or ("assumption" in status_text.lower())
        if mentions_cfg and mentions_years and cmd_search_ok and mentions_counts and mentions_limitation:
            scores["status_update_contents_valid"] = 1.0

    return scores


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Grader for spirituals search task")
    parser.add_argument("workspace", nargs="?", default=".", help="Path to workspace root")
    args = parser.parse_args()
    result = grade([], args.workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()