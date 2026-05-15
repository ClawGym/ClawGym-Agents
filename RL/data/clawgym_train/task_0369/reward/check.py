import json
import csv
import sys
import re
import math
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            return rows
    except Exception:
        return None


def _try_parse_float(x: Any) -> Optional[float]:
    try:
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            s = x.strip()
            if s.endswith("%"):
                s = s[:-1]
            return float(s)
    except Exception:
        return None
    return None


def _floats_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _iso_timestamp_like(s: Any) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        candidate = s
        if s.endswith("Z"):
            candidate = s[:-1] + "+00:00"
        datetime.fromisoformat(candidate)
        return True
    except Exception:
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+\-]\d{2}:\d{2})?$"
        return re.match(pattern, s) is not None


def _compute_aggregates_by_metric(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    metrics: Dict[str, List[float]] = {}
    for r in rows:
        metric = r.get("metric_name")
        val = _try_parse_float(r.get("value"))
        if metric is None or val is None:
            continue
        metrics.setdefault(metric, []).append(val)
    aggregates: Dict[str, Dict[str, float]] = {}
    for m, vals in metrics.items():
        if not vals:
            continue
        n = len(vals)
        mean = sum(vals) / n
        if n > 0:
            var_pop = sum((v - mean) ** 2 for v in vals) / n
            std_pop = math.sqrt(var_pop)
        else:
            std_pop = 0.0
        if n > 1:
            var_samp = sum((v - mean) ** 2 for v in vals) / (n - 1)
            std_samp = math.sqrt(var_samp)
        else:
            std_samp = 0.0
        aggregates[m] = {
            "count": float(n),
            "mean": mean,
            "std_pop": std_pop,
            "std_samp": std_samp,
            "min": min(vals),
            "max": max(vals),
        }
    return aggregates


def _parse_summary_csv(path: Path) -> Optional[Dict[str, Dict[str, float]]]:
    rows = _safe_read_csv_dicts(path)
    if rows is None:
        return None
    def norm(s: str) -> str:
        return s.strip().lower()
    summary: Dict[str, Dict[str, float]] = {}
    if not rows:
        return {}
    headers = list(rows[0].keys())
    header_map = {norm(h): h for h in headers}
    required = ["metric_name", "count", "mean", "std", "min", "max"]
    for req in required:
        if req not in header_map:
            return None
    for r in rows:
        m = r.get(header_map["metric_name"], None)
        if m is None or m == "":
            return None
        count_val = _try_parse_float(r.get(header_map["count"]))
        mean_val = _try_parse_float(r.get(header_map["mean"]))
        std_val = _try_parse_float(r.get(header_map["std"]))
        min_val = _try_parse_float(r.get(header_map["min"]))
        max_val = _try_parse_float(r.get(header_map["max"]))
        if None in (count_val, mean_val, std_val, min_val, max_val):
            return None
        summary[m] = {
            "count": count_val,
            "mean": mean_val,
            "std": std_val,
            "min": min_val,
            "max": max_val,
        }
    return summary


def _median(values: List[float]) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def _extract_section(text: str, needle: str) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if needle.lower() in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if re.match(r"^\(\d+\)", lines[j].strip()):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])


def _find_numbers_in_text(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r"[-+]?\d*\.\d+|[-+]?\d+", text):
        try:
            nums.append(float(m.group()))
        except Exception:
            continue
    return nums


def _find_percents_in_text(text: str) -> List[float]:
    vals = []
    for m in re.finditer(r"([-+]?\d+(?:\.\d+)?)\s*%", text):
        try:
            vals.append(float(m.group(1)))
        except Exception:
            continue
    return vals


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except Exception:
        return 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "summary_file_exists_and_schema": 0.0,
        "summary_values_match": 0.0,
        "sources_json_exists_and_schema": 0.0,
        "sources_entries_per_metric": 0.0,
        "sources_two_numeric_baselines_per_metric": 0.0,
        "report_sections_present": 0.0,
        "report_comparisons_correct": 0.0,
        "email_file_exists_and_subject": 0.0,
        "email_includes_means": 0.0,
        "email_includes_percent_diffs": 0.0,
        "email_has_followup_questions_and_closing": 0.0,
        "trigger_file_present_and_timestamp": 0.0,
    }

    in_csv = workspace / "incoming_results" / "candidate_model_results.csv"
    base = "candidate_model_results"
    summary_csv = workspace / "outputs" / "summary" / f"{base}.summary.csv"
    sources_json = workspace / "outputs" / "web_sources" / f"{base}.sources.json"
    report_md = workspace / "outputs" / "report" / f"{base}.report.md"
    email_txt = workspace / "outputs" / "email" / f"{base}.draft_email.txt"
    trigger_done = workspace / "outputs" / "triggers" / "processed" / f"{base}.done"

    in_rows = _safe_read_csv_dicts(in_csv)
    metrics_in_input: Dict[str, Dict[str, float]] = {}
    if in_rows:
        metrics_in_input = _compute_aggregates_by_metric(in_rows)

    metric_names = list(metrics_in_input.keys())

    parsed_summary = _parse_summary_csv(summary_csv) if summary_csv.exists() else None
    if parsed_summary is not None and metric_names:
        all_metrics_present = all(m in parsed_summary for m in metric_names)
        if all_metrics_present:
            scores["summary_file_exists_and_schema"] = 1.0

        all_match = True
        for m, agg in metrics_in_input.items():
            summ = parsed_summary.get(m)
            if summ is None:
                all_match = False
                break
            if int(round(summ["count"])) != int(round(agg["count"])):
                all_match = False
                break
            if not _floats_close(summ["mean"], agg["mean"], tol=1e-6):
                all_match = False
                break
            if not _floats_close(summ["min"], agg["min"], tol=1e-6):
                all_match = False
                break
            if not _floats_close(summ["max"], agg["max"], tol=1e-6):
                all_match = False
                break
            std_ok = (_floats_close(summ["std"], agg["std_pop"], tol=1e-6) or
                      _floats_close(summ["std"], agg["std_samp"], tol=1e-6))
            if not std_ok:
                all_match = False
                break
        if all_match:
            scores["summary_values_match"] = 1.0

    sources = _safe_load_json(sources_json) if sources_json.exists() else None
    sources_valid_schema = False
    per_metric_entries: Dict[str, List[dict]] = {m: [] for m in metric_names}
    if isinstance(sources, list) and metric_names:
        required_fields = [
            "title",
            "source_type",
            "organization_or_journal",
            "year",
            "domain_context",
            "metric_name",
            "baseline_value",
            "unit_or_notes",
            "url",
            "accessed_at",
        ]
        entries_ok = True
        for entry in sources:
            if not isinstance(entry, dict):
                entries_ok = False
                break
            for rf in required_fields:
                if rf not in entry:
                    entries_ok = False
                    break
            if not entries_ok:
                break
            if not isinstance(entry.get("title"), str) or not entry["title"].strip():
                entries_ok = False
                break
            if not isinstance(entry.get("source_type"), str) or not entry["source_type"].strip():
                entries_ok = False
                break
            if not isinstance(entry.get("organization_or_journal"), str) or not entry["organization_or_journal"].strip():
                entries_ok = False
                break
            try:
                int(entry.get("year"))
            except Exception:
                entries_ok = False
                break
            if not isinstance(entry.get("domain_context"), str) or not entry["domain_context"].strip():
                entries_ok = False
                break
            if not isinstance(entry.get("metric_name"), str) or not entry["metric_name"].strip():
                entries_ok = False
                break
            bv = entry.get("baseline_value", None)
            if not (bv is None or isinstance(bv, (int, float))):
                entries_ok = False
                break
            if not isinstance(entry.get("unit_or_notes"), str):
                entries_ok = False
                break
            if not isinstance(entry.get("url"), str) or not entry["url"].strip():
                entries_ok = False
                break
            if not _iso_timestamp_like(entry.get("accessed_at")):
                entries_ok = False
                break
            metric_in_entry = entry.get("metric_name")
            if metric_in_entry in per_metric_entries:
                per_metric_entries[metric_in_entry].append(entry)
        if entries_ok:
            sources_valid_schema = True

    if sources_valid_schema and metric_names:
        scores["sources_json_exists_and_schema"] = 1.0

    if metric_names:
        if all(len(per_metric_entries.get(m, [])) >= 2 for m in metric_names):
            scores["sources_entries_per_metric"] = 1.0

    numeric_counts: Dict[str, int] = {}
    for m in metric_names:
        numeric_counts[m] = 0
        for e in per_metric_entries.get(m, []):
            bv = e.get("baseline_value")
            if isinstance(bv, (int, float)):
                numeric_counts[m] += 1
    if metric_names and all(numeric_counts[m] >= 2 for m in metric_names):
        scores["sources_two_numeric_baselines_per_metric"] = 1.0

    improvements: Dict[str, float] = {}
    for m in metric_names:
        if numeric_counts.get(m, 0) >= 2:
            numeric_bvs = [float(e["baseline_value"]) for e in per_metric_entries[m] if isinstance(e.get("baseline_value"), (int, float))]
            med = _median(numeric_bvs)
            mean_val = metrics_in_input[m]["mean"]
            if med != 0:
                improvements[m] = 100.0 * (mean_val - med) / med

    report_text = _safe_read_text(report_md) if report_md.exists() else None
    if isinstance(report_text, str):
        has_s1 = "summary table of aggregates" in report_text.lower()
        has_s2 = "baseline sources summary" in report_text.lower()
        has_s3 = "comparison vs median baseline per metric" in report_text.lower()
        has_s4 = "notes on any gaps or assumptions" in report_text.lower()
        if has_s1 and has_s2 and has_s3 and has_s4:
            scores["report_sections_present"] = 1.0

        if improvements:
            comp_sec = _extract_section(report_text, "Comparison vs median baseline per metric")
            comp_ok = True
            if not comp_sec:
                comp_ok = False
            else:
                for m, imp in improvements.items():
                    found_for_metric = False
                    for line in comp_sec.splitlines():
                        if m.lower() in line.lower():
                            for p in _find_percents_in_text(line):
                                if abs(p - imp) <= 1.0:
                                    found_for_metric = True
                                    break
                        if found_for_metric:
                            break
                    if not found_for_metric:
                        for p in _find_percents_in_text(comp_sec):
                            if abs(p - imp) <= 1.0:
                                found_for_metric = True
                                break
                    if not found_for_metric:
                        comp_ok = False
                        break
            if comp_ok:
                scores["report_comparisons_correct"] = 1.0

    email_text = _safe_read_text(email_txt) if email_txt.exists() else None
    if isinstance(email_text, str):
        lines = [ln for ln in email_text.splitlines()]
        first_nonempty = None
        for ln in lines:
            if ln.strip():
                first_nonempty = ln
                break
        if first_nonempty and first_nonempty.strip().lower().startswith("subject:"):
            scores["email_file_exists_and_subject"] = 1.0

        means_ok = True
        if metric_names:
            for m in metric_names:
                mean_val = metrics_in_input[m]["mean"]
                found = False
                for ln in lines:
                    if m.lower() in ln.lower():
                        for num in _find_numbers_in_text(ln):
                            if abs(num - mean_val) <= 0.01:
                                found = True
                                break
                    if found:
                        break
                if not found:
                    for num in _find_numbers_in_text(email_text):
                        if abs(num - mean_val) <= 0.01:
                            found = True
                            break
                if not found:
                    means_ok = False
                    break
        else:
            means_ok = False
        if means_ok:
            scores["email_includes_means"] = 1.0

        if improvements:
            perc_ok = True
            percents_in_email = _find_percents_in_text(email_text)
            for m, imp in improvements.items():
                match_found = any(abs(p - imp) <= 1.0 for p in percents_in_email)
                if not match_found:
                    perc_ok = False
                    break
            if perc_ok:
                scores["email_includes_percent_diffs"] = 1.0

        question_lines = [ln for ln in lines if "?" in ln]
        closing_ok = False
        closing_candidates = ["regards", "sincerely", "best", "thank you", "thanks"]
        tail_text = "\n".join(lines[-10:]).lower() if lines else ""
        if any(phrase in tail_text for phrase in closing_candidates):
            closing_ok = True
        if len(question_lines) >= 2 and closing_ok:
            scores["email_has_followup_questions_and_closing"] = 1.0

    if trigger_done.exists():
        out_paths = [p for p in [summary_csv, sources_json, report_md, email_txt] if p.exists()]
        if out_paths:
            latest_out_mtime = max(_mtime(p) for p in out_paths)
            if _mtime(trigger_done) >= latest_out_mtime:
                scores["trigger_file_present_and_timestamp"] = 1.0
        else:
            scores["trigger_file_present_and_timestamp"] = 0.0

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
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()