import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Any]:
    try:
        txt = read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the specific disclosure_rules.yaml structure:
    keys:
      - allowed_tag: string
      - prohibited_phrases: list of strings
      - required_disclaimer: string (may be quoted)
    """
    text = read_text(path)
    if text is None:
        return None
    result: Dict[str, Any] = {"allowed_tag": None, "prohibited_phrases": [], "required_disclaimer": None}
    lines = [ln.rstrip() for ln in text.splitlines()]
    current_key = None
    try:
        for ln in lines:
            if not ln.strip():
                continue
            if re.match(r"^\s*#", ln):
                continue
            if re.match(r"^\s*prohibited_phrases\s*:", ln):
                current_key = "prohibited_phrases"
                continue
            m_kv = re.match(r"^\s*([A-Za-z_]+)\s*:\s*(.*)$", ln)
            if m_kv:
                key, val = m_kv.groups()
                if key == "allowed_tag":
                    result["allowed_tag"] = val.strip().strip('"').strip("'")
                    current_key = None
                elif key == "required_disclaimer":
                    result["required_disclaimer"] = val.strip().strip('"').strip("'")
                    current_key = None
                elif key == "prohibited_phrases":
                    current_key = "prohibited_phrases"
                else:
                    current_key = None
                continue
            if current_key == "prohibited_phrases":
                m_item = re.match(r"^\s*-\s*(.+)\s*$", ln)
                if m_item:
                    item = m_item.group(1).strip().strip('"').strip("'")
                    result["prohibited_phrases"].append(item)
        if not isinstance(result.get("prohibited_phrases"), list):
            return None
        if result.get("allowed_tag") is None or result.get("required_disclaimer") is None:
            return None
        return result
    except Exception:
        return None


def parse_comms_config(path: Path) -> Optional[Dict[str, Any]]:
    """
    Execute the config python file in a restricted namespace and read constants.
    """
    text = read_text(path)
    if text is None:
        return None
    ns: Dict[str, Any] = {}
    try:
        exec(text, {}, ns)
    except Exception:
        return None
    keys = ["INCLUDE_SOURCE_LINE_NUMBERS", "MAX_QUOTE_CHARS", "INCLUDE_MATCHED_KEYWORDS"]
    for k in keys:
        if k not in ns:
            return None
    try:
        return {
            "INCLUDE_SOURCE_LINE_NUMBERS": bool(ns["INCLUDE_SOURCE_LINE_NUMBERS"]),
            "MAX_QUOTE_CHARS": int(ns["MAX_QUOTE_CHARS"]),
            "INCLUDE_MATCHED_KEYWORDS": bool(ns["INCLUDE_MATCHED_KEYWORDS"]),
        }
    except Exception:
        return None


def parse_allegations_md(path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Parse markdown containing bullet lines:
    - Allegation n: text
    Return list of dicts: {id: int, full_line_text: str, content_text: str}
    """
    text = read_text(path)
    if text is None:
        return None
    lines = [ln.strip() for ln in text.splitlines()]
    allegations: List[Dict[str, Any]] = []
    for ln in lines:
        if ln.startswith("- "):
            full = ln[2:].strip()
            m = re.match(r"^Allegation\s+(\d+)\s*:\s*(.+)$", full)
            if not m:
                continue
            aid = int(m.group(1))
            content = m.group(2).strip()
            allegations.append({"id": aid, "full_line_text": full, "content_text": content})
    if not allegations:
        return None
    return allegations


def parse_memos_talking_points(path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Parse talking points file with lines: [tag] content
    Return list of dicts: {tag: str, content: str, line_number: int}
    """
    text = read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    memos: List[Dict[str, Any]] = []
    for idx, ln in enumerate(lines, start=1):
        m = re.match(r"^\s*\[([A-Za-z0-9_]+)\]\s*(.+)\s*$", ln)
        if not m:
            continue
        tag = m.group(1).strip()
        content = m.group(2).strip()
        memos.append({"tag": tag, "content": content, "line_number": idx})
    return memos


def tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9]+", text.lower())


def compute_overlap(a_text: str, b_text: str, stopwords: set) -> List[str]:
    a_tokens = [t for t in tokenize(a_text) if t not in stopwords]
    b_tokens = [t for t in tokenize(b_text) if t not in stopwords]
    overlap = sorted(set(a_tokens).intersection(set(b_tokens)))
    return overlap


def apply_redaction(text: str, phrases: List[str]) -> str:
    redacted = text
    for phrase in phrases:
        if not phrase:
            continue
        pattern = re.compile(re.escape(phrase), flags=re.IGNORECASE)
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def expected_redacted_truncated(text: str, phrases: List[str], max_chars: int) -> str:
    redacted = apply_redaction(text, phrases)
    return redacted[:max_chars]


def build_expected_quote_map(memos: List[Dict[str, Any]], phrases: List[str], max_chars: int, allowed_tag: str) -> Dict[str, List[int]]:
    """
    Map expected redacted+truncated quotes to line numbers for allowed_tag lines.
    """
    map_q: Dict[str, List[int]] = {}
    for entry in memos:
        if entry["tag"] != allowed_tag:
            continue
        expected = expected_redacted_truncated(entry["content"], phrases, max_chars)
        map_q.setdefault(expected, []).append(entry["line_number"])
    return map_q


def contains_unredacted_prohibited(text: str, phrases: List[str]) -> bool:
    for phrase in phrases:
        if not phrase:
            continue
        if re.search(re.escape(phrase), text, flags=re.IGNORECASE):
            return True
    return False


def parse_md_sections(md_text: str) -> List[str]:
    lines = [ln.rstrip() for ln in md_text.splitlines()]
    return lines


def find_section_indices(md_lines: List[str], targets: List[Tuple[str, str]]) -> List[int]:
    """
    Given md lines and list of tuples (full_line_text, content_text) for allegations in order,
    find start indices of sections, matching either full_line_text exactly or content_text exactly.
    Returns indices in order; -1 if not found.
    """
    indices: List[int] = []
    start_search = 0
    for full_text, content_text in targets:
        idx_found = -1
        for i in range(start_search, len(md_lines)):
            ln = md_lines[i].strip()
            if not ln:
                continue
            if ln == full_text or ln == content_text:
                idx_found = i
                start_search = i + 1
                break
        indices.append(idx_found)
    return indices


def extract_bullets(md_lines: List[str], start_idx: int, end_idx: Optional[int]) -> List[str]:
    """
    Extract bullet lines between start_idx (exclusive) and end_idx (exclusive).
    bullet markers considered: "- " or "* "
    Stops at blank line.
    """
    bullets: List[str] = []
    if start_idx < 0:
        return bullets
    i = start_idx + 1
    while i < (end_idx if end_idx is not None else len(md_lines)):
        ln = md_lines[i]
        if not ln.strip():
            break
        if ln.strip().startswith("- ") or ln.strip().startswith("* "):
            bullets.append(ln.strip())
        i += 1
    return bullets


def parse_md_bullet_quote_and_line(bullet: str) -> Tuple[str, Optional[int]]:
    """
    Parse bullet content to extract quote and optional (line N).
    Expected format: "* quote ... (line N)" or "- quote ... (line N)".
    """
    content = bullet.lstrip("-*").strip()
    m = re.search(r"\(line\s+(\d+)\)\s*$", content)
    line_num = int(m.group(1)) if m else None
    quote = content[:m.start()].rstrip() if m else content
    return quote, line_num


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "outputs_exist_json": 0.0,
        "outputs_exist_md": 0.0,
        "json_parseable_and_structure": 0.0,
        "disclaimer_in_json_matches_policy": 0.0,
        "config_in_json_matches_comms_config": 0.0,
        "pairs_count_matches_allegations": 0.0,
        "allegation_ids_and_texts_match": 0.0,
        "max_two_talking_points_per_allegation": 0.0,
        "quotes_selected_from_allowed_tag_and_source": 0.0,
        "quotes_redacted_and_truncated_correctly": 0.0,
        "keyword_overlap_for_selected_quotes": 0.0,
        "matched_keywords_presence_and_correctness": 0.0,
        "line_numbers_presence_and_correctness": 0.0,
        "md_disclaimer_and_sections_structure": 0.0,
        "md_has_all_allegation_sections": 0.0,
        "md_quotes_match_json_and_line_numbers": 0.0,
        "no_unredacted_prohibited_phrases_present": 0.0,
    }

    # Paths
    input_allegations = workspace / "input" / "reporter_allegations.md"
    input_memos = workspace / "input" / "memos" / "talking_points.txt"
    input_policy_yaml = workspace / "input" / "policy" / "disclosure_rules.yaml"
    input_comms_py = workspace / "input" / "policy" / "comms_config.py"

    output_json = workspace / "output" / "counter_brief.json"
    output_md = workspace / "output" / "counter_brief.md"

    # Existence checks
    if output_json.exists():
        scores["outputs_exist_json"] = 1.0
    if output_md.exists():
        scores["outputs_exist_md"] = 1.0

    # Load inputs
    policy = parse_simple_yaml(input_policy_yaml)
    comms = parse_comms_config(input_comms_py)
    allegations = parse_allegations_md(input_allegations)
    memos = parse_memos_talking_points(input_memos)

    # If inputs missing or malformed, many checks can't proceed
    if not (policy and comms and allegations and memos):
        return scores

    allowed_tag = policy["allowed_tag"]
    prohibited_phrases = policy["prohibited_phrases"]
    required_disclaimer = policy["required_disclaimer"]
    include_line_numbers = comms["INCLUDE_SOURCE_LINE_NUMBERS"]
    max_quote_chars = comms["MAX_QUOTE_CHARS"]
    include_matched_keywords = comms["INCLUDE_MATCHED_KEYWORDS"]

    # Load outputs JSON
    out_json = load_json(output_json) if output_json.exists() else None

    # JSON structure
    if isinstance(out_json, dict):
        has_keys = all(k in out_json for k in ["disclaimer", "config", "pairs"])
        config_ok = isinstance(out_json.get("config"), dict) and all(
            k in out_json["config"] for k in ["include_line_numbers", "max_quote_chars", "include_matched_keywords"]
        )
        pairs_ok = isinstance(out_json.get("pairs"), list)
        scores["json_parseable_and_structure"] = 1.0 if (has_keys and config_ok and pairs_ok) else 0.0

    # Disclaimer in JSON
    if out_json and out_json.get("disclaimer") == required_disclaimer:
        scores["disclaimer_in_json_matches_policy"] = 1.0

    # Config match
    if out_json and isinstance(out_json.get("config"), dict):
        cfg = out_json["config"]
        cfg_match = (
            cfg.get("include_line_numbers") == include_line_numbers
            and cfg.get("max_quote_chars") == max_quote_chars
            and cfg.get("include_matched_keywords") == include_matched_keywords
        )
        scores["config_in_json_matches_comms_config"] = 1.0 if cfg_match else 0.0

    # Pairs count matches allegations
    total_pairs = len(out_json["pairs"]) if out_json and isinstance(out_json.get("pairs"), list) else 0
    expected_pairs = len(allegations)
    if total_pairs == expected_pairs and expected_pairs > 0:
        scores["pairs_count_matches_allegations"] = 1.0

    # Allegation ids and texts match
    if out_json and isinstance(out_json.get("pairs"), list) and expected_pairs > 0:
        id_text_matches = 0
        for i, pair in enumerate(out_json["pairs"][:expected_pairs]):
            expected_id = allegations[i]["id"]
            expected_full = allegations[i]["full_line_text"]
            expected_content = allegations[i]["content_text"]
            id_ok = pair.get("allegation_id") == expected_id
            text = pair.get("allegation_text")
            text_ok = text == expected_full or text == expected_content
            if id_ok and text_ok:
                id_text_matches += 1
        scores["allegation_ids_and_texts_match"] = id_text_matches / float(expected_pairs) if expected_pairs > 0 else 0.0

    # Build expected quote map for allowed_tag
    expected_quote_map = build_expected_quote_map(memos, prohibited_phrases, max_quote_chars, allowed_tag)

    # Precompute memo entries by line number
    memo_by_line: Dict[int, Dict[str, Any]] = {entry["line_number"]: entry for entry in memos}

    # Checks across talking points
    max_two_checks = 0
    max_two_total = 0
    quote_source_checks = 0
    quote_source_total = 0
    quote_redaction_checks = 0
    quote_redaction_total = 0
    line_num_checks = 0
    line_num_total = 0
    keyword_overlap_checks = 0
    keyword_overlap_total = 0
    matched_keywords_checks = 0
    matched_keywords_total = 0

    stopwords = {"the", "and", "of", "to", "for"}

    if out_json and isinstance(out_json.get("pairs"), list) and expected_pairs > 0:
        for i, pair in enumerate(out_json["pairs"][:expected_pairs]):
            tp_list = pair.get("talking_points")
            # Check max two per allegation
            max_two_total += 1
            if isinstance(tp_list, list) and len(tp_list) <= 2:
                max_two_checks += 1

            if isinstance(tp_list, list):
                all_matched_keywords: set = set()
                for tp in tp_list:
                    # Source correctness
                    quote_source_total += 1
                    source_file_ok = tp.get("source_file") == "input/memos/talking_points.txt"
                    quote = tp.get("quote", "")
                    matched_lines = expected_quote_map.get(quote, [])
                    quote_from_allowed_ok = len(matched_lines) > 0 and source_file_ok
                    if quote_from_allowed_ok:
                        quote_source_checks += 1

                    # Redaction + truncation correctness: quote should match expected mapping for allowed_tag
                    quote_redaction_total += 1
                    if len(matched_lines) > 0:
                        quote_redaction_checks += 1

                    # Line numbers presence and correctness according to config
                    line_num_total += 1
                    ln = tp.get("line_number", None)
                    if include_line_numbers:
                        if isinstance(ln, int) and ln in memo_by_line and memo_by_line[ln]["tag"] == allowed_tag:
                            # The quote must correspond to that line's expected redacted/truncated content
                            expected_quote = expected_redacted_truncated(memo_by_line[ln]["content"], prohibited_phrases, max_quote_chars)
                            if expected_quote == quote and (not matched_lines or ln in matched_lines):
                                line_num_checks += 1
                    else:
                        # Should not include line_number key
                        if "line_number" not in tp:
                            line_num_checks += 1

                    # Keyword overlap relevance
                    keyword_overlap_total += 1
                    allegation_text_for_overlap = pair.get("allegation_text", "")
                    memo_line = memo_by_line.get(ln) if isinstance(ln, int) else None
                    memo_content = memo_line["content"] if memo_line else ""
                    overlap = compute_overlap(allegation_text_for_overlap, memo_content, stopwords)
                    if len(overlap) > 0:
                        keyword_overlap_checks += 1
                    all_matched_keywords.update(overlap)

                # matched_keywords at pair level
                matched_keywords_total += 1
                if include_matched_keywords:
                    mk = pair.get("matched_keywords")
                    if isinstance(mk, list):
                        mk_norm = [str(x).lower() for x in mk]
                        if set(mk_norm) == set(all_matched_keywords):
                            matched_keywords_checks += 1
                else:
                    if "matched_keywords" not in pair:
                        matched_keywords_checks += 1

        # Aggregate TP-based scores
        scores["max_two_talking_points_per_allegation"] = max_two_checks / float(max_two_total) if max_two_total > 0 else 0.0
        scores["quotes_selected_from_allowed_tag_and_source"] = (
            quote_source_checks / float(quote_source_total) if quote_source_total > 0 else 0.0
        )
        scores["quotes_redacted_and_truncated_correctly"] = (
            quote_redaction_checks / float(quote_redaction_total) if quote_redaction_total > 0 else 0.0
        )
        scores["line_numbers_presence_and_correctness"] = (
            line_num_checks / float(line_num_total) if line_num_total > 0 else 0.0
        )
        scores["keyword_overlap_for_selected_quotes"] = (
            keyword_overlap_checks / float(keyword_overlap_total) if keyword_overlap_total > 0 else 0.0
        )
        scores["matched_keywords_presence_and_correctness"] = (
            matched_keywords_checks / float(matched_keywords_total) if matched_keywords_total > 0 else 0.0
        )

    # MD checks
    md_text = read_text(output_md) if output_md.exists() else None
    if md_text:
        md_lines = parse_md_sections(md_text)
        # Disclaimer at top (first non-empty line)
        first_non_empty = None
        for ln in md_lines:
            if ln.strip():
                first_non_empty = ln.strip()
                break
        if first_non_empty == required_disclaimer:
            scores["md_disclaimer_and_sections_structure"] = 1.0

        # Find section indices
        targets = [(allegations[i]["full_line_text"], allegations[i]["content_text"]) for i in range(len(allegations))]
        section_indices = find_section_indices(md_lines, targets)

        # All allegation sections present
        if len(section_indices) == len(allegations) and all(idx >= 0 for idx in section_indices):
            scores["md_has_all_allegation_sections"] = 1.0

        md_match_checks = 0
        md_match_total = 0
        no_points_note_checks = 0
        no_points_note_total = 0

        if out_json and isinstance(out_json.get("pairs"), list):
            for idx, pair in enumerate(out_json["pairs"][:len(allegations)]):
                start_idx = section_indices[idx] if idx < len(section_indices) else -1
                end_idx = section_indices[idx + 1] if idx + 1 < len(section_indices) and section_indices[idx + 1] != -1 else None
                bullets = extract_bullets(md_lines, start_idx, end_idx)
                tp_list = pair.get("talking_points", [])
                if isinstance(tp_list, list):
                    if len(tp_list) == 0:
                        no_points_note_total += 1
                        search_range_end = end_idx if end_idx is not None else len(md_lines)
                        note_present = False
                        for j in range((start_idx + 1) if start_idx >= 0 else 0, search_range_end):
                            ln = md_lines[j].strip()
                            if not ln:
                                break
                            if "No eligible public talking points found." in ln:
                                note_present = True
                                break
                        if note_present:
                            no_points_note_checks += 1
                    else:
                        # Compare each bullet with JSON talking points in order, up to the number of talking points
                        md_match_total += len(tp_list)
                        if len(bullets) >= len(tp_list):
                            for k in range(len(tp_list)):
                                quote_json = tp_list[k].get("quote", "")
                                ln_json = tp_list[k].get("line_number", None)
                                quote_md, ln_md = parse_md_bullet_quote_and_line(bullets[k])
                                quote_ok = quote_md == quote_json
                                line_ok = (ln_md == ln_json) if include_line_numbers else (ln_md is None)
                                if quote_ok and line_ok:
                                    md_match_checks += 1

        # Apply penalty for missing "no eligible" notes by reducing disclaimer score if necessary
        if no_points_note_total > 0:
            if not (no_points_note_checks == no_points_note_total):
                if scores["md_disclaimer_and_sections_structure"] == 1.0:
                    scores["md_disclaimer_and_sections_structure"] = 0.5

        scores["md_quotes_match_json_and_line_numbers"] = (
            md_match_checks / float(md_match_total) if md_match_total > 0 else 0.0
        )

    # Ensure no unredacted prohibited phrases present in any present outputs
    present_outputs = []
    if out_json:
        present_outputs.append("json")
    if md_text:
        present_outputs.append("md")
    if present_outputs:
        compliant = True
        # Check JSON quotes
        if out_json and isinstance(out_json.get("pairs"), list):
            for pair in out_json["pairs"]:
                tps = pair.get("talking_points", [])
                if isinstance(tps, list):
                    for tp in tps:
                        quote = tp.get("quote", "")
                        if contains_unredacted_prohibited(quote, prohibited_phrases):
                            compliant = False
                            break
                if not compliant:
                    break
        # Check MD entire text
        if compliant and md_text:
            for phrase in prohibited_phrases:
                if re.search(re.escape(phrase), md_text, flags=re.IGNORECASE):
                    compliant = False
                    break
        scores["no_unredacted_prohibited_phrases_present"] = 1.0 if compliant else 0.0
    else:
        scores["no_unredacted_prohibited_phrases_present"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()