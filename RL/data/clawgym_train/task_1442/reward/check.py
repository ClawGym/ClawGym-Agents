import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def read_text_safe(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_csv_dicts_safe(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def parse_markdown_sections(md_text: str) -> List[Tuple[str, int, int]]:
    """
    Return list of (section_title, start_index, end_index) where indices are line indices (start inclusive, end exclusive)
    """
    lines = md_text.splitlines()
    headers = []
    for i, line in enumerate(lines):
        m = re.match(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", line)
        if m:
            headers.append((m.group(1).strip(), i))
    sections = []
    for idx, (title, start_line) in enumerate(headers):
        end_line = len(lines)
        if idx + 1 < len(headers):
            end_line = headers[idx + 1][1]
        sections.append((title, start_line, end_line))
    return sections


def get_section_text(md_text: str, section_name_candidates: List[str]) -> Optional[str]:
    sections = parse_markdown_sections(md_text)
    lines = md_text.splitlines()
    for title, start, end in sections:
        normalized_title = title.lower().strip()
        for cand in section_name_candidates:
            if cand.lower() in normalized_title:
                # Exclude the header line itself in content
                content = "\n".join(lines[start + 1:end]).strip()
                return content
    return None


def count_bullets(text: str) -> int:
    if text is None:
        return 0
    count = 0
    for line in text.splitlines():
        if re.match(r"^\s*[-\*]\s+", line):
            count += 1
    return count


def extract_articles_from_md(md_text: str) -> List[Dict]:
    lines = md_text.splitlines()
    articles = []
    current = None
    for line in lines:
        m = re.match(r"^##\s+Article\s+(\d+):\s*(.+)$", line.strip())
        if m:
            if current:
                current['text'] = current['text'].strip()
                articles.append(current)
            current = {
                'article_number': int(m.group(1)),
                'article_title': m.group(2).strip(),
                'text': ''
            }
        else:
            if current is not None:
                current['text'] += (line + "\n")
    if current:
        current['text'] = current['text'].strip()
        articles.append(current)
    return articles


def parse_article_blocks(critique_text: str) -> Dict[int, str]:
    """
    Split the critique's 'Per-Article' content by occurrences of 'Article <num>' and return mapping num->block text
    """
    # Normalize non-breaking hyphens etc.
    text = critique_text
    # Find all occurrences
    matches = list(re.finditer(r"Article\s+(\d+)", text, flags=re.IGNORECASE))
    blocks = {}
    if not matches:
        return blocks
    for i, m in enumerate(matches):
        num = int(m.group(1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks[num] = text[start:end].strip()
    return blocks


def tokenize_statute_refs(ref: str) -> List[str]:
    if not ref:
        return []
    parts = re.split(r"[,\s;\|]+", ref.strip())
    return [p for p in parts if p]


def find_statute_ids_in_text(text: str, valid_ids: set) -> List[str]:
    # Extract tokens that look like uppercase letters + hyphen + digits (e.g., PRIV-001)
    found = set()
    # Build a regex that matches any of the known IDs to be strict
    # If too many, fallback to generic pattern then filter
    if len(valid_ids) > 0 and len("|".join(map(re.escape, valid_ids))) < 2000:
        pattern = r"\b(" + "|".join(map(re.escape, sorted(valid_ids))) + r")\b"
        for m in re.finditer(pattern, text):
            found.add(m.group(1))
    else:
        for m in re.finditer(r"\b[A-Z]{2,,}-\d{3}\b", text):
            if m.group(0) in valid_ids:
                found.add(m.group(0))
    return sorted(found)


def safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def round_two(x: float) -> float:
    return float(f"{x:.2f}")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "extracted_file_exists": 0.0,
        "extracted_article_min_count": 0.0,
        "extracted_fields_complete": 0.0,
        "extracted_matches_source": 0.0,
        "critique_has_required_sections": 0.0,
        "critique_exec_summary_bullet_count_valid": 0.0,
        "critique_per_article_includes_all_required": 0.0,
        "critique_article_1_compliance_and_citations": 0.0,
        "critique_article_1_risk_score_consistent": 0.0,
        "critique_article_2_compliance_and_citations": 0.0,
        "critique_article_2_risk_score_consistent": 0.0,
        "critique_article_3_compliance_and_citations": 0.0,
        "critique_article_3_risk_score_consistent": 0.0,
        "critique_article_4_compliance_and_citations": 0.0,
        "critique_article_4_risk_score_consistent": 0.0,
        "critique_article_5_compliance_and_citations": 0.0,
        "critique_article_5_risk_score_consistent": 0.0,
        "critique_article_6_compliance_and_citations": 0.0,
        "critique_article_6_risk_score_consistent": 0.0,
        "issues_csv_has_required_header": 0.0,
        "issues_csv_min_three_issues": 0.0,
        "issues_csv_statute_refs_valid": 0.0,
        "issues_csv_articles_align_with_extracted": 0.0,
        "meeting_notes_required_sections_present": 0.0,
        "meeting_notes_min_five_action_items": 0.0,
        "meeting_notes_action_owners_valid": 0.0,
        "meeting_notes_action_article_refs_present": 0.0,
        "meeting_notes_amendment_language_present": 0.0,
        "validator_parity_checks_pass": 0.0,
    }

    # Paths
    extracted_path = workspace / "workspace" / "extracted_clauses.json"
    critique_path = workspace / "workspace" / "treaty_critique.md"
    issues_path = workspace / "workspace" / "issues.csv"
    notes_path = workspace / "workspace" / "meeting_notes.md"
    md_source_path = workspace / "input" / "draft_treaty.md"
    statutes_path = workspace / "input" / "domestic_statutes.csv"
    risk_matrix_path = workspace / "input" / "risk_matrix.json"

    # Load inputs
    extracted = load_json_safe(extracted_path)
    md_source = read_text_safe(md_source_path)
    statutes_rows = read_csv_dicts_safe(statutes_path)
    risk_matrix = load_json_safe(risk_matrix_path)

    # Extracted file checks
    if extracted is not None:
        scores["extracted_file_exists"] = 1.0
        if isinstance(extracted, list) and len(extracted) >= 6:
            scores["extracted_article_min_count"] = 1.0
        # fields complete
        fields_ok = True
        if isinstance(extracted, list) and extracted:
            for item in extracted:
                if not (isinstance(item, dict) and 'article_number' in item and 'article_title' in item and 'text' in item):
                    fields_ok = False
                    break
            if fields_ok:
                scores["extracted_fields_complete"] = 1.0
    # Compare against source by re-extracting
    if md_source is not None and extracted is not None and isinstance(extracted, list):
        expected_articles = extract_articles_from_md(md_source)
        # Strict match: same count and same sequence of numbers and titles and text
        def normalize_text(t: str) -> str:
            return t.strip().replace("\r\n", "\n").replace("\r", "\n")
        match = True
        if len(expected_articles) != len(extracted):
            match = False
        else:
            for a, b in zip(expected_articles, extracted):
                if a.get('article_number') != b.get('article_number'):
                    match = False
                    break
                if a.get('article_title') != b.get('article_title'):
                    match = False
                    break
                if normalize_text(a.get('text', '')) != normalize_text(b.get('text', '')):
                    match = False
                    break
        if match:
            scores["extracted_matches_source"] = 1.0

    # Load critique
    critique_text = read_text_safe(critique_path)
    # Required sections presence
    if critique_text is not None:
        # Allow both hyphen and non-breaking hyphen variants in section names
        per_article_candidates = ["Per-Article Assessment", "Per‑Article Assessment", "Per ‑ Article Assessment"]
        exec_sum = get_section_text(critique_text, ["Executive Summary"])
        per_article = get_section_text(critique_text, per_article_candidates)
        if exec_sum is not None and per_article is not None:
            scores["critique_has_required_sections"] = 1.0
        # Executive Summary bullets count 3-7
        if exec_sum is not None:
            bullets = count_bullets(exec_sum)
            if 3 <= bullets <= 7:
                scores["critique_exec_summary_bullet_count_valid"] = 1.0

    # Per-Article checks
    # Required article-topic mapping for risk severity checks
    expected_article_topics = {
        1: "Data Sharing",
        2: "Privacy",
        3: "Reciprocity",
        4: "Oversight",
        5: "Dispute",
        6: "Verification",
    }
    # Gather statutes set
    statute_ids = set()
    if statutes_rows:
        for r in statutes_rows:
            sid = (r.get("statute_id") or "").strip()
            if sid:
                statute_ids.add(sid)
    # Risk severity lookup and allowed likelihoods
    severity_map = {}
    allowed_likelihoods = set()
    if risk_matrix and isinstance(risk_matrix, dict):
        severity_map = risk_matrix.get("severity_by_topic", {}) or {}
        lh = risk_matrix.get("likelihood_heuristics", {}) or {}
        defaults = lh.get("default_likelihood_values", {}) or {}
        for k in ("explicit", "ambiguous", "missing"):
            v = defaults.get(k)
            if isinstance(v, (int, float)):
                allowed_likelihoods.add(float(v))

    # Parse per-article blocks from entire critique (not just section), to be more robust
    article_blocks = {}
    if critique_text is not None:
        article_blocks = parse_article_blocks(critique_text)
        # Ensure all required articles 1-6 are present in critique
        required_present = all(n in article_blocks for n in expected_article_topics.keys())
        if required_present:
            scores["critique_per_article_includes_all_required"] = 1.0

    def check_article_compliance_and_citations(n: int) -> float:
        block = article_blocks.get(n, "")
        if not block:
            return 0.0
        # Compliance keyword
        if not re.search(r"\b(Aligned|Conflict|Ambiguous)\b", block):
            return 0.0
        # Must include at least one known statute_id
        found_ids = find_statute_ids_in_text(block, statute_ids)
        if not found_ids:
            return 0.0
        return 1.0

    def check_article_risk_consistency(n: int) -> float:
        block = article_blocks.get(n, "")
        if not block or not severity_map or not allowed_likelihoods:
            return 0.0
        # Parse risk_score numeric in block
        m = re.search(r"risk[_\s\-]*score\s*[:=]\s*([0-9]*\.?[0-9]+)", block, flags=re.IGNORECASE)
        if not m:
            return 0.0
        rs = safe_float(m.group(1))
        if rs is None:
            return 0.0
        if rs < 0.0 or rs > 1.0:
            return 0.0
        # Ensure block mentions 'likelihood' to evidence rationale
        if not re.search(r"\blikelihood\b", block, flags=re.IGNORECASE):
            return 0.0
        # Compute expected severity for this article
        topic = expected_article_topics.get(n)
        if topic not in severity_map:
            return 0.0
        sev = float(severity_map[topic])
        # Check if rs equals sev * some allowed likelihood rounded to two decimals
        ok = False
        for lkh in sorted(allowed_likelihoods):
            expected = round_two(sev * float(lkh))
            if abs(expected - float(f"{rs:.2f}")) < 1e-9:
                ok = True
                break
        return 1.0 if ok else 0.0

    # Apply per-article checks
    for n in range(1, 7):
        key_comp = f"critique_article_{n}_compliance_and_citations"
        key_risk = f"critique_article_{n}_risk_score_consistent"
        scores[key_comp] = check_article_compliance_and_citations(n)
        scores[key_risk] = check_article_risk_consistency(n)

    # Issues CSV checks
    issues_rows = None
    issues_header_ok = False
    issues_min_ok = False
    issues_statutes_ok = False
    issues_article_align_ok = False
    if issues_path.exists():
        try:
            with issues_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = [h.strip() for h in rows[0]]
                required_headers = ['article_number', 'article_title', 'issue_type', 'statute_ref', 'risk_score', 'summary']
                issues_header_ok = all(h in header for h in required_headers)
                if issues_header_ok:
                    idx = {h: header.index(h) for h in required_headers}
                    if len(rows) >= 4:
                        issues_min_ok = True
                    # Load extracted articles map for alignment
                    art_map = {}
                    if isinstance(extracted, list):
                        for a in extracted:
                            try:
                                art_map[int(a.get("article_number"))] = a.get("article_title", "")
                            except Exception:
                                pass
                    all_stat_ok = True
                    all_article_align = True
                    for r in rows[1:]:
                        # risk_score numeric in [0,1]
                        try:
                            rs = float(r[idx['risk_score']])
                        except Exception:
                            all_stat_ok = False
                            all_article_align = False
                            break
                        if not (0.0 <= rs <= 1.0):
                            all_stat_ok = False
                            all_article_align = False
                            break
                        # statute_ref tokens must all be valid IDs
                        refs = tokenize_statute_refs(r[idx['statute_ref']])
                        if not refs:
                            all_stat_ok = False
                            break
                        if statute_ids and not all(ref in statute_ids for ref in refs):
                            all_stat_ok = False
                            break
                        # article alignment
                        art_num_str = r[idx['article_number']].strip()
                        art_title = r[idx['article_title']].strip()
                        if not art_num_str.isdigit():
                            all_article_align = False
                            break
                        art_num = int(art_num_str)
                        expected_title = art_map.get(art_num)
                        if not expected_title or art_title != expected_title:
                            all_article_align = False
                            break
                        # issue_type should indicate conflict or ambiguity (non-trivial)
                        issue_type = r[idx['issue_type']].strip().lower()
                        if not any(term in issue_type for term in ["conflict", "ambiguous", "ambiguity"]):
                            all_stat_ok = False
                            break
                        # summary non-empty
                        if not r[idx['summary']].strip():
                            all_stat_ok = False
                            break
                    issues_statutes_ok = 1.0 if all_stat_ok else 0.0
                    issues_article_align_ok = 1.0 if all_article_align else 0.0
        except Exception:
            pass

    scores["issues_csv_has_required_header"] = 1.0 if issues_header_ok else 0.0
    scores["issues_csv_min_three_issues"] = 1.0 if issues_min_ok else 0.0
    scores["issues_csv_statute_refs_valid"] = float(issues_statutes_ok) if isinstance(issues_statutes_ok, float) else (1.0 if issues_statutes_ok else 0.0)
    scores["issues_csv_articles_align_with_extracted"] = float(issues_article_align_ok) if isinstance(issues_article_align_ok, float) else (1.0 if issues_article_align_ok else 0.0)

    # Meeting notes checks
    notes_text = read_text_safe(notes_path)
    if notes_text is not None:
        # Required sections
        req_sections = ["Action Items", "Decisions Needed", "Open Questions", "Follow-ups", "Follow‑ups"]
        has_all = all(s in notes_text for s in ["Action Items", "Decisions Needed", "Open Questions"]) and (("Follow-ups" in notes_text) or ("Follow‑ups" in notes_text))
        if has_all:
            scores["meeting_notes_required_sections_present"] = 1.0
        # Action items: count Owners and Article refs
        # Extract Action Items section content
        action_section = get_section_text(notes_text, ["Action Items"])
        owners_ok = False
        articles_ok = False
        amend_ok = False
        count_items = 0
        if action_section is not None:
            # Split by lines and find lines with Owner:
            owner_lines = [ln for ln in action_section.splitlines() if "Owner:" in ln]
            count_items = len(owner_lines)
            # Validate owner role choices
            allowed_roles = {"Lead Negotiator", "Legal Counsel", "Technical Liaison"}
            owners_ok = True if owner_lines else False
            for ln in owner_lines:
                m = re.search(r"Owner:\s*([^|,\n]+)", ln)
                if not m:
                    owners_ok = False
                    break
                role = m.group(1).strip()
                if role not in allowed_roles:
                    owners_ok = False
                    break
            # Article references in section
            articles_ok = bool(re.search(r"\bArticle\s+\d+\b", action_section))
            # Amendment language presence: look for 'amend' in section (case-insensitive)
            amend_ok = bool(re.search(r"\bamend", action_section, flags=re.IGNORECASE))
        # At least 5 action items
        if count_items >= 5:
            scores["meeting_notes_min_five_action_items"] = 1.0
        if owners_ok:
            scores["meeting_notes_action_owners_valid"] = 1.0
        if articles_ok:
            scores["meeting_notes_action_article_refs_present"] = 1.0
        if amend_ok:
            scores["meeting_notes_amendment_language_present"] = 1.0

    # Validator parity checks (mirror tools/validate.py structural checks)
    validator_ok = False
    try:
        # Check extracted
        if not extracted_path.exists():
            raise AssertionError("missing extracted")
        data = load_json_safe(extracted_path)
        if not isinstance(data, list) or len(data) < 6:
            raise AssertionError("bad extracted len")
        for i, item in enumerate(data):
            for k in ['article_number', 'article_title', 'text']:
                if k not in item:
                    raise AssertionError("missing key")
        # Check critique basic
        if critique_text is None or ("Executive Summary" not in critique_text):
            raise AssertionError("critique missing Executive Summary")
        # Ensure at least one article title appears in critique
        titles_ok = False
        if isinstance(data, list):
            for a in data:
                if a.get('article_title') and a.get('article_title') in critique_text:
                    titles_ok = True
                    break
        if not titles_ok:
            raise AssertionError("critique lacks article title")
        # Check issues.csv basic
        if not issues_path.exists():
            raise AssertionError("issues.csv missing")
        with issues_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            raise AssertionError("issues empty")
        header = [h.strip() for h in rows[0]]
        required_headers = ['article_number', 'article_title', 'issue_type', 'statute_ref', 'risk_score', 'summary']
        for h in required_headers:
            if h not in header:
                raise AssertionError("issues header missing")
        if len(rows) < 4:
            raise AssertionError("issues need at least 3 rows")
        idx = {h: header.index(h) for h in required_headers}
        for r in rows[1:]:
            rs = float(r[idx['risk_score']])
            if rs < 0 or rs > 1:
                raise AssertionError("risk out of range")
            if not r[idx['article_number']].strip() or not r[idx['article_title']].strip():
                raise AssertionError("missing article fields")
            if not r[idx['statute_ref']].strip():
                raise AssertionError("missing statute ref")
            if not r[idx['summary']].strip():
                raise AssertionError("missing summary")
        # Check meeting notes basic
        if notes_text is None:
            raise AssertionError("meeting notes missing")
        if "Action Items" not in notes_text:
            raise AssertionError("notes missing Action Items")
        if "Owner:" not in notes_text:
            raise AssertionError("notes missing Owner")
        if "Article" not in notes_text:
            raise AssertionError("notes missing Article ref")
        validator_ok = True
    except Exception:
        validator_ok = False

    scores["validator_parity_checks_pass"] = 1.0 if validator_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()