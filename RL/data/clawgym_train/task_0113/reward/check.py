import json
import sys
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[dict]:
    try:
        text = read_text_safe(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def extract_hex_digests(text: str) -> List[str]:
    return re.findall(r"\b[a-fA-F0-9]{64}\b", text or "")


def parse_cmudict(path: Path) -> Optional[Dict[str, List[str]]]:
    """
    Parse CMU Pronouncing Dictionary file into a mapping: word(lower) -> list of ARPAbet phonemes without stress digits.
    Uses the first pronunciation for words with multiple entries; case-insensitive.
    """
    content = read_text_safe(path)
    if content is None:
        return None
    mapping: Dict[str, List[str]] = {}
    any_valid = False
    try:
        for line in content.splitlines():
            if not line or line.startswith(";;;"):
                continue
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            word_raw = parts[0]
            # Remove alternative pronunciation marker e.g., WORD(1)
            base = re.sub(r"\(\d+\)$", "", word_raw)
            base_lower = base.lower()
            if base_lower in mapping:
                # first pronunciation only
                continue
            phones = parts[1:]
            # Strip stress digits from ARPAbet phones
            phones_clean = [re.sub(r"\d+$", "", p) for p in phones]
            if all(p for p in phones_clean):
                mapping[base_lower] = phones_clean
                any_valid = True
        if not any_valid:
            return None
        return mapping
    except Exception:
        return None


def tokenize_audition_lines(md_text: str) -> List[str]:
    """
    Strip punctuation, lowercase, and split into tokens.
    """
    cleaned = []
    for ch in md_text:
        if ch.isalnum() or ch.isspace():
            cleaned.append(ch)
        else:
            cleaned.append(" ")
    text = "".join(cleaned).lower()
    tokens = [t for t in text.split() if t]
    return tokens


def recompute_coverage(audition_path: Path, dict_map: Dict[str, List[str]]) -> Optional[Tuple[int, int, int, List[str], Dict[str, int], Dict[str, float]]]:
    """
    Returns (words_total, words_found, words_unknown, unknown_words(list, lowercase unique sorted),
             phoneme_counts(dict), phoneme_percentages(dict)).
    words_found and words_unknown are token-level counts (occurrences), not unique types.
    """
    audition_text = read_text_safe(audition_path)
    if audition_text is None:
        return None
    tokens = tokenize_audition_lines(audition_text)
    words_total = len(tokens)
    words_found = 0
    unknown_count = 0
    unknown_set = set()
    phoneme_counts: Dict[str, int] = {}
    for tok in tokens:
        if tok in dict_map:
            words_found += 1
            for ph in dict_map[tok]:
                phoneme_counts[ph] = phoneme_counts.get(ph, 0) + 1
        else:
            unknown_count += 1
            unknown_set.add(tok)
    words_unknown = unknown_count
    unknown_words = sorted(unknown_set)
    total_phones = sum(phoneme_counts.values())
    phoneme_percentages: Dict[str, float] = {}
    if total_phones > 0:
        for ph, cnt in phoneme_counts.items():
            phoneme_percentages[ph] = (cnt / total_phones) * 100.0
    else:
        phoneme_percentages = {}
    return (words_total, words_found, words_unknown, unknown_words, phoneme_counts, phoneme_percentages)


def sum_close_to(value: float, target: float, tol: float) -> bool:
    return abs(value - target) <= tol


def find_analyzer_script(workspace: Path) -> Optional[Path]:
    candidates = [
        workspace / "tools" / "phoneme_analyzer.py",
        workspace / "tools" / "phoneme_analyzer.sh",
        workspace / "tools" / "phoneme_analyzer.js",
    ]
    for p in candidates:
        if p.exists():
            return p
    tools_dir = workspace / "tools"
    if tools_dir.exists():
        for p in tools_dir.iterdir():
            if p.name.startswith("phoneme_analyzer.") and p.suffix in {".py", ".sh", ".js"}:
                return p
    return None


def analyzer_has_example_comment(path: Path) -> bool:
    text = read_text_safe(path)
    if not text:
        return False
    lines = [ln.strip() for ln in text.splitlines()[:10] if ln.strip()]
    comment_prefixes = ["#", "//"]
    for ln in lines:
        if not any(ln.startswith(pref) for pref in comment_prefixes):
            continue
        if ("input/audition_lines.md" in ln) and ("artifacts/phoneme_coverage.json" in ln):
            return True
    return False


def load_phoneme_coverage_json(path: Path) -> Optional[dict]:
    return load_json_safe(path)


def get_top5_phonemes(phoneme_percentages: Dict[str, float]) -> List[str]:
    items = sorted(phoneme_percentages.items(), key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _ in items[:5]]


def contains_all_phonemes(text: str, phonemes: List[str]) -> bool:
    for ph in phonemes:
        if re.search(rf"\b{re.escape(ph)}\b", text) is None:
            return False
    return True


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"[.!?\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def extract_section(text: str, section_title: str) -> Optional[str]:
    """
    Extracts the content of a markdown section by title (case-insensitive),
    from the header line until the next header or end of text.
    """
    lines = text.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if re.match(rf"^#{1,6}\s+{re.escape(section_title)}\s*$", ln.strip(), flags=re.IGNORECASE):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if re.match(r"^#{1,6}\s+.+", lines[j].strip()):
            end_idx = j
            break
    section_content = "\n".join(lines[start_idx:end_idx]).strip()
    return section_content


def count_action_items_with_references(section_text: str, phoneme_set: set, unknown_words_set: set) -> int:
    if not section_text:
        return 0
    count = 0
    for ln in section_text.splitlines():
        if re.match(r"^(\s*[-*]|\s*\d+\.)\s+", ln):
            has_ph = any(re.search(rf"\b{re.escape(ph)}\b", ln) for ph in phoneme_set)
            has_unk = any(re.search(rf"\b{re.escape(uw)}\b", ln, flags=re.IGNORECASE) for uw in unknown_words_set)
            if has_ph or has_unk:
                count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cmudict_file_exists_and_nonempty": 0.0,
        "cmudict_sha256_matches": 0.0,
        "cmudict_format_valid": 0.0,
        "analyzer_script_present_with_example_comment": 0.0,
        "phoneme_coverage_json_exists_with_required_keys": 0.0,
        "phoneme_coverage_json_internal_consistency": 0.0,
        "phoneme_coverage_matches_recomputation": 0.0,
        "unknown_words_txt_exists_and_matches_json": 0.0,
        "coach_email_greets_and_mentions_attachments_and_stats": 0.0,
        "coach_email_includes_top5_phonemes_and_goals": 0.0,
        "meeting_notes_structure_and_references": 0.0,
        "meeting_notes_action_items_tied_to_analysis": 0.0,
        "validator_script_present": 0.0,
        "test_report_exists_nonempty": 0.0,
    }

    # Paths
    cmu_path = workspace / "data" / "cmudict.txt"
    sha_path = workspace / "data" / "cmudict.sha256"
    audition_path = workspace / "input" / "audition_lines.md"
    coach_contact_path = workspace / "input" / "coach_contacts.json"
    artifacts_json_path = workspace / "artifacts" / "phoneme_coverage.json"
    unknown_txt_path = workspace / "artifacts" / "unknown_words.txt"
    email_path = workspace / "deliverables" / "coach_email_draft.txt"
    notes_path = workspace / "deliverables" / "meeting_notes.md"
    validator_py = workspace / "tests" / "validate_outputs.py"
    validator_sh = workspace / "tests" / "validate_outputs.sh"
    test_report_path = workspace / "artifacts" / "test_report.txt"

    # cmudict exists and non-empty
    cmu_text = read_text_safe(cmu_path)
    if cmu_text and cmu_text.strip():
        scores["cmudict_file_exists_and_nonempty"] = 1.0

    # sha256 matches
    digest = sha256_file(cmu_path) if cmu_path.exists() else None
    sha_text = read_text_safe(sha_path)
    if digest and sha_text:
        digests_in_file = extract_hex_digests(sha_text)
        if digest in [d.lower() for d in digests_in_file] or digest.upper() in digests_in_file:
            scores["cmudict_sha256_matches"] = 1.0

    # cmudict format valid: try to parse and ensure reasonable size
    dict_map = None
    parsed_ok = False
    if cmu_path.exists():
        dict_map = parse_cmudict(cmu_path)
        if dict_map and isinstance(dict_map, dict) and len(dict_map) >= 10000:
            parsed_ok = True
    if parsed_ok:
        scores["cmudict_format_valid"] = 1.0

    # Analyzer script with example comment
    analyzer_path = find_analyzer_script(workspace)
    if analyzer_path and analyzer_has_example_comment(analyzer_path):
        scores["analyzer_script_present_with_example_comment"] = 1.0

    # Load phoneme coverage json
    cov_json = load_phoneme_coverage_json(artifacts_json_path)
    required_keys = {
        "source_file",
        "dict_file",
        "words_total",
        "words_found",
        "words_unknown",
        "unknown_words",
        "phoneme_counts",
        "phoneme_percentages",
    }
    cov_keys_ok = False
    if isinstance(cov_json, dict) and required_keys.issubset(set(cov_json.keys())):
        types_ok = (
            isinstance(cov_json.get("source_file"), str)
            and isinstance(cov_json.get("dict_file"), str)
            and isinstance(cov_json.get("words_total"), int)
            and isinstance(cov_json.get("words_found"), int)
            and isinstance(cov_json.get("words_unknown"), int)
            and isinstance(cov_json.get("unknown_words"), list)
            and isinstance(cov_json.get("phoneme_counts"), dict)
            and isinstance(cov_json.get("phoneme_percentages"), dict)
        )
        cov_keys_ok = types_ok
    if cov_keys_ok:
        scores["phoneme_coverage_json_exists_with_required_keys"] = 1.0

    # Internal consistency checks
    internal_ok = False
    if cov_keys_ok:
        try:
            wt = cov_json["words_total"]
            wf = cov_json["words_found"]
            wu = cov_json["words_unknown"]
            phon_counts = cov_json["phoneme_counts"]
            phon_perc = cov_json["phoneme_percentages"]
            # words_found + words_unknown == words_total
            cond1 = (wf + wu == wt)
            # percentages sum ~100% (±0.1)
            perc_sum = sum(float(v) for v in phon_perc.values()) if phon_perc else 0.0
            cond2 = sum_close_to(perc_sum, 100.0, 0.1) or (len(phon_perc) == 0 and perc_sum == 0.0)
            # percentages consistent with counts within tolerance when counts present
            total_phones = sum(int(v) for v in phon_counts.values()) if phon_counts else 0
            cond3 = True
            if total_phones > 0:
                for ph, cnt in phon_counts.items():
                    pct = phon_perc.get(ph)
                    if pct is None:
                        cond3 = False
                        break
                    expected = (cnt / total_phones) * 100.0
                    if abs(pct - expected) > 0.5:
                        cond3 = False
                        break
            internal_ok = cond1 and cond2 and cond3
        except Exception:
            internal_ok = False
    if internal_ok:
        scores["phoneme_coverage_json_internal_consistency"] = 1.0

    # Recompute coverage and compare
    recompute_ok = False
    if dict_map and audition_path.exists() and cov_keys_ok:
        recomputed = recompute_coverage(audition_path, dict_map)
        if recomputed:
            (wt2, wf2, wu2, unknown2, phon_counts2, phon_perc2) = recomputed
            try:
                basic_ok = (
                    cov_json["words_total"] == wt2
                    and cov_json["words_found"] == wf2
                    and cov_json["words_unknown"] == wu2
                )
                # Unknown words set match (case-insensitive)
                unk_json_set = {str(w).lower() for w in cov_json.get("unknown_words", [])}
                unk_cmp_ok = set(unknown2) == unk_json_set
                # Phoneme counts match exactly (ignoring zeros)
                pc_json = {k: int(v) for k, v in cov_json.get("phoneme_counts", {}).items() if int(v) != 0}
                pc_ref = {k: int(v) for k, v in phon_counts2.items() if int(v) != 0}
                counts_ok = pc_json == pc_ref
                # Percentages close to recomputed
                perc_ok = True
                for ph, ref in phon_perc2.items():
                    pct = cov_json.get("phoneme_percentages", {}).get(ph)
                    if pct is None or abs(pct - ref) > 0.5:
                        perc_ok = False
                        break
                recompute_ok = basic_ok and unk_cmp_ok and counts_ok and perc_ok
            except Exception:
                recompute_ok = False
    if recompute_ok:
        scores["phoneme_coverage_matches_recomputation"] = 1.0

    # unknown_words.txt exists and matches JSON, and appears in input and not in dict
    unknown_txt_ok = False
    u_text = read_text_safe(unknown_txt_path)
    if u_text is not None and cov_keys_ok and audition_path.exists() and dict_map:
        lines = [ln.strip() for ln in u_text.splitlines() if ln.strip()]
        txt_set = {ln.lower() for ln in lines}
        unk_json_set = {str(w).lower() for w in cov_json.get("unknown_words", [])}
        sets_equal = txt_set == unk_json_set
        audition_tokens = set(tokenize_audition_lines(read_text_safe(audition_path) or ""))
        appear_ok = all(w in audition_tokens for w in txt_set)
        not_in_dict_ok = all(w not in dict_map for w in txt_set)
        unknown_txt_ok = sets_equal and appear_ok and not_in_dict_ok
    if unknown_txt_ok:
        scores["unknown_words_txt_exists_and_matches_json"] = 1.0

    # Coach email checks
    email_text = read_text_safe(email_path) or ""
    coach_info = load_json_safe(coach_contact_path) or {}
    coach_name = coach_info.get("coach_name")
    email_basic_ok = False
    if email_text and cov_keys_ok and coach_name:
        greet_ok = coach_name in email_text
        attach_ok = ("artifacts/phoneme_coverage.json" in email_text) and ("artifacts/unknown_words.txt" in email_text)
        wu = cov_json.get("words_unknown")
        count_ok = isinstance(wu, int) and (str(wu) in email_text)
        email_basic_ok = greet_ok and attach_ok and count_ok
    if email_basic_ok:
        scores["coach_email_greets_and_mentions_attachments_and_stats"] = 1.0

    email_focus_ok = False
    if email_text and cov_keys_ok:
        top5 = get_top5_phonemes(cov_json.get("phoneme_percentages", {}))
        top5_present = contains_all_phonemes(email_text, top5) if top5 else False
        unknown_words_set = {str(w).lower() for w in cov_json.get("unknown_words", [])}
        phoneme_codes_set = set(cov_json.get("phoneme_counts", {}).keys())
        candidates = []
        for ln in email_text.splitlines():
            if re.match(r"^\s*[-*]\s+", ln):
                candidates.append(ln.strip())
        for sent in split_sentences(email_text):
            if re.search(r"\b(goal|goals|practice|focus|target)\b", sent, flags=re.IGNORECASE):
                candidates.append(sent)
        seen = set()
        filtered = []
        for c in candidates:
            key = c.lower()
            if key not in seen:
                seen.add(key)
                filtered.append(c)

        def mentions_analysis(s: str) -> bool:
            has_ph = any(re.search(rf"\b{re.escape(ph)}\b", s) for ph in phoneme_codes_set)
            has_unk = any(re.search(rf"\b{re.escape(uw)}\b", s, flags=re.IGNORECASE) for uw in unknown_words_set)
            return has_ph or has_unk

        goals_count = sum(1 for c in filtered if mentions_analysis(c))
        email_focus_ok = top5_present and (2 <= goals_count <= 3)
    if email_focus_ok:
        scores["coach_email_includes_top5_phonemes_and_goals"] = 1.0

    # Meeting notes checks
    notes_text = read_text_safe(notes_path) or ""
    notes_struct_ok = False
    if notes_text:
        has_context = extract_section(notes_text, "Context") is not None
        has_key_findings = extract_section(notes_text, "Key Findings") is not None
        has_action_items = extract_section(notes_text, "Action Items") is not None
        refs_ok = ("artifacts/phoneme_coverage.json" in notes_text) and ("artifacts/unknown_words.txt" in notes_text)
        notes_struct_ok = has_context and has_key_findings and has_action_items and refs_ok
    if notes_struct_ok:
        scores["meeting_notes_structure_and_references"] = 1.0

    notes_actions_ok = False
    if notes_text and cov_keys_ok:
        action_section = extract_section(notes_text, "Action Items") or ""
        phoneme_codes_set = set(cov_json.get("phoneme_counts", {}).keys())
        unknown_words_set2 = {str(w).lower() for w in cov_json.get("unknown_words", [])}
        count_items = count_action_items_with_references(action_section, phoneme_codes_set, unknown_words_set2)
        notes_actions_ok = count_items >= 5
    if notes_actions_ok:
        scores["meeting_notes_action_items_tied_to_analysis"] = 1.0

    # Validator script present
    validator_present = False
    for p in [validator_py, validator_sh]:
        if p.exists() and (read_text_safe(p) or ""):
            validator_present = True
            break
    if validator_present:
        scores["validator_script_present"] = 1.0

    # Test report exists and non-empty
    tr_text = read_text_safe(test_report_path)
    if tr_text and tr_text.strip():
        scores["test_report_exists_nonempty"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()