import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_csv_file(path: Path) -> list[dict] | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows
    except Exception:
        return None


def normalize_path_str(p: str, workspace: Path) -> str:
    if p is None:
        return ""
    s = p.strip().replace("\\", "/")
    ws = str(workspace).replace("\\", "/")
    if s.startswith(ws + "/"):
        s = s[len(ws) + 1 :]
    if s.startswith("./"):
        s = s[2:]
    # Collapse redundant separators
    parts = []
    for part in s.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def count_occurrences(haystack: str, needle: str) -> int:
    # Case-insensitive non-overlapping occurrences
    h = haystack.lower()
    n = needle.lower()
    if not n:
        return 0
    count = 0
    i = 0
    while True:
        j = h.find(n, i)
        if j == -1:
            break
        count += 1
        i = j + len(n)
    return count


def compute_expected_scan(workspace: Path) -> tuple[dict, list]:
    restricted_path = workspace / "input" / "guidelines" / "restricted_terms.json"
    data = safe_load_json(restricted_path)
    if not isinstance(data, dict) or "restricted" not in data or not isinstance(data["restricted"], list):
        return {}, []
    restricted_terms = [str(t) for t in data["restricted"]]

    search_dirs = [
        workspace / "input" / "materials",
        workspace / "input" / "agreements",
    ]
    files_to_scan: list[Path] = []
    for d in search_dirs:
        if d.exists() and d.is_dir():
            for p in d.rglob("*"):
                if p.is_file() and p.suffix.lower() in (".md", ".txt"):
                    files_to_scan.append(p)

    expected_counts: dict[tuple[str, str], int] = defaultdict(int)
    expected_snippets: list[tuple[str, int, str]] = []

    for file_path in files_to_scan:
        text = safe_read_text(file_path)
        if text is None:
            continue
        rel_norm = normalize_path_str(str(file_path), workspace)
        lines = text.splitlines()
        for line_no, line in enumerate(lines, start=1):
            for term in restricted_terms:
                c = count_occurrences(line, term)
                if c > 0:
                    expected_counts[(rel_norm, term)] += c
                    # Add one snippet per match (duplicates allowed)
                    for _ in range(c):
                        expected_snippets.append((rel_norm, line_no, line))
    # Reduce counts to per-file-per-term (nonzero only)
    # expected_counts already only counts matches; zero entries will not exist.
    return expected_counts, expected_snippets


def parse_flagged_snippets(path: Path, workspace: Path) -> list[tuple[str, int, str]] | None:
    text = safe_read_text(path)
    if text is None:
        return None
    results: list[tuple[str, int, str]] = []
    for raw_line in text.splitlines():
        # Expect format: file_path:line_number:line_text (line_text may contain colons)
        parts = raw_line.split(":", 2)
        if len(parts) < 3:
            return None
        p_str, ln_str, l_text = parts[0].strip(), parts[1].strip(), parts[2]
        try:
            ln = int(ln_str)
        except Exception:
            return None
        norm = normalize_path_str(p_str, workspace)
        results.append((norm, ln, l_text))
    return results


def find_section_indices(lines: list[str], section_name: str) -> int | None:
    # Match lines that are headings for the required section: optional leading '#' and spaces, then exact name
    pattern = re.compile(rf"^\s*#*\s*{re.escape(section_name)}\s*$")
    for idx, line in enumerate(lines):
        if pattern.match(line):
            return idx
    return None


def extract_section(lines: list[str], start_idx: int, end_idx: int | None) -> list[str]:
    if end_idx is None:
        return lines[start_idx + 1 :]
    return lines[start_idx + 1 : end_idx]


def extract_quoted_attributions(section_lines: list[str]) -> list[tuple[str, str]]:
    # Return list of (quoted_text, src_path)
    results: list[tuple[str, str]] = []
    # Match "Sentence." (path) with straight or curly double quotes
    pattern = re.compile(r'["“](.+?)["”]\s*\(([^)]+)\)\s*$')
    for line in section_lines:
        m = pattern.search(line.strip())
        if m:
            quoted = m.group(1).strip()
            src = m.group(2).strip()
            results.append((quoted, src))
    return results


def text_contains_sentence_verbatim(source_text: str, sentence: str) -> bool:
    # Check if sentence appears verbatim in source_text
    if not sentence:
        return False
    return sentence in source_text


def check_compliance_section(
    workspace: Path,
    findings_path: Path,
    section_name: str,
    keyword_rule: str,
) -> float:
    """
    keyword_rule: one of 'minors', 'alcohol', 'trademarks'
    """
    findings_text = safe_read_text(findings_path)
    if findings_text is None:
        return 0.0
    lines = findings_text.splitlines()

    idx1 = find_section_indices(lines, section_name)
    if idx1 is None:
        return 0.0
    # Find next section header among the three known section names
    section_names = ["Youth/Minors", "Alcohol/Safety", "Trademarks/Branding"]
    following_indices = []
    for name in section_names:
        idx = find_section_indices(lines, name)
        if idx is not None and idx > idx1:
            following_indices.append(idx)
    end_idx = min(following_indices) if following_indices else None

    section_lines = extract_section(lines, idx1, end_idx)
    quoted = extract_quoted_attributions(section_lines)
    if len(quoted) != 2:
        return 0.0

    # Validate one from each source and keyword presence
    mou_path = normalize_path_str("input/agreements/sponsorship_MOU.md", workspace)
    pol_path = normalize_path_str("input/policies/school_policy.md", workspace)

    seen_sources = set()
    for sentence, src in quoted:
        src_norm = normalize_path_str(src, workspace)
        # Sentence-like: ends with . ! or ?
        if not re.search(r"[.!?]$", sentence):
            return 0.0
        # Keyword check
        s_lower = sentence.lower()
        if keyword_rule == "minors":
            if "minor" not in s_lower:
                return 0.0
        elif keyword_rule == "alcohol":
            if "alcohol" not in s_lower:
                return 0.0
        elif keyword_rule == "trademarks":
            if not ("trademark" in s_lower or "super bowl" in s_lower or "nfl" in s_lower):
                return 0.0
        else:
            return 0.0

        # Source check and verbatim presence
        if src_norm not in {mou_path, pol_path}:
            return 0.0
        if src_norm in seen_sources:
            return 0.0
        seen_sources.add(src_norm)

        src_file = workspace / src_norm
        src_text = safe_read_text(src_file)
        if src_text is None:
            return 0.0
        if not text_contains_sentence_verbatim(src_text, sentence):
            return 0.0

    # Ensure we have one from each
    if seen_sources != {mou_path, pol_path}:
        return 0.0
    return 1.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "scan_script_exists": 0.0,
        "flagged_terms_csv_correct": 0.0,
        "flagged_snippets_txt_correct": 0.0,
        "compliance_findings_sections_order": 0.0,
        "compliance_findings_youth_content": 0.0,
        "compliance_findings_alcohol_content": 0.0,
        "compliance_findings_trademarks_content": 0.0,
        "press_release_includes_date_time": 0.0,
        "press_release_no_restricted_terms": 0.0,
        "press_release_word_count_limit": 0.0,
        "press_release_ends_with_disclaimer": 0.0,
        "readme_present_and_paragraph": 0.0,
        "readme_includes_command": 0.0,
    }

    # 1) Scan terms: check script existence
    scan_script = workspace / "tools" / "scan_terms.py"
    if scan_script.exists() and scan_script.is_file():
        scores["scan_script_exists"] = 1.0

    # Compute expected scan results
    expected_counts, expected_snippets = compute_expected_scan(workspace)

    # Validate flagged_terms.csv
    flagged_terms_csv = workspace / "output" / "flagged_terms.csv"
    rows = parse_csv_file(flagged_terms_csv) if flagged_terms_csv.exists() else None
    if rows is not None:
        # Expect columns: file_path, term, count
        ok = True
        # Load restricted to validate terms are from the list
        restricted_data = safe_load_json(workspace / "input" / "guidelines" / "restricted_terms.json")
        restricted_terms = []
        if isinstance(restricted_data, dict) and isinstance(restricted_data.get("restricted"), list):
            restricted_terms = [str(t) for t in restricted_data["restricted"]]
        # Build mapping
        found_counts: dict[tuple[str, str], int] = defaultdict(int)
        for r in rows:
            if not {"file_path", "term", "count"} <= set(r.keys()):
                ok = False
                break
            term = r["term"]
            if term not in restricted_terms:
                ok = False
                break
            try:
                count_val = int(r["count"])
            except Exception:
                ok = False
                break
            norm_path = normalize_path_str(r["file_path"], workspace)
            found_counts[(norm_path, term)] += count_val
        # Compare found_counts to expected_counts (exact match)
        if ok and expected_counts and dict(found_counts) == expected_counts:
            scores["flagged_terms_csv_correct"] = 1.0
        elif ok and not expected_counts and dict(found_counts) == {}:
            # No matches expected and none found
            scores["flagged_terms_csv_correct"] = 1.0
        else:
            scores["flagged_terms_csv_correct"] = 0.0
    else:
        scores["flagged_terms_csv_correct"] = 0.0

    # Validate flagged_snippets.txt
    flagged_snippets_txt = workspace / "output" / "flagged_snippets.txt"
    parsed_snips = parse_flagged_snippets(flagged_snippets_txt, workspace) if flagged_snippets_txt.exists() else None
    if parsed_snips is not None:
        # Compare as multisets
        expected_counter = Counter(expected_snippets)
        parsed_counter = Counter(parsed_snips)
        if expected_counter == parsed_counter:
            scores["flagged_snippets_txt_correct"] = 1.0
        else:
            scores["flagged_snippets_txt_correct"] = 0.0
    else:
        scores["flagged_snippets_txt_correct"] = 0.0

    # 2) Compliance findings
    findings_path = workspace / "output" / "compliance_findings.md"
    findings_text = safe_read_text(findings_path)
    if findings_text is not None:
        lines = findings_text.splitlines()
        idx_youth = find_section_indices(lines, "Youth/Minors")
        idx_alc = find_section_indices(lines, "Alcohol/Safety")
        idx_tm = find_section_indices(lines, "Trademarks/Branding")
        if idx_youth is not None and idx_alc is not None and idx_tm is not None:
            if idx_youth < idx_alc < idx_tm:
                scores["compliance_findings_sections_order"] = 1.0

        # Youth
        scores["compliance_findings_youth_content"] = check_compliance_section(
            workspace, findings_path, "Youth/Minors", "minors"
        )
        # Alcohol
        scores["compliance_findings_alcohol_content"] = check_compliance_section(
            workspace, findings_path, "Alcohol/Safety", "alcohol"
        )
        # Trademarks/Branding
        scores["compliance_findings_trademarks_content"] = check_compliance_section(
            workspace, findings_path, "Trademarks/Branding", "trademarks"
        )

    # 3) Press release clean
    pr_clean_path = workspace / "output" / "press_release_clean.txt"
    pr_text = safe_read_text(pr_clean_path)
    if pr_text is not None:
        # Date and time preservation
        if ("Friday, Sept 20" in pr_text) and ("7:00 PM" in pr_text):
            scores["press_release_includes_date_time"] = 1.0

        # No restricted terms
        restricted_data = safe_load_json(workspace / "input" / "guidelines" / "restricted_terms.json")
        no_terms = False
        if isinstance(restricted_data, dict) and isinstance(restricted_data.get("restricted"), list):
            restricted_terms = [str(t) for t in restricted_data["restricted"]]
            text_lower = pr_text.lower()
            if not any(t.lower() in text_lower for t in restricted_terms):
                no_terms = True
        scores["press_release_no_restricted_terms"] = 1.0 if no_terms else 0.0

        # Word count <= 120
        words = re.findall(r"\S+", pr_text.strip())
        if len(words) <= 120:
            scores["press_release_word_count_limit"] = 1.0

        # Ends with exact disclaimer
        disclaimer_path = workspace / "input" / "checklist" / "required_disclaimer.txt"
        disc_text = safe_read_text(disclaimer_path)
        if disc_text is not None:
            pr_trim = pr_text.rstrip()
            disc_trim = disc_text.strip()
            if pr_trim.endswith(disc_trim):
                scores["press_release_ends_with_disclaimer"] = 1.0

    # 4) README.txt
    readme_path = workspace / "output" / "README.txt"
    readme_text = safe_read_text(readme_path)
    if readme_text is not None:
        # One paragraph: no blank lines between content
        lines = readme_text.splitlines()
        # A paragraph is non-empty content with no blank-only separator lines
        # We'll consider "one paragraph" if there's no empty line among non-leading/trailing whitespace.
        if "" not in [ln.strip() for ln in lines]:
            # non-empty
            if any(ln.strip() for ln in lines):
                scores["readme_present_and_paragraph"] = 1.0
        # Includes exact command used with python and tools/scan_terms.py
        pattern = re.compile(r"\bpython(3)?\b[^\n]*tools/scan_terms\.py")
        if pattern.search(readme_text):
            scores["readme_includes_command"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()