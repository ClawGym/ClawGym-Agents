import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


TRACKED_KEYWORDS = [
    "tariff",
    "subsidy",
    "free trade",
    "sanction",
    "carbon tax",
    "cap-and-trade",
    "capital controls",
    "privatization",
    "state-owned",
    "austerity",
]


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="latin-1")
        except Exception:
            return None


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _list_input_docs(workspace: Path) -> List[Path]:
    input_dir = workspace / "input" / "drafts"
    if not input_dir.exists() or not input_dir.is_dir():
        return []
    return sorted([p for p in input_dir.glob("*.txt") if p.is_file()])


def _compile_keyword_patterns() -> Dict[str, List[re.Pattern]]:
    patterns: Dict[str, List[re.Pattern]] = {}
    plural_variants = {
        "tariff": ["tariff", "tariffs"],
        "subsidy": ["subsidy", "subsidies"],
        "sanction": ["sanction", "sanctions"],
    }
    for kw in TRACKED_KEYWORDS:
        variants = plural_variants.get(kw, [kw])
        compiled = []
        for v in variants:
            # whole word/phrase: ensure not preceded/followed by word char
            pat = re.compile(rf"(?i)(?<!\w){re.escape(v)}(?!\w)")
            compiled.append(pat)
        patterns[kw] = compiled
    return patterns


def _count_occurrences(text: str, patterns: List[re.Pattern]) -> int:
    count = 0
    for pat in patterns:
        count += len(list(pat.finditer(text)))
    return count


def _compute_doc_metrics(text: str, keyword_patterns: Dict[str, List[re.Pattern]]) -> Tuple[int, Dict[str, int], int, int, bool]:
    norm_text = _normalize_newlines(text)
    total_words = len(norm_text.split())
    keyword_counts: Dict[str, int] = {}
    for kw in TRACKED_KEYWORDS:
        keyword_counts[kw] = _count_occurrences(norm_text, keyword_patterns[kw])
    support_count = len(re.findall(r"(?i)(?<!\w)support(?!\w)", norm_text))
    oppose_count = len(re.findall(r"(?i)(?<!\w)oppose(?!\w)", norm_text))
    has_contradiction = support_count > 0 and oppose_count > 0
    return total_words, keyword_counts, support_count, oppose_count, has_contradiction


def _expected_analysis_for_docs(docs: List[Path], workspace: Path) -> List[Dict]:
    patterns = _compile_keyword_patterns()
    expected = []
    for p in docs:
        text = _read_text_safe(p)
        if text is None:
            # malformed; treat as empty metrics
            total_words = 0
            keyword_counts = {kw: 0 for kw in TRACKED_KEYWORDS}
            support_count = 0
            oppose_count = 0
            has_contradiction = False
        else:
            total_words, keyword_counts, support_count, oppose_count, has_contradiction = _compute_doc_metrics(text, patterns)
        doc_id = p.stem
        rel_path = (Path("input") / "drafts" / p.name).as_posix()
        expected.append({
            "doc_id": doc_id,
            "source_path": rel_path,
            "total_words": total_words,
            "keyword_counts": keyword_counts,
            "support_count": support_count,
            "oppose_count": oppose_count,
            "has_contradiction": has_contradiction,
        })
    # sort expected by doc_id for stable comparisons
    expected.sort(key=lambda d: d["doc_id"])
    return expected


def _safe_get(obj: dict, key: str, default=None):
    try:
        return obj.get(key, default)
    except Exception:
        return default


def _validate_analysis_schema_and_length(actual: List[Dict], expected: List[Dict]) -> bool:
    if not isinstance(actual, list):
        return False
    if len(actual) != len(expected):
        return False
    # schema: exactly specified fields
    required_fields = {"doc_id", "source_path", "total_words", "keyword_counts", "support_count", "oppose_count", "has_contradiction"}
    for item in actual:
        if not isinstance(item, dict):
            return False
        keys = set(item.keys())
        if keys != required_fields:
            return False
        if not isinstance(item["doc_id"], str):
            return False
        if not isinstance(item["source_path"], str):
            return False
        if not isinstance(item["total_words"], int):
            return False
        if not isinstance(item["support_count"], int):
            return False
        if not isinstance(item["oppose_count"], int):
            return False
        if not isinstance(item["has_contradiction"], bool):
            return False
        kc = item["keyword_counts"]
        if not isinstance(kc, dict):
            return False
        if set(kc.keys()) != set(TRACKED_KEYWORDS):
            return False
        for v in kc.values():
            if not isinstance(v, int):
                return False
    return True


def _compare_analysis_content(actual: List[Dict], expected: List[Dict]) -> float:
    # normalize ordering by doc_id
    def sort_key(d): return d["doc_id"]
    try:
        actual_sorted = sorted(actual, key=sort_key)
    except Exception:
        return 0.0
    expected_sorted = expected
    if len(actual_sorted) != len(expected_sorted) or len(expected_sorted) == 0:
        return 0.0 if len(expected_sorted) > 0 else 0.0
    total = len(expected_sorted)
    correct = 0
    for act, exp in zip(actual_sorted, expected_sorted):
        ok = True
        if act["doc_id"] != exp["doc_id"]:
            ok = False
        if act["source_path"] != exp["source_path"]:
            ok = False
        if act["total_words"] != exp["total_words"]:
            ok = False
        if act["support_count"] != exp["support_count"]:
            ok = False
        if act["oppose_count"] != exp["oppose_count"]:
            ok = False
        if act["has_contradiction"] != exp["has_contradiction"]:
            ok = False
        kc_ok = True
        for kw in TRACKED_KEYWORDS:
            if act["keyword_counts"].get(kw) != exp["keyword_counts"].get(kw):
                kc_ok = False
                break
        if not kc_ok:
            ok = False
        if ok:
            correct += 1
    return correct / total if total > 0 else 0.0


def _split_paragraphs(text: str) -> List[str]:
    norm = _normalize_newlines(text).strip()
    if not norm:
        return []
    parts = re.split(r"\n\s*\n", norm)
    # keep non-empty
    return [p.strip() for p in parts if p.strip()]


def _find_paragraph_for_doc(paragraphs: List[str], doc_id: str) -> Optional[str]:
    for p in paragraphs:
        # whole-word match for doc_id in paragraph
        if re.search(rf"(?i)(?<!\w){re.escape(doc_id)}(?!\w)", p):
            return p
    return None


def _top_keywords_for_doc(keyword_counts: Dict[str, int], topn: int = 2) -> List[str]:
    items = list(keyword_counts.items())
    items.sort(key=lambda kv: (-kv[1], kv[0]))
    return [k for k, v in items[:topn]]


def _docfreq_for_keywords(analyses: List[Dict]) -> Dict[str, int]:
    df = {kw: 0 for kw in TRACKED_KEYWORDS}
    for a in analyses:
        for kw in TRACKED_KEYWORDS:
            if a["keyword_counts"].get(kw, 0) > 0:
                df[kw] += 1
    return df


def _startswith_loosely(content: str, prefix: str) -> bool:
    # Normalize newlines; allow optional single trailing newline difference
    c = _normalize_newlines(content)
    p = _normalize_newlines(prefix)
    if c.startswith(p):
        return True
    # Allow exactly one extra newline after original
    if c.startswith(p + "\n"):
        return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "analysis_file_exists_and_schema": 0.0,
        "analysis_counts_correct": 0.0,
        "report_exists_and_doc_sections": 0.0,
        "report_top2_and_overall_metrics_correct": 0.0,
        "revisions_exist_prefix_and_header": 0.0,
        "revisions_bullets_correct": 0.0,
        "action_items_exists_and_sections": 0.0,
        "action_items_bullets_correct_content": 0.0,
    }

    input_docs = _list_input_docs(workspace)
    expected_analysis = _expected_analysis_for_docs(input_docs, workspace)

    # 1) Structured analysis output
    analysis_path = workspace / "output" / "analysis" / "keywords.json"
    actual_analysis = _load_json_safe(analysis_path)
    schema_ok = False
    if actual_analysis is not None and isinstance(actual_analysis, list):
        schema_ok = _validate_analysis_schema_and_length(actual_analysis, expected_analysis)
    if analysis_path.exists() and actual_analysis is not None and schema_ok:
        scores["analysis_file_exists_and_schema"] = 1.0
    else:
        scores["analysis_file_exists_and_schema"] = 0.0

    # Counts/content correctness across docs
    if schema_ok and len(expected_analysis) > 0:
        scores["analysis_counts_correct"] = _compare_analysis_content(actual_analysis, expected_analysis)
    else:
        # If there are expected docs but schema invalid, score 0
        scores["analysis_counts_correct"] = 0.0

    # 2) Status summary report
    report_path = workspace / "output" / "reports" / "status_summary.md"
    report_text = _read_text_safe(report_path)
    if report_text is None:
        scores["report_exists_and_doc_sections"] = 0.0
        scores["report_top2_and_overall_metrics_correct"] = 0.0
    else:
        paras = _split_paragraphs(report_text)
        # Check for each document: a section/paragraph stating doc_id and contradiction and top2 keywords
        if len(expected_analysis) == 0:
            scores["report_exists_and_doc_sections"] = 0.0
            scores["report_top2_and_overall_metrics_correct"] = 0.0
        else:
            found_sections = 0
            doc_checks = 0
            correct_doc_checks = 0
            for exp in expected_analysis:
                doc_id = exp["doc_id"]
                p = _find_paragraph_for_doc(paras, doc_id)
                if p is not None:
                    found_sections += 1
                # For top2 and contradiction correctness
                doc_checks += 1  # one combined check per doc for presence of correct 'true/false' and top two keyword mentions
                exp_bool = "true" if exp["has_contradiction"] else "false"
                # expect 'true'/'false' word present
                bool_present = re.search(rf"(?i)(?<!\w){exp_bool}(?!\w)", p or "") is not None
                top2 = _top_keywords_for_doc(exp["keyword_counts"], topn=2)
                # ensure both keywords are mentioned in paragraph
                top2_present = all(re.search(rf"(?i)(?<!\w){re.escape(kw)}(?!\w)", p or "") is not None for kw in top2)
                if bool_present and top2_present and p is not None:
                    correct_doc_checks += 1
            scores["report_exists_and_doc_sections"] = found_sections / len(expected_analysis)

            # Overall metrics in the final section
            overall_ok = False
            if paras:
                last_para = paras[-1]
                # total documents processed
                total_docs = len(expected_analysis)
                total_line_ok = re.search(rf"(?is)\btotal\b.*\b{total_docs}\b", last_para) is not None
                # per-keyword doc frequency
                exp_df = _docfreq_for_keywords(expected_analysis)
                per_kw_ok = True
                lines = _normalize_newlines(last_para).split("\n")
                for kw, freq in exp_df.items():
                    # look for a line containing keyword and the exact freq number
                    line_has = any((re.search(rf"(?i)(?<!\w){re.escape(kw)}(?!\w)", ln) and re.search(rf"(?<!\d){freq}(?!\d)", ln)) for ln in lines)
                    if not line_has:
                        per_kw_ok = False
                        break
                overall_ok = bool(total_line_ok and per_kw_ok)
            # Combine doc checks and overall metrics: average of (doc correctness across docs) and (overall metrics correctness as 0/1)
            doc_part = (correct_doc_checks / doc_checks) if doc_checks > 0 else 0.0
            overall_part = 1.0 if overall_ok else 0.0
            scores["report_top2_and_overall_metrics_correct"] = (doc_part + overall_part) / 2.0

    # 3) Counterpoint revisions
    # For each input doc, there should be a revision at output/revisions/{doc_id}_counterpoint.md
    if len(expected_analysis) == 0:
        scores["revisions_exist_prefix_and_header"] = 0.0
        scores["revisions_bullets_correct"] = 0.0
    else:
        exist_prefix_header_hits = 0
        bullets_hits = 0
        for exp in expected_analysis:
            doc_id = exp["doc_id"]
            src_path = workspace / "input" / "drafts" / f"{doc_id}.txt"
            rev_path = workspace / "output" / "revisions" / f"{doc_id}_counterpoint.md"
            src_text = _read_text_safe(src_path) or ""
            rev_text = _read_text_safe(rev_path)
            # Check existence, prefix (original text), and header presence
            header_ok = False
            prefix_ok = False
            if rev_text is not None:
                prefix_ok = _startswith_loosely(rev_text, src_text)
                # header line "Counterpoint" exact or "# Counterpoint"
                lines = _normalize_newlines(rev_text).split("\n")
                header_ok = any(ln.strip() == "Counterpoint" or ln.strip() == "# Counterpoint" for ln in lines)
            if rev_text is not None and prefix_ok and header_ok:
                exist_prefix_header_hits += 1

            # Bullets correctness
            bullets_ok = False
            if rev_text is not None:
                lines = _normalize_newlines(rev_text).split("\n")
                # find start of counterpoint section
                start_idx = None
                for i, ln in enumerate(lines):
                    if ln.strip() == "Counterpoint" or ln.strip() == "# Counterpoint":
                        start_idx = i
                        break
                if start_idx is not None:
                    section_lines = lines[start_idx + 1 :]
                    bullets = [ln.strip() for ln in section_lines if ln.strip().startswith("- ")]
                    # Expected bullets: exactly one per keyword with count > 0
                    expected_positive = [kw for kw, cnt in exp["keyword_counts"].items() if cnt > 0]
                    expected_set = set(
                        [f"- Counterpoint on {kw} in {doc_id}: prepare arguments challenging reliance on {kw}." for kw in expected_positive]
                    )
                    bullets_set = set(bullets)
                    # ensure no extra bullets and all expected present exactly once
                    if bullets_set == expected_set and len(bullets) == len(expected_positive):
                        bullets_ok = True
            if bullets_ok:
                bullets_hits += 1

        total_docs = len(expected_analysis)
        scores["revisions_exist_prefix_and_header"] = exist_prefix_header_hits / total_docs
        scores["revisions_bullets_correct"] = bullets_hits / total_docs

    # 4) Action items notes
    notes_path = workspace / "output" / "notes" / "action_items.md"
    notes_text = _read_text_safe(notes_path)
    if len(expected_analysis) == 0 or notes_text is None:
        scores["action_items_exists_and_sections"] = 0.0
        scores["action_items_bullets_correct_content"] = 0.0
    else:
        lines = _normalize_newlines(notes_text).split("\n")
        # Build sections by locating headers
        # Accept either exact "Action Items — {doc_id}" or "# Action Items — {doc_id}"
        def find_section(doc_id: str) -> Tuple[Optional[int], Optional[int]]:
            header_patterns = [
                rf"^\s*Action Items — {re.escape(doc_id)}\s*$",
                rf"^\s*#\s*Action Items — {re.escape(doc_id)}\s*$",
            ]
            header_idx = None
            for i, ln in enumerate(lines):
                if any(re.match(pat, ln) for pat in header_patterns):
                    header_idx = i
                    break
            if header_idx is None:
                return None, None
            # section ends at next header line or EOF
            end_idx = len(lines)
            for j in range(header_idx + 1, len(lines)):
                if lines[j].strip().startswith("# ") or re.match(r"^\s*Action Items — ", lines[j]):
                    end_idx = j
                    break
            return header_idx, end_idx

        sections_found = 0
        bullets_content_correct = 0
        for exp in expected_analysis:
            doc_id = exp["doc_id"]
            start, end = find_section(doc_id)
            if start is not None:
                sections_found += 1
                section_lines = [ln.strip() for ln in lines[start + 1 : end]]
                bullets = [ln for ln in section_lines if ln.startswith("- ")]
                # exactly three bullets
                if len(bullets) == 3:
                    # compute expected bullets
                    # 1) top keyword or none
                    top_items = sorted(exp["keyword_counts"].items(), key=lambda kv: (-kv[1], kv[0]))
                    top_count = top_items[0][1]
                    if top_count == 0:
                        top_kw = "none"
                    else:
                        top_kw = top_items[0][0]
                    b1 = f"- Prepare talking points for the top keyword: {top_kw}"
                    # 2) contradiction
                    if exp["has_contradiction"]:
                        b2 = f"- Clarify stance conflicts detected (support vs oppose) in {doc_id}"
                    else:
                        b2 = f"- Add anticipatory Q&A covering counter-arguments for {doc_id}"
                    # 3) missing keyword: alphabetically first with count 0 or none
                    missing = [kw for kw in TRACKED_KEYWORDS if exp["keyword_counts"].get(kw, 0) == 0]
                    if missing:
                        mk = sorted(missing)[0]
                    else:
                        mk = "none"
                    b3 = f"- Research and draft counterpoints for a missing keyword: {mk}"
                    if bullets[0] == b1 and bullets[1] == b2 and bullets[2] == b3:
                        bullets_content_correct += 1

        total_docs = len(expected_analysis)
        scores["action_items_exists_and_sections"] = sections_found / total_docs
        scores["action_items_bullets_correct_content"] = bullets_content_correct / total_docs

    # Ensure floats are within [0,1]
    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if fv < 0.0:
            fv = 0.0
        if fv > 1.0:
            fv = 1.0
        scores[k] = fv

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()