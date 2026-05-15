import json
import sys
import csv
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _to_float(val: str) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if s == "" or s.lower() == "na" or s.lower() == "null":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _is_adverse(event_val: str) -> bool:
    if event_val is None:
        return False
    return str(event_val).strip().lower() != "none"


def _discover_outcome_files(workspace: Path) -> List[Path]:
    base = workspace / "input" / "clinical_data"
    if not base.exists():
        return []
    files = []
    for p in base.rglob("*_outcomes.csv"):
        if p.is_file():
            files.append(p)
    return sorted(files)


def _gather_records(files: List[Path]) -> List[Dict]:
    records = []
    for p in files:
        data = _load_csv_dicts(p)
        if data is None:
            # If any file is malformed, we skip adding its rows but grading will fail where dependent
            continue
        for row in data:
            rec = {
                "patient_id": row.get("patient_id"),
                "treatment": (row.get("treatment") or "").strip().lower(),
                "pre_gad7": _to_float(row.get("pre_gad7")),
                "post_gad7": _to_float(row.get("post_gad7")),
                "adverse_event": (row.get("adverse_event") or "").strip(),
            }
            records.append(rec)
    return records


def _complete_cases(records: List[Dict]) -> List[Dict]:
    cc = []
    for r in records:
        if r.get("pre_gad7") is not None and r.get("post_gad7") is not None:
            cc.append(r)
    return cc


def _round1(x: float) -> float:
    return round(x, 1)


def _compute_metrics(records: List[Dict]) -> Dict[str, Dict[str, float]]:
    # Compute per treatment group and overall
    by_group: Dict[str, List[Dict]] = {}
    for r in records:
        grp = r.get("treatment", "").strip().lower()
        if grp == "":
            continue
        by_group.setdefault(grp, []).append(r)
    metrics: Dict[str, Dict[str, float]] = {}

    def metrics_for(group_records: List[Dict]) -> Dict[str, float]:
        n = len(group_records)
        if n == 0:
            return {
                "n_patients": 0.0,
                "mean_pre_gad7": 0.0,
                "mean_post_gad7": 0.0,
                "mean_reduction": 0.0,
                "pct_improved": 0.0,
                "pct_clinically_significant": 0.0,
                "adverse_event_rate": 0.0,
            }
        pre_vals = [r["pre_gad7"] for r in group_records]
        post_vals = [r["post_gad7"] for r in group_records]
        reductions = [r["pre_gad7"] - r["post_gad7"] for r in group_records]
        improved = sum(1 for r in group_records if (r["pre_gad7"] > r["post_gad7"]))
        clinically_sig = sum(1 for r in group_records if (r["pre_gad7"] - r["post_gad7"] >= 5.0))
        adverse = sum(1 for r in group_records if _is_adverse(r.get("adverse_event")))
        mean_pre = sum(pre_vals) / n
        mean_post = sum(post_vals) / n
        mean_red = sum(reductions) / n
        pct_improved = (improved / n) * 100.0
        pct_cs = (clinically_sig / n) * 100.0
        adverse_rate = (adverse / n) * 100.0
        return {
            "n_patients": float(n),
            "mean_pre_gad7": _round1(mean_pre),
            "mean_post_gad7": _round1(mean_post),
            "mean_reduction": _round1(mean_red),
            "pct_improved": _round1(pct_improved),
            "pct_clinically_significant": _round1(pct_cs),
            "adverse_event_rate": _round1(adverse_rate),
        }

    # Per detected group
    for g, recs in by_group.items():
        metrics[g] = metrics_for(recs)

    # Overall across all
    all_recs = [r for _, recs in by_group.items() for r in recs]
    metrics["overall"] = metrics_for(all_recs)
    return metrics


def _parse_csv_file(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _safe_float_eq(a: Optional[float], b: Optional[float], tol: float = 0.05) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _extract_numbers(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r'[-+]?\d+(?:\.\d+)?', text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            pass
    return nums


def _find_sentences(text: str) -> List[str]:
    # Split into sentences naively by ., ?, ! followed by space or end
    # Keep delimiters by replacing with period and splitting
    # Normalize newlines
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    # Add a period after line breaks to help sentence detection
    t = re.sub(r'\n+', '\n', t)
    # Split sentences using punctuation
    sentences = re.split(r'(?<=[.!?])\s+', t.strip())
    # Clean empty
    sentences = [s.strip() for s in sentences if s.strip()]
    return sentences


def _paragraphs(text: str) -> List[str]:
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    paras = [p.strip() for p in re.split(r'\n\s*\n', t) if p.strip()]
    return paras


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "aggregates_exists_and_format": 0.0,
        "aggregates_groups_order": 0.0,
        "aggregates_values_correct_acupuncture": 0.0,
        "aggregates_values_correct_herbal": 0.0,
        "aggregates_values_correct_overall": 0.0,
        "findings_lists_sources_and_count": 0.0,
        "findings_reports_group_ns": 0.0,
        "findings_paragraph_mentions_reductions_and_adverse": 0.0,
        "email_length_greeting_and_genericity": 0.0,
        "email_includes_stats_acupuncture": 0.0,
        "email_includes_stats_herbal": 0.0,
    }

    # Discover inputs
    input_files = _discover_outcome_files(workspace)
    basenames = [p.name for p in input_files]
    all_rows = _gather_records(input_files)
    cc_rows = _complete_cases(all_rows)
    metrics_by_group = _compute_metrics(cc_rows)

    # Expected column order for aggregates
    expected_columns = [
        "group",
        "n_patients",
        "mean_pre_gad7",
        "mean_post_gad7",
        "mean_reduction",
        "pct_improved",
        "pct_clinically_significant",
        "adverse_event_rate",
    ]
    expected_groups_order = ["acupuncture", "herbal", "overall"]

    # 1) Aggregated metrics CSV
    aggregates_path = workspace / "output" / "summary" / "aggregates.csv"
    if aggregates_path.exists():
        parsed = _parse_csv_file(aggregates_path)
        try:
            with aggregates_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        # Check header
        if header is not None and header == expected_columns:
            scores["aggregates_exists_and_format"] = 1.0
        else:
            scores["aggregates_exists_and_format"] = 0.0

        # Check groups order and presence exactly 3 rows
        if parsed is not None:
            groups = [row.get("group", "").strip().lower() for row in parsed]
            if groups == expected_groups_order and len(parsed) == 3:
                scores["aggregates_groups_order"] = 1.0
            else:
                scores["aggregates_groups_order"] = 0.0

            # Compare values for each group
            def check_row(row: Dict[str, str], group: str) -> bool:
                exp = metrics_by_group.get(group)
                if exp is None:
                    return False
                # Parse row values
                try:
                    n_pat = int(float(row.get("n_patients", "nan")))
                except Exception:
                    return False
                def pf(key: str) -> Optional[float]:
                    try:
                        return float(row.get(key, "nan"))
                    except Exception:
                        return None
                checks = []
                checks.append(n_pat == int(exp["n_patients"]))
                checks.append(_safe_float_eq(pf("mean_pre_gad7"), exp["mean_pre_gad7"]))
                checks.append(_safe_float_eq(pf("mean_post_gad7"), exp["mean_post_gad7"]))
                checks.append(_safe_float_eq(pf("mean_reduction"), exp["mean_reduction"]))
                # Percentages must be between 0 and 100 and equal expected rounded
                for key in ["pct_improved", "pct_clinically_significant", "adverse_event_rate"]:
                    val = pf(key)
                    checks.append(val is not None and 0.0 <= val <= 100.0)
                    checks.append(_safe_float_eq(val, exp[key]))
                return all(checks)

            if parsed is not None and len(parsed) >= 1:
                # acupuncture
                row_a = parsed[0] if len(parsed) > 0 else None
                if row_a and row_a.get("group", "").strip().lower() == "acupuncture" and check_row(row_a, "acupuncture"):
                    scores["aggregates_values_correct_acupuncture"] = 1.0
                # herbal
                row_h = parsed[1] if len(parsed) > 1 else None
                if row_h and row_h.get("group", "").strip().lower() == "herbal" and check_row(row_h, "herbal"):
                    scores["aggregates_values_correct_herbal"] = 1.0
                # overall
                row_o = parsed[2] if len(parsed) > 2 else None
                if row_o and row_o.get("group", "").strip().lower() == "overall" and check_row(row_o, "overall"):
                    scores["aggregates_values_correct_overall"] = 1.0

    # 2) Findings summary
    findings_path = workspace / "output" / "summary" / "findings.md"
    findings_text = _read_text(findings_path) if findings_path.exists() else None
    if findings_text is not None and len(input_files) > 0:
        # 2a: Includes basenames and total number of files detected
        basenames_present = all(b in findings_text for b in basenames)
        count_num = len(input_files)
        count_pattern = re.compile(rf"\b{count_num}\b")
        count_present = bool(count_pattern.search(findings_text))
        if basenames_present and count_present:
            scores["findings_lists_sources_and_count"] = 1.0

        # 2b: Number of patients analyzed per group (complete cases)
        group_ns_ok = True
        for g in ["acupuncture", "herbal"]:
            n = int(metrics_by_group.get(g, {}).get("n_patients", 0.0))
            # Find a line containing group name and the number
            lines = findings_text.splitlines()
            found = False
            for ln in lines:
                if g in ln.lower():
                    nums = _extract_numbers(ln)
                    if any(int(round(x)) == n for x in nums):
                        found = True
                        break
            if not found:
                group_ns_ok = False
                break
        if group_ns_ok:
            scores["findings_reports_group_ns"] = 1.0

        # 2c: One short paragraph (3–5 sentences) synthesizing key results,
        # mentioning mean reductions and adverse event rates for each group.
        # We will look for a paragraph containing both groups and containing
        # numbers close to mean_reduction and adverse_event_rate for each.
        target = None
        paras = _paragraphs(findings_text)
        for p in paras:
            # Count sentences in this paragraph
            sents = _find_sentences(p)
            # limit sentences to those within this paragraph by splitting on sentence enders within p
            # Re-split using paragraph content
            sents = re.split(r'(?<=[.!?])\s+', p)
            sents = [s.strip() for s in sents if s.strip()]
            if 3 <= len(sents) <= 5:
                target = p
                # Now verify content requirements
                ok_groups = {"acupuncture": False, "herbal": False}
                for grp in ok_groups.keys():
                    # Collect all sentences in this paragraph that mention the group
                    grp_sents = [s for s in sents if grp in s.lower()]
                    # We need numbers close to mean_reduction and adverse_event_rate
                    exp_mr = metrics_by_group.get(grp, {}).get("mean_reduction", None)
                    exp_ae = metrics_by_group.get(grp, {}).get("adverse_event_rate", None)
                    has_mr = False
                    has_ae = False
                    for s in grp_sents:
                        nums = _extract_numbers(s)
                        if exp_mr is not None and any(_safe_float_eq(x, exp_mr, tol=0.2) for x in nums):
                            has_mr = True
                        if exp_ae is not None and any(_safe_float_eq(x, exp_ae, tol=0.2) for x in nums):
                            has_ae = True
                    ok_groups[grp] = has_mr and has_ae
                if all(ok_groups.values()):
                    scores["findings_paragraph_mentions_reductions_and_adverse"] = 1.0
                    break

    # 3) Patient email rewrite
    email_path = workspace / "output" / "communications" / "patient_email_rewrite.txt"
    email_text = _read_text(email_path) if email_path.exists() else None
    if email_text is not None and len(input_files) > 0:
        # 3a: 150–170 words and includes "Hello", and no draft placeholders
        words = re.findall(r"\b\w+\b", email_text)
        word_count = len(words)
        has_hello = "hello" in email_text.lower()
        no_placeholders = ("[Patient Name]" not in email_text) and ("[Clinician Name]" not in email_text)
        if 150 <= word_count <= 170 and has_hello and no_placeholders:
            scores["email_length_greeting_and_genericity"] = 1.0

        # 3b and 3c: Include computed mean reduction, pct clinically significant, and AE rate for each group
        # We will validate that for each group, in sentences mentioning that group, the numbers are present.
        sentences = _find_sentences(email_text)
        # Group sentences by group keyword
        lower_sentences = [(s, s.lower()) for s in sentences]
        def check_group_stats(grp: str) -> bool:
            grp_sents = [orig for (orig, low) in lower_sentences if grp in low]
            if not grp_sents:
                return False
            exp_mr = metrics_by_group.get(grp, {}).get("mean_reduction", None)
            exp_cs = metrics_by_group.get(grp, {}).get("pct_clinically_significant", None)
            exp_ae = metrics_by_group.get(grp, {}).get("adverse_event_rate", None)
            if exp_mr is None or exp_cs is None or exp_ae is None:
                return False
            has_mr = False
            has_cs = False
            has_ae = False
            for s in grp_sents:
                nums = _extract_numbers(s)
                if any(_safe_float_eq(x, exp_mr, tol=0.2) for x in nums):
                    has_mr = True
                if any(_safe_float_eq(x, exp_cs, tol=0.2) for x in nums):
                    has_cs = True
                if any(_safe_float_eq(x, exp_ae, tol=0.2) for x in nums):
                    has_ae = True
            return has_mr and has_cs and has_ae

        if check_group_stats("acupuncture"):
            scores["email_includes_stats_acupuncture"] = 1.0
        if check_group_stats("herbal"):
            scores["email_includes_stats_herbal"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()