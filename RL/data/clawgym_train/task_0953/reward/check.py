import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_themes_yaml(path: Path):
    """
    Minimal YAML loader tailored to the provided themes.yaml structure.
    Expects:
    themes:
      theme_name:
        keywords: ["kw1", "kw2", ...]
    Returns dict: {theme_name: [keywords...]} or None on failure.
    """
    text = safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    themes_started = False
    themes = {}
    current_theme = None
    for raw in lines:
        line = raw.rstrip()
        if not themes_started:
            if re.match(r'^\s*themes:\s*$', line):
                themes_started = True
            continue
        # Expect theme names at two-space indent
        m_theme = re.match(r'^\s{2}([A-Za-z0-9_]+):\s*$', line)
        if m_theme:
            current_theme = m_theme.group(1)
            themes[current_theme] = []
            continue
        if current_theme is not None:
            m_keywords = re.match(r'^\s{4}keywords:\s*\[(.*)\]\s*$', line)
            if m_keywords:
                inside = m_keywords.group(1).strip()
                # Split by commas not inside quotes; since items are simple quoted strings, we can split by comma.
                items = []
                if inside:
                    parts = [p.strip() for p in inside.split(",")]
                    for p in parts:
                        # strip surrounding quotes
                        if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
                            p = p[1:-1]
                        items.append(p)
                themes[current_theme] = items
                continue
            # Stop if we hit next top-level or empty
            if re.match(r'^\s{2}[A-Za-z0-9_]+:\s*$', line):
                # Next theme handled next iteration
                continue
    if not themes:
        return None
    # Normalize to lower-case keywords for matching
    themes_norm = {k: [kw.strip() for kw in v if kw and kw.strip()] for k, v in themes.items()}
    return themes_norm


def build_keyword_patterns(themes: dict) -> dict:
    """
    Build case-insensitive regex patterns per theme for each keyword.
    To avoid matching inside larger words, use non-word boundaries around keyword,
    and allow a simple plural 's' at the end to match common plurals.
    """
    patterns = {}
    for theme, kws in themes.items():
        pats = []
        for kw in kws:
            kw_escaped = re.escape(kw)
            # Allow optional plural 's' at the end for simple cases
            pat = re.compile(r'(?i)(?<!\w)' + kw_escaped + r's?(?!\w)')
            pats.append(pat)
        patterns[theme] = pats
    return patterns


def split_sentences(text: str) -> list:
    if not text:
        return []
    # Normalize whitespace
    txt = re.sub(r'\s+', ' ', text).strip()
    if not txt:
        return []
    # Split on sentence-ending punctuation: period, question mark, exclamation mark
    parts = re.split(r'(?<=[.!?])\s+', txt)
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences


def parse_iso_date(d: str):
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None


def in_date_range(dstr: str, start_incl: str = "2020-03-01", end_incl: str = "2020-04-30") -> bool:
    d = parse_iso_date(dstr)
    if d is None:
        return False
    s = parse_iso_date(start_incl)
    e = parse_iso_date(end_incl)
    return s <= d <= e


def parse_notes_file(path: Path):
    """
    Parse note blocks as specified: three header lines (Date:, Source:, Type:),
    followed by one or more content lines until blank line or EOF.
    Returns a list of dicts with keys: date, source, type, content (joined string).
    """
    text = safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    results = []
    i = 0
    n = len(lines)
    while i < n:
        # seek Date:
        if not lines[i].startswith("Date:"):
            i += 1
            continue
        date_line = lines[i].strip()
        i += 1
        if i >= n or not lines[i].startswith("Source:"):
            # malformed block; skip to next line
            continue
        source_line = lines[i].strip()
        i += 1
        if i >= n or not lines[i].startswith("Type:"):
            continue
        type_line = lines[i].strip()
        i += 1
        # Collect content lines until blank line or EOF
        content_lines = []
        while i < n and lines[i].strip() != "":
            content_lines.append(lines[i].rstrip())
            i += 1
        # Skip the blank line if present
        while i < n and lines[i].strip() == "":
            i += 1
        # Extract values
        m_date = re.match(r'^Date:\s*(\d{4}-\d{2}-\d{2})\s*$', date_line)
        m_source = re.match(r'^Source:\s*(.+?)\s*$', source_line)
        m_type = re.match(r'^Type:\s*(.+?)\s*$', type_line)
        if not (m_date and m_source and m_type):
            # malformed; skip
            continue
        block = {
            "date": m_date.group(1),
            "source": m_source.group(1),
            "type": m_type.group(1),
            "content": " ".join(content_lines).strip()
        }
        results.append(block)
    return results


def compute_expected_mentions(workspace: Path):
    """
    Compute expected mentions records from inputs.
    Returns (records_list, error_flag)
    Each record dict fields:
      source_file, date, source, type, theme, sentence
    """
    cfg_path = workspace / "input" / "config" / "themes.yaml"
    notes_dir = workspace / "input" / "notes"
    policies_dir = workspace / "input" / "policies"
    state_actions_path = policies_dir / "state_actions.json"

    # Load themes
    themes = load_themes_yaml(cfg_path)
    if themes is None:
        return [], True
    patterns = build_keyword_patterns(themes)

    records = []

    # Parse notes
    if notes_dir.exists() and notes_dir.is_dir():
        for md_path in sorted(notes_dir.glob("*.md")):
            blocks = parse_notes_file(md_path)
            if blocks is None:
                return [], True
            for b in blocks:
                if not in_date_range(b.get("date", "")):
                    continue
                sentences = split_sentences(b.get("content", ""))
                for sent in sentences:
                    matched_themes = set()
                    for theme, pats in patterns.items():
                        for pat in pats:
                            if pat.search(sent):
                                matched_themes.add(theme)
                                break
                    for theme in sorted(matched_themes):
                        records.append({
                            "source_file": f"input/notes/{md_path.name}",
                            "date": b["date"],
                            "source": b["source"],
                            "type": b["type"],
                            "theme": theme,
                            "sentence": sent.strip()
                        })
    else:
        # If notes dir missing, treat as no notes (not an error per se)
        pass

    # Parse policies
    if state_actions_path.exists():
        state_actions = safe_load_json(state_actions_path)
        if not isinstance(state_actions, list):
            return [], True
        for item in state_actions:
            try:
                d = item.get("date", "")
                if not in_date_range(d):
                    continue
                excerpt = item.get("excerpt", "") or ""
                source = f"{item.get('state', '').strip()} {item.get('source_type', '').strip()}".strip()
                sentences = split_sentences(excerpt)
                for sent in sentences:
                    matched_themes = set()
                    for theme, pats in patterns.items():
                        for pat in pats:
                            if pat.search(sent):
                                matched_themes.add(theme)
                                break
                    for theme in sorted(matched_themes):
                        records.append({
                            "source_file": "input/policies/state_actions.json",
                            "date": d,
                            "source": source,
                            "type": "policy",
                            "theme": theme,
                            "sentence": sent.strip()
                        })
            except Exception:
                return [], True
    else:
        # If policies file missing, no policy records; not an error
        pass

    return records, False


def load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return None
            return rows
    except Exception:
        return None


def normalize_row_for_counter(row: dict, header_order: list):
    return tuple((k, (row.get(k, "") or "").strip()) for k in header_order)


def counts_by_key(rows: list, key: str) -> dict:
    c = Counter()
    for r in rows:
        c[r.get(key, "")] += 1
    return dict(c)


def is_desc_sorted(pairs: list) -> bool:
    # pairs: list of (key, count)
    counts = [cnt for _, cnt in pairs]
    return all(counts[i] >= counts[i+1] for i in range(len(counts)-1))


def parse_json_validation_output(path: Path):
    data = safe_load_json(path)
    if not isinstance(data, list):
        return None
    # Normalize entries
    norm = []
    for item in data:
        if not isinstance(item, dict):
            return None
        fp = item.get("file_path")
        valid = item.get("valid")
        err = item.get("error_summary")
        if fp is None or not isinstance(valid, bool) or err is None:
            return None
        norm.append({"file_path": fp, "valid": valid, "error_summary": err})
    return norm


def compute_actual_json_validity(workspace: Path):
    policies_dir = workspace / "input" / "policies"
    if not policies_dir.exists():
        return None, True
    files = sorted(policies_dir.glob("*.json"))
    results = []
    for fp in files:
        content = safe_read_text(fp)
        if content is None:
            # Treat unreadable as invalid
            results.append((fp, False))
            continue
        try:
            json.loads(content)
            results.append((fp, True))
        except Exception:
            results.append((fp, False))
    return results, False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "extracted_mentions_structure": 0.0,
        "extracted_mentions_content": 0.0,
        "themes_ranked_correct": 0.0,
        "top_sources_correct": 0.0,
        "json_validation_statuses": 0.0,
        "report_includes_required_info": 0.0,
    }

    # Expected mentions from inputs
    expected_mentions, exp_err = compute_expected_mentions(workspace)

    # Load produced mentions.csv
    mentions_path = workspace / "output" / "extracted" / "mentions.csv"
    header, produced_rows = load_csv_dicts(mentions_path)

    # Check structure
    expected_header = [
        "source_file",
        "date",
        "source",
        "type",
        "theme",
        "sentence",
    ]
    if header is not None and header == expected_header:
        scores["extracted_mentions_structure"] = 1.0
    else:
        scores["extracted_mentions_structure"] = 0.0

    # Content check
    if not exp_err and header is not None and produced_rows is not None and header == expected_header:
        # Normalize produced rows
        # Build Counter for produced and expected
        prod_counter = Counter()
        for r in produced_rows:
            # Ensure fields exist and trim
            tup = normalize_row_for_counter(r, expected_header)
            prod_counter[tup] += 1

        exp_counter = Counter()
        for r in expected_mentions:
            tup = tuple((k, (r.get(k, "") or "").strip()) for k in expected_header)
            exp_counter[tup] += 1

        if prod_counter == exp_counter:
            scores["extracted_mentions_content"] = 1.0
        else:
            scores["extracted_mentions_content"] = 0.0
    else:
        scores["extracted_mentions_content"] = 0.0

    # Themes ranked correctness
    themes_ranked_path = workspace / "output" / "summary" / "themes_ranked.csv"
    tr_rows = load_csv_rows(themes_ranked_path)
    themes_ranked_ok = False
    if tr_rows is not None and len(tr_rows) >= 2:
        # header must be exactly two columns: theme, mention_count
        if tr_rows[0] == ["theme", "mention_count"]:
            try:
                # Parse rows
                tr_data = [(row[0], int(row[1])) for row in tr_rows[1:] if len(row) >= 2]
                # Non-increasing sort
                if is_desc_sorted(tr_data):
                    # Compute counts from produced mentions.csv
                    if header == expected_header and produced_rows is not None:
                        prod_theme_counts = counts_by_key(produced_rows, "theme")
                        # Sum consistency
                        sum_counts = sum(prod_theme_counts.values())
                        if sum_counts == len(produced_rows):
                            # Compare contents
                            tr_dict = {k: v for k, v in tr_data}
                            # Must match counts from produced mentions
                            if tr_dict == prod_theme_counts:
                                # If expected available, also ensure matches expected counts
                                if not exp_err:
                                    exp_theme_counts = Counter([r["theme"] for r in expected_mentions])
                                    if dict(exp_theme_counts) == tr_dict:
                                        themes_ranked_ok = True
                                    else:
                                        themes_ranked_ok = False
                                else:
                                    themes_ranked_ok = True
            except Exception:
                themes_ranked_ok = False
    scores["themes_ranked_correct"] = 1.0 if themes_ranked_ok else 0.0

    # Top sources correctness
    top_sources_path = workspace / "output" / "summary" / "top_sources.csv"
    ts_rows = load_csv_rows(top_sources_path)
    top_sources_ok = False
    if ts_rows is not None and len(ts_rows) >= 2:
        if ts_rows[0] == ["source", "mention_count"]:
            try:
                ts_data = [(row[0], int(row[1])) for row in ts_rows[1:] if len(row) >= 2]
                if is_desc_sorted(ts_data):
                    if header == expected_header and produced_rows is not None:
                        prod_source_counts = counts_by_key(produced_rows, "source")
                        sum_counts = sum(prod_source_counts.values())
                        if sum_counts == len(produced_rows):
                            ts_dict = {k: v for k, v in ts_data}
                            if ts_dict == prod_source_counts:
                                if not exp_err:
                                    exp_source_counts = Counter([r["source"] for r in expected_mentions])
                                    if dict(exp_source_counts) == ts_dict:
                                        top_sources_ok = True
                                    else:
                                        top_sources_ok = False
                                else:
                                    top_sources_ok = True
            except Exception:
                top_sources_ok = False
    scores["top_sources_correct"] = 1.0 if top_sources_ok else 0.0

    # JSON validation statuses
    diagnostics_path = workspace / "output" / "diagnostics" / "json_validation.json"
    reported = parse_json_validation_output(diagnostics_path)
    actual_files, actual_err = compute_actual_json_validity(workspace)
    json_val_ok = False
    if (reported is not None) and (actual_files is not None) and not actual_err:
        # Map reported by filename end
        rep_map = {}
        for r in reported:
            fp = r["file_path"]
            # Normalize as Path for suffix matching
            rep_map[Path(fp).as_posix()] = (r["valid"], r["error_summary"])
        # For robustness, also map by suffix 'input/policies/filename'
        rep_suffix_map = {}
        for k, v in rep_map.items():
            rep_suffix_map[k] = v
            rep_suffix_map[Path(k).name] = v

        all_ok = True
        for fp, is_valid in actual_files:
            key_full = f"input/policies/{fp.name}"
            found = None
            if key_full in rep_suffix_map:
                found = rep_suffix_map[key_full]
            elif fp.as_posix() in rep_suffix_map:
                found = rep_suffix_map[fp.as_posix()]
            elif fp.name in rep_suffix_map:
                found = rep_suffix_map[fp.name]
            if found is None:
                all_ok = False
                break
            rep_valid, rep_err = found
            # valid must match
            if rep_valid != is_valid:
                all_ok = False
                break
            # error_summary emptiness rules
            if is_valid:
                if rep_err is None:
                    all_ok = False
                    break
                if str(rep_err) != "":
                    all_ok = False
                    break
            else:
                # invalid case: must have non-empty error summary string
                if not isinstance(rep_err, str) or rep_err.strip() == "":
                    all_ok = False
                    break
        # Also ensure no extra entries beyond policy JSON files present? Not required; ignore extras.
        json_val_ok = all_ok
    scores["json_validation_statuses"] = 1.0 if json_val_ok else 0.0

    # Report includes required info
    report_path = workspace / "output" / "report.md"
    report_text = safe_read_text(report_path)
    report_ok = False
    if report_text is not None:
        text_lower = report_text.lower()
        # Determine numbers from produced files (ensure internal consistency with their outputs)
        mentions_count = 0
        if produced_rows is not None:
            mentions_count = len(produced_rows)
        # Determine top theme and count from themes_ranked.csv
        top_theme = None
        top_theme_count = None
        if tr_rows is not None and len(tr_rows) >= 2 and tr_rows[0] == ["theme", "mention_count"]:
            try:
                first_row = tr_rows[1]
                if len(first_row) >= 2:
                    top_theme = first_row[0]
                    top_theme_count = int(first_row[1])
            except Exception:
                top_theme = None
        # Determine top source and count from top_sources.csv
        top_source = None
        top_source_count = None
        if ts_rows is not None and len(ts_rows) >= 2 and ts_rows[0] == ["source", "mention_count"]:
            try:
                first_row = ts_rows[1]
                if len(first_row) >= 2:
                    top_source = first_row[0]
                    top_source_count = int(first_row[1])
            except Exception:
                top_source = None
        # Determine invalid JSON files from diagnostics
        invalid_files = []
        if reported is not None:
            for r in reported:
                if r.get("valid") is False:
                    # collect basename
                    try:
                        invalid_files.append(Path(r.get("file_path", "")).name)
                    except Exception:
                        pass

        # Check that report contains required info
        conds = []
        # mentions count appears
        conds.append(str(mentions_count) in report_text)
        # top theme and count appear
        if top_theme is not None and top_theme_count is not None:
            conds.append(top_theme in report_text)
            conds.append(str(top_theme_count) in report_text)
        else:
            conds.append(False)
        # top source and count appear
        if top_source is not None and top_source_count is not None:
            conds.append(top_source in report_text)
            conds.append(str(top_source_count) in report_text)
        else:
            conds.append(False)
        # invalid JSON files mentioned (by basename)
        if invalid_files:
            for name in invalid_files:
                conds.append(name in report_text)
        else:
            # If no invalids, still must state none? Specification requires a brief note of which files were invalid;
            # if none invalid, presence is ambiguous. We won't require this condition strictly.
            pass

        report_ok = all(conds)
    scores["report_includes_required_info"] = 1.0 if report_ok else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()