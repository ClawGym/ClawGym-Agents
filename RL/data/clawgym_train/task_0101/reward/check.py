import json
import csv
import re
import ast
import sys
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _parse_simple_yaml(path: Path) -> tuple[dict, bool]:
    """
    Minimal YAML parser for the specific config structure provided:
    - tracked_correspondents: list of strings
    - min_year: int
    - max_year: int
    - keywords: list of strings (optional)
    """
    text = _read_text(path)
    if not text:
        return {}, False
    cfg: dict = {}
    lines = text.splitlines()
    i = 0
    current_key = None
    in_list = False
    list_acc = []
    try:
        while i < len(lines):
            line = lines[i]
            # Strip BOM or weird whitespace
            raw = line
            line = line.rstrip("\n")
            if not line.strip():
                i += 1
                continue
            # Key: value on same line
            m_kv = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*(.*?)\s*$', line)
            if m_kv:
                key = m_kv.group(1)
                val = m_kv.group(2)
                # If value is empty, could be a list starting
                if val == "" or val is None:
                    # Start list
                    if in_list and current_key is not None:
                        cfg[current_key] = list_acc
                    current_key = key
                    in_list = True
                    list_acc = []
                else:
                    # Scalar; try int or keep as string
                    if in_list and current_key is not None:
                        cfg[current_key] = list_acc
                    in_list = False
                    current_key = None
                    sval = val
                    if re.fullmatch(r"-?\d+", sval):
                        cfg[key] = int(sval)
                    else:
                        # Try to parse JSON-like list or string
                        sval = sval.strip()
                        if sval.startswith("[") and sval.endswith("]"):
                            try:
                                cfg[key] = json.loads(sval)
                            except Exception:
                                cfg[key] = sval
                        else:
                            cfg[key] = sval
                i += 1
                continue
            # List item
            if in_list and re.match(r'^\s*-\s+', line):
                item = re.sub(r'^\s*-\s+', '', line).strip()
                # Strip possible wrapping quotes
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                list_acc.append(item)
                i += 1
                continue
            # New key starts without value; end of previous list
            if in_list and re.match(r'^\S', line):
                cfg[current_key] = list_acc
                in_list = False
                current_key = None
                # Do not increment to reprocess this line
                continue
            i += 1
        if in_list and current_key is not None:
            cfg[current_key] = list_acc
        return cfg, True
    except Exception:
        return {}, False


def _parse_extractor_defaults(path: Path) -> tuple[dict, bool]:
    """
    Parse DEFAULT_MIN_YEAR, DEFAULT_MAX_YEAR, DEFAULT_KEYWORDS from scripts/extractor.py.
    """
    text = _read_text(path)
    if not text:
        return {}, False
    defaults = {}
    ok = True
    try:
        m_min = re.search(r'DEFAULT_MIN_YEAR\s*=\s*(-?\d+)', text)
        m_max = re.search(r'DEFAULT_MAX_YEAR\s*=\s*(-?\d+)', text)
        m_keys = re.search(r'DEFAULT_KEYWORDS\s*=\s*(\[[\s\S]*?\])', text)
        if m_min:
            defaults["min_year"] = int(m_min.group(1))
        else:
            ok = False
        if m_max:
            defaults["max_year"] = int(m_max.group(1))
        else:
            ok = False
        if m_keys:
            lst_literal = m_keys.group(1)
            try:
                defaults["keywords"] = ast.literal_eval(lst_literal)
                # Ensure list of strings
                if not isinstance(defaults["keywords"], list) or not all(isinstance(x, str) for x in defaults["keywords"]):
                    ok = False
            except Exception:
                ok = False
        else:
            ok = False
        return defaults, ok
    except Exception:
        return {}, False


def _load_jsonl(path: Path) -> tuple[list, bool]:
    if not path.exists():
        return [], False
    records = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f, 1):
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    return [], False
                if not isinstance(obj, dict):
                    return [], False
                records.append(obj)
        return records, True
    except Exception:
        return [], False


def _load_contacts_csv(path: Path) -> tuple[list[dict], bool]:
    if not path.exists():
        return [], False
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return rows, True
    except Exception:
        return [], False


def _load_csv_with_header(path: Path) -> tuple[list[str], list[list[str]], bool]:
    """
    Load raw CSV preserving header order and raw row values as lists.
    """
    if not path.exists():
        return [], [], False
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return [], [], False
        header = rows[0]
        data_rows = rows[1:]
        return header, data_rows, True
    except Exception:
        return [], [], False


def _compute_effective_config(cfg_yaml: dict, defaults: dict) -> dict:
    # Following scripts/extractor.py logic
    ec = {
        "min_year": cfg_yaml.get("min_year", defaults.get("min_year")),
        "max_year": cfg_yaml.get("max_year", defaults.get("max_year")),
        "keywords": (cfg_yaml.get("keywords") if cfg_yaml.get("keywords") else defaults.get("keywords")),
        "tracked_correspondents": cfg_yaml.get("tracked_correspondents", []),
    }
    return ec


def _year_from_date(date_str: str) -> int | None:
    if not isinstance(date_str, str) or len(date_str) < 4:
        return None
    m = re.match(r'^\s*(\d{4})', date_str)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _extract_matches(letters: list[dict], ec: dict) -> list[dict]:
    tracked = set(ec.get("tracked_correspondents") or [])
    min_year = ec.get("min_year")
    max_year = ec.get("max_year")
    kw_list = ec.get("keywords") or []
    eff_keywords = [str(k).lower() for k in kw_list]
    matches = []
    for rec in letters:
        sender = rec.get("sender", "")
        recipient = rec.get("recipient", "")
        body = rec.get("body", "")
        date = rec.get("date", "")
        y = _year_from_date(date)
        if y is None:
            continue
        cond_tracked = sender in tracked or recipient in tracked
        cond_year = (min_year is None or y >= min_year) and (max_year is None or y <= max_year)
        body_lower = str(body).lower()
        found = sorted(set([k for k in eff_keywords if k in body_lower]))
        cond_kw = len(found) > 0
        if cond_tracked and cond_year and cond_kw:
            matches.append({
                "id": rec.get("id", ""),
                "date": date,
                "sender": sender,
                "recipient": recipient,
                "matched_keywords": ",".join(found),
                "snippet": str(body)[:120],
                "body": str(body),
            })
    return matches


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "extracted_csv_exists_and_header": 0.0,
        "extracted_csv_correct_rows": 0.0,
        "extracted_csv_matched_keywords_and_snippets": 0.0,
        "status_report_effective_config_values_and_sources": 0.0,
        "status_report_totals": 0.0,
        "status_report_matched_bullets": 0.0,
        "status_report_exclusions_bullets": 0.0,
        "email_headers": 0.0,
        "email_bullets_quality": 0.0,
    }

    # Paths
    extractor_py = workspace / "scripts" / "extractor.py"
    cfg_yaml_path = workspace / "config" / "extract_config.yaml"
    letters_path = workspace / "data" / "letters.jsonl"
    extracted_csv_path = workspace / "output" / "extracted_correspondence.csv"
    status_report_path = workspace / "output" / "status_report.md"
    email_path = workspace / "output" / "email_to_collaborator.txt"
    contacts_csv_path = workspace / "team" / "contacts.csv"

    # Load inputs to compute expected results
    defaults, defaults_ok = _parse_extractor_defaults(extractor_py)
    cfg_yaml, cfg_ok = _parse_simple_yaml(cfg_yaml_path)
    letters, letters_ok = _load_jsonl(letters_path)

    ec = {}
    expected_matches = []
    expected_ids = set()
    if defaults_ok and cfg_ok and letters_ok:
        ec = _compute_effective_config(cfg_yaml, defaults)
        expected_matches = _extract_matches(letters, ec)
        expected_ids = set([m["id"] for m in expected_matches])

    required_header = ["id", "date", "sender", "recipient", "matched_keywords", "snippet"]

    # Check extracted_correspondence.csv
    header, data_rows, csv_ok = _load_csv_with_header(extracted_csv_path)
    if csv_ok and header == required_header:
        scores["extracted_csv_exists_and_header"] = 1.0
    else:
        scores["extracted_csv_exists_and_header"] = 0.0

    if csv_ok and defaults_ok and cfg_ok and letters_ok and header == required_header:
        # Build dict from rows
        got_rows = []
        for row in data_rows:
            if len(row) != len(required_header):
                got_rows = []
                break
            got_rows.append({required_header[i]: row[i] for i in range(len(required_header))})
        if not got_rows:
            scores["extracted_csv_correct_rows"] = 0.0
            scores["extracted_csv_matched_keywords_and_snippets"] = 0.0
        else:
            got_ids = set([r["id"] for r in got_rows])
            if got_ids == expected_ids:
                scores["extracted_csv_correct_rows"] = 1.0
            else:
                scores["extracted_csv_correct_rows"] = 0.0

            # Check per-row details
            per_ok = True
            mk_ok = True
            for exp in expected_matches:
                # Find row
                row = next((r for r in got_rows if r["id"] == exp["id"]), None)
                if row is None:
                    per_ok = False
                    mk_ok = False
                    break
                # Exact fields match for date, sender, recipient
                if row["date"] != exp["date"] or row["sender"] != exp["sender"] or row["recipient"] != exp["recipient"]:
                    per_ok = False
                # matched_keywords correctness: lowercase, sorted, unique, subset of effective keywords
                if row["matched_keywords"] != exp["matched_keywords"]:
                    mk_ok = False
                # snippet correctness
                if row["snippet"] != exp["snippet"]:
                    per_ok = False
            scores["extracted_csv_matched_keywords_and_snippets"] = 1.0 if (per_ok and mk_ok) else 0.0
    else:
        # If we can't compute expected due to missing inputs, keep zeros
        pass

    # Check status_report.md
    status_text = _read_text(status_report_path)
    if status_text:
        status_lower = status_text.lower()
        # Effective configuration section and values + sources
        has_section = "effective configuration" in status_lower

        ec_values_ok = False
        source_notes_ok = False
        if defaults_ok and cfg_ok:
            # Check values present
            # min_year
            min_ok = str(ec.get("min_year")) in status_text
            # max_year
            max_ok = str(ec.get("max_year")) in status_text
            # keywords: check both appear
            kws = [str(k).lower() for k in ec.get("keywords", [])]
            kw_ok = all(k in status_lower for k in kws)
            # tracked_correspondents: check all appear
            tr = ec.get("tracked_correspondents", [])
            tr_ok = all(name.lower() in status_lower for name in [str(x).lower() for x in tr])

            ec_values_ok = min_ok and max_ok and kw_ok and tr_ok

            # Sources: min_year, tracked_correspondents from YAML; keywords, max_year from defaults
            # Accept "yaml" or "config" as source indicator; "default" for defaults
            def near(term_key: str, required_words: list[str]) -> bool:
                # Find any line containing term_key and check it (or adjacent) contains any required_words
                lines = status_text.splitlines()
                for idx, line in enumerate(lines):
                    if term_key.lower() in line.lower():
                        window = " ".join(lines[max(0, idx - 1): min(len(lines), idx + 2)])
                        if any(w in window.lower() for w in required_words):
                            return True
                # Also allow a line that lists both keys and the source
                for line in lines:
                    if term_key.lower() in line.lower() and any(w in line.lower() for w in required_words):
                        return True
                return False

            min_src = near("min_year", ["yaml", "config"])
            tr_src = near("tracked_correspondents", ["yaml", "config"])
            max_src = near("max_year", ["default"])
            kw_src = near("keywords", ["default"])
            source_notes_ok = min_src and tr_src and max_src and kw_src

        if has_section and ec_values_ok and source_notes_ok:
            scores["status_report_effective_config_values_and_sources"] = 1.0
        else:
            scores["status_report_effective_config_values_and_sources"] = 0.0

        # Totals: processed and matched
        totals_ok = False
        if letters_ok and defaults_ok and cfg_ok:
            processed_needed = len(letters)
            matched_needed = len(expected_matches)

            # Look for lines containing processed and matched counts
            processed_found = False
            matched_found = False
            for line in status_text.splitlines():
                lwr = line.lower()
                nums = re.findall(r'\d+', line)
                if "processed" in lwr or "letters processed" in lwr or "total" in lwr:
                    if str(processed_needed) in nums:
                        processed_found = True
                if "matched" in lwr or "matches" in lwr:
                    if str(matched_needed) in nums:
                        matched_found = True
            totals_ok = processed_found and matched_found
        scores["status_report_totals"] = 1.0 if totals_ok else 0.0

        # Matched bullets
        matched_bul_ok = False
        if letters_ok and defaults_ok and cfg_ok:
            lines = status_text.splitlines()
            bullet_lines = [ln for ln in lines if re.match(r'^\s*[-*]\s+', ln)]
            # For each expected match, require a bullet line that includes the ID and both sender and recipient
            need_map = {m["id"]: (m["sender"], m["recipient"]) for m in expected_matches}
            ok_all = True
            for lid, (snd, rcp) in need_map.items():
                found_line = None
                for bl in bullet_lines:
                    if (lid in bl) and (snd in bl) and (rcp in bl):
                        found_line = bl
                        break
                if not found_line:
                    ok_all = False
                    break
            matched_bul_ok = ok_all
        scores["status_report_matched_bullets"] = 1.0 if matched_bul_ok else 0.0

        # Exclusions bullets: any letters excluded due to date or keyword criteria (ID and reason)
        excl_ok = False
        if letters_ok and defaults_ok and cfg_ok:
            # Compute excluded letters due to date or keyword criteria; for our dataset, L3 is excluded due to date (and also tracked), but we require date reason
            # We'll require at least one bullet includes L3 and mentions date/year
            lines = status_text.splitlines()
            bullet_lines = [ln for ln in lines if re.match(r'^\s*[-*]\s+', ln)]
            # Identify letters excluded for date or keyword
            # Determine which letters fail date within tracked or keyword; requirement says list any letters excluded due to date or keyword criteria
            # We'll check for L3 presence and "date" or "year"
            found_excl = False
            for bl in bullet_lines:
                if "L3" in bl and (("date" in bl.lower()) or ("year" in bl.lower())):
                    found_excl = True
                    break
            excl_ok = found_excl
        scores["status_report_exclusions_bullets"] = 1.0 if excl_ok else 0.0

    # Email checks
    email_text = _read_text(email_path)
    contacts, contacts_ok = _load_contacts_csv(contacts_csv_path)
    collab_email = None
    if contacts_ok:
        for row in contacts:
            role = (row.get("role") or "").strip()
            if role.lower() == "collaborator":
                collab_email = (row.get("email") or "").strip()
                break

    headers_ok = False
    bullets_quality_ok = False
    if email_text and collab_email:
        lines = email_text.splitlines()
        # Find To and Subject lines
        to_line_idx = None
        subj_line_idx = None
        for idx, line in enumerate(lines):
            if to_line_idx is None and line.strip().lower().startswith("to:"):
                to_line_idx = idx
            elif subj_line_idx is None and line.strip().lower().startswith("subject:"):
                subj_line_idx = idx
            if to_line_idx is not None and subj_line_idx is not None:
                break
        if to_line_idx is not None and subj_line_idx is not None and to_line_idx < subj_line_idx:
            # Check To contains the collaborator email
            to_line = lines[to_line_idx]
            # Extract email after "To:"
            to_value = to_line.split(":", 1)[1].strip() if ":" in to_line else ""
            if collab_email.lower() in to_value.lower():
                # Subject includes phrase
                subj_line = lines[subj_line_idx]
                subj_value = subj_line.split(":", 1)[1] if ":" in subj_line else ""
                if "correspondence extraction update".lower() in subj_value.lower():
                    headers_ok = True
        scores["email_headers"] = 1.0 if headers_ok else 0.0

        # Body and bullets
        if subj_line_idx is not None:
            body_lines = lines[subj_line_idx + 1 :]
            # Identify bullets
            bullet_lines = [ln for ln in body_lines if re.match(r'^\s*[-*]\s+', ln)]
            # Identify first paragraph (non-empty, non-bullet lines before first bullet)
            first_para_lines = []
            for ln in body_lines:
                if re.match(r'^\s*[-*]\s+', ln):
                    break
                if ln.strip() == "":
                    # allow one blank line after subject, skip it and continue accumulating paragraph after it if not bullet
                    # We'll not accumulate blank lines in paragraph
                    continue
                first_para_lines.append(ln)
            # Conditions: 2–3 bullets, a first paragraph exists
            bullets_count_ok = 2 <= len(bullet_lines) <= 3
            first_para_ok = len(first_para_lines) >= 1
            # Content categories checks across bullets
            bullets_text = " ".join(bullet_lines).lower()
            cat_counts_ok = False
            cat_keywords_ok = False
            cat_corresp_ok = False
            # Counts: look for "match" and a number (preferably 2)
            if re.search(r'\bmatch\w*\b', bullets_text) and re.search(r'\b\d+\b', bullets_text):
                cat_counts_ok = True
            # Keywords/time window: presence of effective keywords or years
            if "experiment" in bullets_text or "observation" in bullets_text or "keyword" in bullets_text or "1675" in bullets_text or "1700" in bullets_text:
                cat_keywords_ok = True
            # Correspondents
            if "newton" in bullets_text or "hooke" in bullets_text or "halley" in bullets_text:
                cat_corresp_ok = True
            categories_satisfied = sum([1 if x else 0 for x in [cat_counts_ok, cat_keywords_ok, cat_corresp_ok]])
            bullets_quality_ok = bullets_count_ok and first_para_ok and (categories_satisfied >= 2)
        scores["email_bullets_quality"] = 1.0 if bullets_quality_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()