import json
import os
import re
import sys
from typing import Dict, List, Tuple

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def is_truthy(val: str) -> bool:
    s = str(val).strip().lower()
    return s in {"true", "1", "yes", "y"}

def extract_sections(md_text: str) -> Tuple[Dict[str, str], List[Tuple[str, int, int]]]:
    """
    Parse a markdown abstract into sections by matching headers:
    Background:, Objective:, Methods:, Results:, Conclusion:
    Allows optional markdown bold (**Header**) and optional markdown heading marks (#).
    Returns:
      - sections dict mapping lowercase header to body text (without header line)
      - list of (header_lower, start_idx, end_idx) for matched header spans
    """
    pattern = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(Background|Objective|Methods|Results|Conclusion)\s*(?:\*\*)?\s*:\s*",
    )
    sections: Dict[str, str] = {}
    matches = list(pattern.finditer(md_text))
    spans: List[Tuple[str, int, int]] = []
    for i, m in enumerate(matches):
        header = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        body = md_text[start:end].strip()
        sections[header] = body
        spans.append((header, m.start(), end))
    return sections, spans

def count_words(text: str) -> int:
    # Normalize whitespace
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return 0
    # Split by whitespace; count tokens with at least one alphanumeric or symbol
    tokens = [t for t in cleaned.split(" ") if t]
    return len(tokens)

def mask_ranges(s: str, ranges: List[Tuple[int, int]]) -> str:
    """Replace characters in the given ranges with spaces to avoid double counting."""
    if not ranges:
        return s
    chars = list(s)
    for start, end in ranges:
        for i in range(start, min(end, len(chars))):
            chars[i] = " "
    return "".join(chars)

def finditer_with_spans(pattern: re.Pattern, text: str) -> List[Tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in pattern.finditer(text)]

def find_numeric_items(text: str) -> List[str]:
    """
    Extract numeric strings and quantitative patterns from text.
    Returns unique items as they appear (verbatim substrings), order-insensitive.
    Priority mask prevents double counting numbers inside larger patterns.
    Patterns:
      - Confidence intervals: '95% CI: a-b' or '95% CI [a, b]'
      - p-values: e.g., 'p<0.05', 'p = 0.001'
      - n= sample sizes: 'n=321'
      - Effect metrics: 'OR=4.2', 'HR=1.5', 'RR=0.8', 'SMD=0.42'
      - Plus/minus: '0.892 ± 0.034'
      - Percentages: '68.2%'
      - Multipliers: '3.2×' or '3.2x'
      - Decimals: '0.034'
      - Integers: '482', '24'
    """
    items: List[str] = []
    masked = text

    # Define patterns
    ci_pat = re.compile(r"\b\d{1,3}\s*%\s*CI\s*[:\[]\s*\[?\s*[-+]?\d+(?:\.\d+)?\s*(?:,\s*|-\s*)[-+]?\d+(?:\.\d+)?\s*\]?", re.IGNORECASE)
    pval_pat = re.compile(r"\bp\s*(?:=|<|>|<=|>=)\s*(?:0|\d+\.\d+|0?\.\d+)\b", re.IGNORECASE)
    n_eq_pat = re.compile(r"\bn\s*=\s*\d+\b", re.IGNORECASE)
    effect_pat = re.compile(r"\b(?:OR|HR|RR|SMD|AOR|IRR|beta|d|r)\s*=\s*[-+]?\d+(?:\.\d+)?\b", re.IGNORECASE)
    plusminus_pat = re.compile(r"\b\d+(?:\.\d+)?\s*±\s*\d+(?:\.\d+)?\b")
    percent_pat = re.compile(r"\b\d+(?:\.\d+)?\s*%")
    times_pat = re.compile(r"\b\d+(?:\.\d+)?\s*[x×]\b", re.IGNORECASE)
    decimal_pat = re.compile(r"\b\d+\.\d+\b")
    integer_pat = re.compile(r"\b\d+\b")

    # Apply in priority order, masking matched ranges between passes
    for pat in [ci_pat, pval_pat, n_eq_pat, effect_pat, plusminus_pat, percent_pat, times_pat]:
        found = finditer_with_spans(pat, masked)
        if found:
            items.extend([s for (s, _, _) in found])
            masked = mask_ranges(masked, [(a, b) for (_, a, b) in found])

    # Decimals not already captured
    dec_found = finditer_with_spans(decimal_pat, masked)
    if dec_found:
        items.extend([s for (s, _, _) in dec_found])
        masked = mask_ranges(masked, [(a, b) for (_, a, b) in dec_found])

    # Integers not already captured
    int_found = finditer_with_spans(integer_pat, masked)
    if int_found:
        items.extend([s for (s, _, _) in int_found])
        masked = mask_ranges(masked, [(a, b) for (_, a, b) in int_found])

    # Return unique items
    unique_items = sorted(set(i.strip() for i in items if i.strip()))
    return unique_items

def contains_p_or_ci(text: str) -> bool:
    if re.search(r"\bp\s*(?:=|<|>|<=|>=)\s*(?:0|\d+\.\d+|0?\.\d+)\b", text, re.IGNORECASE):
        return True
    if re.search(r"\b\d{1,3}\s*%\s*CI\b", text, re.IGNORECASE):
        return True
    if re.search(r"\bconfidence\s*interval\b", text, re.IGNORECASE):
        return True
    return False

def csv_read(path: str) -> List[List[str]]:
    rows: List[List[str]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                # Simple CSV split by comma; values expected simple
                parts = [p.strip() for p in line.split(",")]
                rows.append(parts)
    except Exception:
        pass
    return rows

def main() -> None:
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected paths
    paper1_path = os.path.join(output_dir, "abstracts", "paper1.md")
    paper2_path = os.path.join(output_dir, "abstracts", "paper2.md")
    index_csv_path = os.path.join(output_dir, "abstracts", "index.csv")
    verification_json_path = os.path.join(output_dir, "abstracts", "verification.json")
    summary_md_path = os.path.join(output_dir, "abstracts", "summary.md")

    input_p1 = os.path.join(input_dir, "paper1.txt")
    input_p2 = os.path.join(input_dir, "paper2.txt")

    checks: Dict[str, bool] = {
        "file_paper1_exists": False,
        "file_paper2_exists": False,
        "file_index_exists": False,
        "file_verification_exists": False,
        "file_summary_exists": False,
        "paper1_has_all_sections": False,
        "paper2_has_all_sections": False,
        "paper1_exactly_five_sections": False,
        "paper2_exactly_five_sections": False,
        "paper1_word_count_250": False,
        "paper2_word_count_250": False,
        "paper1_numbers_subset_of_input": False,
        "paper2_numbers_subset_of_input": False,
        "paper1_significance_included_if_required": False,
        "paper2_significance_included_if_required": False,
        "index_header_ok": False,
        "index_two_rows": False,
        "index_word_counts_match": False,
        "index_has_all_sections_match": False,
        "index_numeric_counts_match": False,
        "verification_structure_ok": False,
        "verification_numbers_match_paper1": False,
        "verification_numbers_match_paper2": False,
        "summary_has_min_bullets": False,
        "summary_mentions_both_papers": False,
    }

    # File presence
    checks["file_paper1_exists"] = os.path.isfile(paper1_path)
    checks["file_paper2_exists"] = os.path.isfile(paper2_path)
    checks["file_index_exists"] = os.path.isfile(index_csv_path)
    checks["file_verification_exists"] = os.path.isfile(verification_json_path)
    checks["file_summary_exists"] = os.path.isfile(summary_md_path)

    # Load contents
    paper1_text = read_text(paper1_path) if checks["file_paper1_exists"] else ""
    paper2_text = read_text(paper2_path) if checks["file_paper2_exists"] else ""
    src1_text = read_text(input_p1)
    src2_text = read_text(input_p2)

    # Sections and word counts
    paper1_sections, _ = extract_sections(paper1_text) if paper1_text else ({}, [])
    paper2_sections, _ = extract_sections(paper2_text) if paper2_text else ({}, [])

    required_headers = ["background", "objective", "methods", "results", "conclusion"]
    if paper1_sections:
        has_all_1 = all(h in paper1_sections and paper1_sections[h].strip() for h in required_headers)
        checks["paper1_has_all_sections"] = has_all_1
        checks["paper1_exactly_five_sections"] = has_all_1 and len(paper1_sections) == 5
        # Count words across bodies only
        if has_all_1:
            body_text_1 = "\n\n".join(paper1_sections[h] for h in required_headers)
            wc1 = count_words(body_text_1)
            checks["paper1_word_count_250"] = wc1 == 250

    if paper2_sections:
        has_all_2 = all(h in paper2_sections and paper2_sections[h].strip() for h in required_headers)
        checks["paper2_has_all_sections"] = has_all_2
        checks["paper2_exactly_five_sections"] = has_all_2 and len(paper2_sections) == 5
        if has_all_2:
            body_text_2 = "\n\n".join(paper2_sections[h] for h in required_headers)
            wc2 = count_words(body_text_2)
            checks["paper2_word_count_250"] = wc2 == 250

    # Numeric fidelity subset checks
    # Only evaluate if corresponding paper exists and has sections
    if checks["file_paper1_exists"] and checks["paper1_has_all_sections"]:
        body_text_1 = "\n\n".join(paper1_sections[h] for h in required_headers)
        nums1 = find_numeric_items(body_text_1)
        # Ensure every numeric item is found verbatim in input
        subset_ok_1 = all(n in src1_text for n in nums1)
        checks["paper1_numbers_subset_of_input"] = subset_ok_1

        # Significance requirement (only awards if input has p/CI)
        if contains_p_or_ci(src1_text):
            if contains_p_or_ci(body_text_1):
                checks["paper1_significance_included_if_required"] = True

    if checks["file_paper2_exists"] and checks["paper2_has_all_sections"]:
        body_text_2 = "\n\n".join(paper2_sections[h] for h in required_headers)
        nums2 = find_numeric_items(body_text_2)
        subset_ok_2 = all(n in src2_text for n in nums2)
        checks["paper2_numbers_subset_of_input"] = subset_ok_2

        if contains_p_or_ci(src2_text):
            if contains_p_or_ci(body_text_2):
                checks["paper2_significance_included_if_required"] = True

    # Index CSV checks
    csv_rows = csv_read(index_csv_path) if checks["file_index_exists"] else []
    if csv_rows:
        header = csv_rows[0]
        checks["index_header_ok"] = header == ["paper_id", "word_count", "has_all_sections", "numeric_count"]
        data_rows = csv_rows[1:]
        # Expect exactly 2 data rows
        if len(data_rows) == 2:
            ids = [r[0] if len(r) >= 4 else "" for r in data_rows]
            if set(ids) == {"paper1", "paper2"}:
                checks["index_two_rows"] = True

            # Recompute for each
            index_wc_ok = True
            index_sections_ok = True
            index_numeric_ok = True
            # Prepare recomputed info
            recompute: Dict[str, Dict[str, int or bool]] = {}
            if checks["file_paper1_exists"] and checks["paper1_has_all_sections"]:
                recompute["paper1"] = {
                    "word_count": count_words("\n\n".join(paper1_sections[h] for h in required_headers)),
                    "has_all_sections": checks["paper1_has_all_sections"],
                    "numeric_count": len(find_numeric_items("\n\n".join(paper1_sections[h] for h in required_headers))),
                }
            if checks["file_paper2_exists"] and checks["paper2_has_all_sections"]:
                recompute["paper2"] = {
                    "word_count": count_words("\n\n".join(paper2_sections[h] for h in required_headers)),
                    "has_all_sections": checks["paper2_has_all_sections"],
                    "numeric_count": len(find_numeric_items("\n\n".join(paper2_sections[h] for h in required_headers))),
                }

            # Only award if corresponding output abstracts exist and have sections
            for row in data_rows:
                if len(row) < 4:
                    index_wc_ok = False
                    index_sections_ok = False
                    index_numeric_ok = False
                    break
                pid, wc, has_secs, numc = row[0], row[1], row[2], row[3]
                if pid in recompute:
                    try:
                        wc_ok = int(wc) == recompute[pid]["word_count"]
                    except ValueError:
                        wc_ok = False
                    hs_ok = is_truthy(has_secs) == bool(recompute[pid]["has_all_sections"])
                    try:
                        nc_ok = int(numc) == int(recompute[pid]["numeric_count"])
                    except ValueError:
                        nc_ok = False
                    index_wc_ok = index_wc_ok and wc_ok
                    index_sections_ok = index_sections_ok and hs_ok
                    index_numeric_ok = index_numeric_ok and nc_ok
                else:
                    # If we cannot recompute (missing abstracts), do not award these
                    index_wc_ok = False
                    index_sections_ok = False
                    index_numeric_ok = False

            checks["index_word_counts_match"] = index_wc_ok
            checks["index_has_all_sections_match"] = index_sections_ok
            checks["index_numeric_counts_match"] = index_numeric_ok

    # Verification JSON checks
    if checks["file_verification_exists"]:
        try:
            with open(verification_json_path, "r", encoding="utf-8") as f:
                verification = json.load(f)
            if isinstance(verification, dict) and "paper1" in verification and "paper2" in verification:
                p1_list = verification.get("paper1", [])
                p2_list = verification.get("paper2", [])
                if isinstance(p1_list, list) and isinstance(p2_list, list):
                    checks["verification_structure_ok"] = True
                    # Recompute numeric items from abstracts' bodies
                    if checks["file_paper1_exists"] and checks["paper1_has_all_sections"]:
                        body1 = "\n\n".join(paper1_sections[h] for h in required_headers)
                        nums1 = set(find_numeric_items(body1))
                        checks["verification_numbers_match_paper1"] = nums1 == set(p1_list)
                    if checks["file_paper2_exists"] and checks["paper2_has_all_sections"]:
                        body2 = "\n\n".join(paper2_sections[h] for h in required_headers)
                        nums2 = set(find_numeric_items(body2))
                        checks["verification_numbers_match_paper2"] = nums2 == set(p2_list)
        except Exception:
            pass

    # Summary checks
    if checks["file_summary_exists"]:
        summary_text = read_text(summary_md_path)
        bullets = [line for line in summary_text.splitlines() if line.strip().startswith("- ")]
        checks["summary_has_min_bullets"] = len(bullets) >= 3
        low = summary_text.lower()
        checks["summary_mentions_both_papers"] = ("paper1" in low) and ("paper2" in low)

    # Compute reward: fraction of passed checks; ensure 0.0 if no outputs
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Baseline: if output dir missing or key artifacts missing, passed remains small
    reward = (passed / total_checks) if passed > 0 else 0.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()