import json
import sys
import re
import csv
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml(text: str) -> Optional[dict]:
    # Minimal indentation-based YAML parser for simple mappings
    try:
        root: dict = {}
        stack: List[Tuple[int, dict]] = [(-1, root)]
        for raw_line in text.splitlines():
            # Remove comments and trailing spaces
            line = raw_line.split("#", 1)[0].rstrip("\r\n")
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            content = line.lstrip(" ")
            if ":" not in content:
                continue
            key, remainder = content.split(":", 1)
            key = key.strip()
            val_str = remainder.strip()
            # Find current parent by indentation
            while stack and indent <= stack[-1][0]:
                stack.pop()
            if not stack:
                # Malformed indentation
                return None
            current = stack[-1][1]
            if val_str == "":
                # Nested mapping
                if key not in current or not isinstance(current.get(key), dict):
                    current[key] = {}
                stack.append((indent, current[key]))
            else:
                # Scalar value
                val = None
                # Try to parse numeric
                try:
                    if re.match(r"^-?\d+\.\d+$", val_str):
                        val = float(val_str)
                    elif re.match(r"^-?\d+$", val_str):
                        val = int(val_str)
                    else:
                        # Keep as string
                        val = val_str
                except Exception:
                    val = val_str
                current[key] = val
        return root
    except Exception:
        return None


def _load_yaml(path: Path) -> Optional[dict]:
    text = _read_text(path)
    if text is None:
        return None
    return _parse_simple_yaml(text)


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _to_float(value: str) -> Optional[float]:
    try:
        s = str(value).strip()
        s = s.replace(",", "")
        s = s.replace("$", "")
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _to_int(value: str) -> Optional[int]:
    try:
        f = _to_float(value)
        if f is None:
            return None
        return int(round(f))
    except Exception:
        return None


def _format_two_decimals(x: float) -> str:
    # Ensure exactly two decimals
    return f"{x:.2f}"


def _compute_expected(proposals: List[Dict[str, str]], thresholds: dict) -> Tuple[Dict[str, dict], List[str]]:
    # Returns mapping by proposal_id with expected calculations and ordered proposal_ids
    elig_rules = thresholds.get("eligibility", {})
    scoring = thresholds.get("scoring", {})
    weights = scoring.get("weights", {})
    max_compliance = elig_rules.get("max_compliance_issues")
    min_past_perf = elig_rules.get("min_past_performance")
    min_readiness = elig_rules.get("min_readiness_score")
    w_need = weights.get("need_index")
    w_impact = weights.get("impact_score")
    w_readiness = weights.get("readiness_score")
    disadv_bonus = scoring.get("disadvantaged_area_bonus")

    expected: Dict[str, dict] = {}
    ordered_ids: List[str] = []

    for row in proposals:
        pid = row.get("proposal_id", "")
        ordered_ids.append(pid)
        c_issues = _to_float(row.get("compliance_issues_count", ""))
        past = _to_float(row.get("past_performance_rating", ""))
        readiness = _to_float(row.get("readiness_score", ""))
        need = _to_float(row.get("need_index", ""))
        impact = _to_float(row.get("impact_score", ""))
        disadv_flag = _to_int(row.get("disadvantaged_area_flag", "0")) or 0
        # Determine eligibility failures
        failures = []
        if c_issues is None or c_issues > max_compliance:
            failures.append("compliance_issues")
        if past is None or past < min_past_perf:
            failures.append("low_past_performance")
        if readiness is None or readiness < min_readiness:
            failures.append("low_readiness")
        is_eligible = len(failures) == 0
        # Composite
        comp = None
        if need is not None and impact is not None and readiness is not None and w_need is not None and w_impact is not None and w_readiness is not None and disadv_bonus is not None:
            comp = (need * w_need) + (impact * w_impact) + (readiness * w_readiness) + (disadv_flag * disadv_bonus)
        expected[pid] = {
            "eligible": is_eligible,
            "failures": failures,
            "composite": comp,
            "need_index": need,
            "impact_score": impact,
            "readiness_score": readiness,
            "disadvantaged_area_flag": disadv_flag,
            "requested_funds": _to_float(row.get("requested_funds", "")),
            "applicant": row.get("applicant", ""),
            "program_stream": row.get("program_stream", ""),
            "region": row.get("region", ""),
        }
    return expected, ordered_ids


def _sort_eligible(expected: Dict[str, dict]) -> List[str]:
    # Sort eligible proposal_ids by composite desc, need_index desc, requested_funds asc
    items = []
    for pid, info in expected.items():
        if info.get("eligible") and info.get("composite") is not None:
            comp = info.get("composite")
            need = info.get("need_index")
            req = info.get("requested_funds")
            # Use tuple for sorting: primary -comp (desc), secondary -need (desc), tertiary req (asc)
            items.append((pid, comp, need, req))
    items.sort(key=lambda x: (-x[1], -x[2], x[3]))
    return [x[0] for x in items]


def _validate_columns(header: List[str], expected_cols: List[str]) -> bool:
    return header == expected_cols


def _parse_first_int_on_line(line: str) -> Optional[int]:
    m = re.search(r"\b(\d+)\b", line)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def _parse_first_percent_on_line(line: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def _parse_first_number_on_line(line: str) -> Optional[float]:
    # Finds currency or plain numbers
    m = re.search(r"[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?", line)
    if m:
        s = m.group(0)
        try:
            s = s.replace("$", "").replace(",", "")
            return float(s)
        except Exception:
            return None
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "eligibility_classification_rowcount_and_columns": 0.0,
        "eligibility_classification_eligible_values_correct": 0.0,
        "eligibility_classification_ineligibility_reasons_presence": 0.0,
        "ranked_recommendations_rowcount_and_columns": 0.0,
        "ranked_recommendations_sort_and_ranking_correct": 0.0,
        "ranked_recommendations_composite_scores_correct": 0.0,
        "summary_totals_and_consistency": 0.0,
        "summary_requested_funds_stats": 0.0,
        "summary_mean_composite_by_program_stream": 0.0,
        "summary_top5_bullets": 0.0,
        "summary_status_note_length": 0.0,
    }

    # Load inputs
    proposals_path = workspace / "input" / "proposals.csv"
    thresholds_path = workspace / "input" / "thresholds.yaml"
    proposals = _read_csv_dicts(proposals_path) if proposals_path.exists() else None
    thresholds = _load_yaml(thresholds_path) if thresholds_path.exists() else None
    if not proposals or not isinstance(thresholds, dict):
        # Cannot proceed; all checks remain 0.0
        return scores

    try:
        expected_map, ordered_ids = _compute_expected(proposals, thresholds)
        expected_sorted_ids = _sort_eligible(expected_map)
    except Exception:
        return scores

    # Derived expected metrics
    total_proposals = len(proposals)
    eligible_ids = [pid for pid, info in expected_map.items() if info.get("eligible")]
    num_eligible = len(eligible_ids)
    # Requested funds stats among eligible
    eligible_funds = [expected_map[pid].get("requested_funds") for pid in eligible_ids if expected_map[pid].get("requested_funds") is not None]
    total_funds = sum(eligible_funds) if eligible_funds else 0.0
    avg_funds = (total_funds / len(eligible_funds)) if eligible_funds else 0.0
    # Means by program_stream among eligible
    stream_scores: Dict[str, List[float]] = {}
    for pid in eligible_ids:
        stream = expected_map[pid].get("program_stream")
        comp = expected_map[pid].get("composite")
        if stream is None or comp is None:
            continue
        stream_scores.setdefault(stream, []).append(comp)
    stream_means: Dict[str, float] = {k: (sum(v) / len(v) if v else 0.0) for k, v in stream_scores.items()}

    # Check eligibility_classification.csv
    elig_out_path = workspace / "output" / "eligibility_classification.csv"
    elig_ok_structure = False
    elig_ok_values = False
    elig_ok_reasons = False
    if elig_out_path.exists():
        try:
            with elig_out_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["proposal_id", "applicant", "program_stream", "region", "eligible", "ineligibility_reasons"]
                if _validate_columns(header, expected_header) and (len(rows) - 1) == total_proposals:
                    elig_ok_structure = True
                # Build map
                data_rows = rows[1:]
                out_map: Dict[str, Dict[str, str]] = {}
                for r in data_rows:
                    if len(r) != len(expected_header):
                        continue
                    out_map[r[0]] = {h: v for h, v in zip(header, r)}
                # Check values
                value_mismatch = False
                reasons_ok = True
                for pid in ordered_ids:
                    exp = expected_map.get(pid, {})
                    out = out_map.get(pid)
                    if out is None:
                        value_mismatch = True
                        reasons_ok = False
                        break
                    out_eligible = out.get("eligible", "").strip()
                    expected_eligible_str = "Yes" if exp.get("eligible") else "No"
                    if out_eligible != expected_eligible_str:
                        value_mismatch = True
                    # Reasons: if eligible -> blank; if not -> non-empty
                    reasons = out.get("ineligibility_reasons", "")
                    if exp.get("eligible"):
                        if reasons.strip() != "":
                            reasons_ok = False
                    else:
                        if reasons.strip() == "":
                            reasons_ok = False
                        # If multiple failures, expect semicolon separation
                        if len(exp.get("failures", [])) > 1 and ";" not in reasons:
                            reasons_ok = False
                elig_ok_values = (not value_mismatch)
                elig_ok_reasons = reasons_ok
        except Exception:
            pass
    scores["eligibility_classification_rowcount_and_columns"] = 1.0 if elig_ok_structure else 0.0
    scores["eligibility_classification_eligible_values_correct"] = 1.0 if elig_ok_values else 0.0
    scores["eligibility_classification_ineligibility_reasons_presence"] = 1.0 if elig_ok_reasons else 0.0

    # Check ranked_recommendations.csv
    ranked_path = workspace / "output" / "ranked_recommendations.csv"
    ranked_ok_structure = False
    ranked_ok_sort = False
    ranked_ok_composite = False
    ranked_rows_data: List[Dict[str, str]] = []
    if ranked_path.exists():
        try:
            with ranked_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames or []
                expected_header = ["rank", "proposal_id", "applicant", "program_stream", "region", "requested_funds", "need_index", "impact_score", "readiness_score", "disadvantaged_area_flag", "composite_score"]
                rows = [row for row in reader]
            if header == expected_header and len(rows) == num_eligible:
                ranked_ok_structure = True
            ranked_rows_data = rows
            # Check order and rank consistency
            # Build expected sorted sequence
            expected_sorted = expected_sorted_ids
            actual_sorted_ids = [row.get("proposal_id", "") for row in ranked_rows_data]
            # Validate ranking order
            sort_ok = (expected_sorted == actual_sorted_ids)
            # Validate rank numbering and fields
            fields_ok = True
            comp_ok = True
            for idx, row in enumerate(ranked_rows_data):
                # rank check
                try:
                    rnk = int(row.get("rank", ""))
                    if rnk != idx + 1:
                        sort_ok = False
                except Exception:
                    sort_ok = False
                pid = row.get("proposal_id", "")
                exp = expected_map.get(pid, {})
                # Verify constituent fields match inputs
                # Numeric comparisons with tolerance for formatting
                for fld in ["requested_funds", "need_index", "impact_score", "readiness_score"]:
                    v = _to_float(row.get(fld, ""))
                    ev = exp.get(fld)
                    if v is None or ev is None or abs(v - ev) > 1e-6:
                        fields_ok = False
                flag_v = _to_int(row.get("disadvantaged_area_flag", ""))
                if flag_v is None or flag_v != exp.get("disadvantaged_area_flag"):
                    fields_ok = False
                # Composite rounding
                comp = exp.get("composite")
                out_comp_str = row.get("composite_score", "").strip()
                if comp is None:
                    comp_ok = False
                else:
                    exp_str = _format_two_decimals(comp)
                    if out_comp_str != exp_str:
                        comp_ok = False
            ranked_ok_sort = sort_ok and fields_ok
            ranked_ok_composite = comp_ok
        except Exception:
            pass
    scores["ranked_recommendations_rowcount_and_columns"] = 1.0 if ranked_ok_structure else 0.0
    scores["ranked_recommendations_sort_and_ranking_correct"] = 1.0 if ranked_ok_sort else 0.0
    scores["ranked_recommendations_composite_scores_correct"] = 1.0 if ranked_ok_composite else 0.0

    # Check summary_report.md
    summary_path = workspace / "output" / "summary_report.md"
    summary_text = _read_text(summary_path) if summary_path.exists() else None
    summary_totals_ok = False
    summary_funds_ok = False
    summary_means_ok = False
    summary_top5_ok = False
    summary_status_ok = False
    if summary_text:
        try:
            lines = [ln.strip() for ln in summary_text.splitlines() if ln.strip() != ""]
            # Totals and consistency: find line with 'Total proposals'
            found_total = None
            for ln in lines:
                if "total proposals" in ln.lower():
                    found_total = _parse_first_int_on_line(ln)
                    break
            # Eligible count and percent
            found_eligible = None
            found_percent = None
            for ln in lines:
                if "eligible" in ln.lower():
                    num = _parse_first_int_on_line(ln)
                    pct = _parse_first_percent_on_line(ln)
                    if num is not None:
                        found_eligible = num
                    if pct is not None:
                        found_percent = pct
                    if found_eligible is not None:
                        break
            # Cross-file consistency: ranked rows count vs eligible count
            ranked_rows_count = len(ranked_rows_data)
            cond_total = (found_total == total_proposals)
            cond_eligible = (found_eligible == num_eligible == ranked_rows_count)
            cond_percent = True
            if found_percent is not None:
                expected_pct = (num_eligible / total_proposals) * 100.0 if total_proposals > 0 else 0.0
                # Allow small rounding tolerance of 0.5 percentage points
                cond_percent = abs(found_percent - expected_pct) <= 0.5
            summary_totals_ok = cond_total and cond_eligible and cond_percent

            # Funds stats: find lines with 'total' and 'requested'/'fund' and 'average'
            total_line_num = None
            avg_line_num = None
            for i, ln in enumerate(lines):
                low = ln.lower()
                if "requested" in low or "fund" in low:
                    if "total" in low:
                        total_line_num = i if total_line_num is None else total_line_num
                    if "average" in low:
                        avg_line_num = i if avg_line_num is None else avg_line_num
            total_parsed = None
            avg_parsed = None
            if total_line_num is not None:
                total_parsed = _parse_first_number_on_line(lines[total_line_num])
            if avg_line_num is not None:
                avg_parsed = _parse_first_number_on_line(lines[avg_line_num])
            if total_parsed is not None and avg_parsed is not None:
                if abs(total_parsed - total_funds) <= 0.5 and abs(avg_parsed - avg_funds) <= 0.5:
                    summary_funds_ok = True

            # Means by program_stream: each stream line present with a number close to mean
            means_ok = True
            for stream, mean_val in stream_means.items():
                # Find a line containing the stream name
                matching = [ln for ln in lines if stream.lower() in ln.lower()]
                if not matching:
                    means_ok = False
                    break
                # From first matching line, extract first number and compare
                num = None
                for cand in matching:
                    n = _parse_first_number_on_line(cand)
                    if n is not None:
                        num = n
                        break
                if num is None or abs(num - mean_val) > 0.05:
                    means_ok = False
                    break
            summary_means_ok = means_ok

            # Top 5 bullets: lines starting with '-' or '*'
            bullet_lines = [ln for ln in lines if ln.startswith("-") or ln.startswith("*")]
            # Build expected top 5 from recomputed sort
            top5 = expected_sorted_ids[:5]
            bullets_ok = True
            for pid in top5:
                info = expected_map[pid]
                app = info.get("applicant", "")
                comp = info.get("composite", 0.0)
                comp_str = _format_two_decimals(comp)
                # Find any bullet line containing pid, applicant, and comp_str
                found = False
                for bl in bullet_lines:
                    if pid in bl and app in bl and comp_str in bl:
                        found = True
                        break
                if not found:
                    bullets_ok = False
                    break
            summary_top5_ok = bullets_ok

            # Status note sentences: count sentences in non-bullet lines
            non_bullets = [ln for ln in lines if not (ln.startswith("-") or ln.startswith("*"))]
            text_nb = " ".join(non_bullets)
            # Remove extra spaces
            text_nb = re.sub(r"\s+", " ", text_nb).strip()
            # Split into sentences
            parts = re.split(r"[.!?]", text_nb)
            sentences = [p.strip() for p in parts if len(p.strip().split()) >= 3]
            # Require between 2 and 3 sentences to match "2–3 sentences"
            if 2 <= len(sentences) <= 3:
                summary_status_ok = True
        except Exception:
            pass

    scores["summary_totals_and_consistency"] = 1.0 if summary_totals_ok else 0.0
    scores["summary_requested_funds_stats"] = 1.0 if summary_funds_ok else 0.0
    scores["summary_mean_composite_by_program_stream"] = 1.0 if summary_means_ok else 0.0
    scores["summary_top5_bullets"] = 1.0 if summary_top5_ok else 0.0
    scores["summary_status_note_length"] = 1.0 if summary_status_ok else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()