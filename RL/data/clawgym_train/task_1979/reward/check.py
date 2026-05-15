import json
import sys
import re
from pathlib import Path
from typing import Tuple, List, Dict, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _parse_csv_for_expected(csv_path: Path) -> Tuple[List[str], List[str], str, List[Tuple[str, str, int, str, str]]]:
    # Replicate scripts/summarize.py logic deterministically
    summaries: List[str] = []
    warnings: List[str] = []
    groups: Dict[Tuple[str, str], List[Tuple[Optional[float], Optional[float]]]] = {}
    if not csv_path.exists():
        done_line = "DONE groups=0 warnings=0"
        return summaries, warnings, done_line, []
    try:
        text_lines = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        done_line = "DONE groups=0 warnings=0"
        return summaries, warnings, done_line, []
    if not text_lines:
        done_line = "DONE groups=0 warnings=0"
        return summaries, warnings, done_line, []
    header = None
    rows: List[Dict[str, str]] = []
    for idx, line in enumerate(text_lines):
        if idx == 0:
            header = [h.strip() for h in line.split(",")]
            continue
        parts = line.split(",")
        while len(parts) < len(header):
            parts.append("")
        row = {header[i]: parts[i] if i < len(parts) else "" for i in range(len(header))}
        rows.append(row)
    row_idx = 2  # as in summarize.py
    for row in rows:
        method = (row.get("method") or "").strip()
        dataset = (row.get("dataset") or "").strip()
        metric_name = (row.get("metric_name") or "").strip().lower()
        metric_value = (row.get("metric_value") or "").strip()
        runtime_val = (row.get("runtime_sec") or "").strip()
        rmse = None
        runtime = None
        if metric_name != "rmse":
            if metric_name:
                warnings.append(f"WARN ignored non-rmse metric at row {row_idx}: {metric_name}")
            row_idx += 1
            continue
        if metric_value == "" or metric_value is None:
            warnings.append(f"WARN missing or invalid rmse at row {row_idx}")
        else:
            try:
                rmse = float(metric_value)
            except Exception:
                warnings.append(f"WARN missing or invalid rmse at row {row_idx}")
        if runtime_val != "" and runtime_val is not None:
            try:
                runtime = float(runtime_val)
            except Exception:
                pass
        if rmse is not None:
            groups.setdefault((method, dataset), []).append((rmse, runtime))
        row_idx += 1
    keys = sorted(groups.keys(), key=lambda k: (k[0], k[1]))
    aggregates_for_check: List[Tuple[str, str, int, str, str]] = []
    for (method, dataset) in keys:
        vals = groups[(method, dataset)]
        if not vals:
            continue
        rmses = [v[0] for v in vals if v[0] is not None]
        runtimes = [v[1] for v in vals if v[1] is not None]
        mean_rmse = sum(rmses) / len(rmses)
        mean_runtime = sum(runtimes) / len(runtimes) if runtimes else None
        mean_runtime_str = f"{mean_runtime}" if mean_runtime is not None else "NA"
        rmse_str = f"{round(mean_rmse, 3)}"
        runtime_str = f"{round(mean_runtime, 3) if mean_runtime is not None else mean_runtime_str}"
        line = f"SUMMARY method={method} dataset={dataset} count={len(rmses)} mean_rmse={rmse_str} mean_runtime_sec={runtime_str}"
        summaries.append(line)
        aggregates_for_check.append((method, dataset, len(rmses), rmse_str, runtime_str))
    done_line = f"DONE groups={len(keys)} warnings={len(warnings)}"
    return summaries, warnings, done_line, aggregates_for_check


def _extract_sections(md_text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current_title: Optional[str] = None
    for line in md_text.splitlines():
        m = re.match(r"^\s{0,3}\#{1,6}\s*(.+?)\s*$", line)
        if m:
            current_title = m.group(1).strip().lower()
            sections[current_title] = []
        else:
            if current_title is not None:
                sections[current_title].append(line)
    return sections


def _find_section(sections: Dict[str, List[str]], title_candidates: List[str]) -> Optional[List[str]]:
    for key, content in sections.items():
        for cand in title_candidates:
            if cand in key:
                return content
    return None


def _count_sentences(text: str) -> int:
    parts = re.split(r"[.!?]+", text)
    count = sum(1 for p in parts if p.strip())
    return count


def _contains_all_substrings(text: str, subs: List[str]) -> bool:
    return all(s in text for s in subs)


def _word_count(text: str) -> int:
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summarize_log_exists": 0.0,
        "summarize_log_expected_summaries_present": 0.0,
        "summarize_log_expected_warnings_present": 0.0,
        "summarize_log_done_line_present": 0.0,
        "method_comparison_exists": 0.0,
        "method_comparison_has_required_sections": 0.0,
        "methods_section_has_exact_method_names_and_length": 0.0,
        "datasets_section_lists_all": 0.0,
        "aggregates_section_exact_values": 0.0,
        "warnings_section_quotes_warnings": 0.0,
        "repro_section_has_exact_command": 0.0,
        "methods_overview_edited_exists": 0.0,
        "methods_overview_method_names_corrected": 0.0,
        "methods_overview_eigenvectors_claim_softened": 0.0,
        "methods_overview_metrics_consistency_rmse": 0.0,
        "status_email_final_exists": 0.0,
        "status_email_has_subject": 0.0,
        "status_email_under_120_words": 0.0,
        "status_email_includes_required_metrics_sentence": 0.0,
        "status_email_has_next_step_recommendation": 0.0,
    }

    # Compute expected outputs from the CSV (canonical for grading)
    csv_path = workspace / "data" / "experiments.csv"
    expected_summaries, expected_warnings, expected_done, expected_aggregates = _parse_csv_for_expected(csv_path)
    expected_datasets = sorted({ds for _, ds, _, _, _ in expected_aggregates})
    expected_methods = sorted({m for m, _, _, _, _ in expected_aggregates})

    # 1) Check outputs/summarize.log
    log_path = workspace / "outputs" / "summarize.log"
    log_text = _read_text_safe(log_path)
    if log_text is not None:
        scores["summarize_log_exists"] = 1.0
        # Check summaries
        if expected_summaries:
            if all(line in log_text for line in expected_summaries):
                scores["summarize_log_expected_summaries_present"] = 1.0
        # Check warnings
        if expected_warnings:
            if all(w in log_text for w in expected_warnings):
                scores["summarize_log_expected_warnings_present"] = 1.0
        else:
            scores["summarize_log_expected_warnings_present"] = 1.0
        # Check DONE line
        if expected_done and expected_done in log_text:
            scores["summarize_log_done_line_present"] = 1.0

    # 2) Check outputs/method_comparison.md
    report_path = workspace / "outputs" / "method_comparison.md"
    report_text = _read_text_safe(report_path)
    if report_text is not None:
        scores["method_comparison_exists"] = 1.0
        sections = _extract_sections(report_text)
        methods_sec = _find_section(sections, ["methods"])
        datasets_sec = _find_section(sections, ["datasets"])
        aggregates_sec = _find_section(sections, ["aggregates"])
        warnings_sec = _find_section(sections, ["notable warnings", "warnings"])
        repro_sec = _find_section(sections, ["repro", "reproduction", "command"])
        if all(sec is not None for sec in [methods_sec, datasets_sec, aggregates_sec, warnings_sec, repro_sec]):
            scores["method_comparison_has_required_sections"] = 1.0

        # Methods section: contains both method names exactly and 2-3 sentences total
        if methods_sec is not None and expected_methods:
            methods_content = "\n".join(methods_sec)
            methods_ok = all(m in methods_content for m in expected_methods)
            sent_count = _count_sentences(methods_content)
            if methods_ok and (2 <= sent_count <= 3):
                scores["methods_section_has_exact_method_names_and_length"] = 1.0

        # Datasets section
        if datasets_sec is not None and expected_datasets:
            ds_text = "\n".join(datasets_sec)
            if all(ds in ds_text for ds in expected_datasets):
                scores["datasets_section_lists_all"] = 1.0

        # Aggregates section: ensure each expected (method,dataset) with exact numbers appears
        if aggregates_sec is not None and expected_aggregates:
            agg_text = "\n".join(aggregates_sec)
            found_all = True
            for method, dataset, count, rmse_str, runtime_str in expected_aggregates:
                pattern = f"method={method} dataset={dataset} count={count} mean_rmse={rmse_str} mean_runtime_sec={runtime_str}"
                if pattern not in agg_text:
                    found_all = False
                    break
            if found_all:
                scores["aggregates_section_exact_values"] = 1.0

        # Notable Warnings: quotes each WARN line verbatim
        if warnings_sec is not None:
            warn_text = "\n".join(warnings_sec)
            if expected_warnings:
                if all(w in warn_text for w in expected_warnings):
                    scores["warnings_section_quotes_warnings"] = 1.0
            else:
                scores["warnings_section_quotes_warnings"] = 1.0

        # Repro section: exact command
        if repro_sec is not None:
            repro_text = "\n".join(repro_sec)
            if "python3 scripts/summarize.py data/experiments.csv" in repro_text:
                scores["repro_section_has_exact_command"] = 1.0

    # 3) Check outputs/methods_overview_edited.md
    edited_path = workspace / "outputs" / "methods_overview_edited.md"
    edited_text = _read_text_safe(edited_path)
    if edited_text is not None:
        scores["methods_overview_edited_exists"] = 1.0
        names_ok = True
        if expected_methods:
            names_ok = all(m in edited_text for m in expected_methods)
        no_bad_names = ("SparseLaplacianGraph" not in edited_text) and ("ConvexRelaxation (QP)" not in edited_text)
        if names_ok and no_bad_names:
            scores["methods_overview_method_names_corrected"] = 1.0
        if "always unique" not in edited_text:
            scores["methods_overview_eigenvectors_claim_softened"] = 1.0
        lt = edited_text.lower()
        mentions_rmse = "rmse" in lt
        mentions_mae = "mae" in lt
        if mentions_rmse or not mentions_mae:
            scores["methods_overview_metrics_consistency_rmse"] = 1.0

    # 4) Check outputs/status_email_final.md
    email_path = workspace / "outputs" / "status_email_final.md"
    email_text = _read_text_safe(email_path)
    if email_text is not None:
        scores["status_email_final_exists"] = 1.0
        lines = [ln for ln in email_text.splitlines()]
        first_nonempty = ""
        for ln in lines:
            if ln.strip():
                first_nonempty = ln.strip()
                break
        if first_nonempty.lower().startswith("subject:"):
            scores["status_email_has_subject"] = 1.0
        if _word_count(email_text) <= 120:
            scores["status_email_under_120_words"] = 1.0
        metrics_ok = True
        required_subs = []
        # Build expected RMSE strings for both datasets and methods
        def _find_rmse(method: str, dataset: str) -> Optional[str]:
            for m, d, _, rmse, _ in expected_aggregates:
                if m == method and d == dataset:
                    return rmse
            return None

        datasets = sorted({d for _, d, _, _, _ in expected_aggregates})
        methods = sorted({m for m, _, _, _, _ in expected_aggregates})
        # Expect specifically beam_vibration and truss_noise, and both methods
        beam_rmse_crqp = _find_rmse("ConvexRelaxationQP", "beam_vibration")
        beam_rmse_sgl = _find_rmse("SparseGraphLaplacian", "beam_vibration")
        truss_rmse_crqp = _find_rmse("ConvexRelaxationQP", "truss_noise")
        truss_rmse_sgl = _find_rmse("SparseGraphLaplacian", "truss_noise")
        if all(v is not None for v in [beam_rmse_crqp, beam_rmse_sgl, truss_rmse_crqp, truss_rmse_sgl]):
            required_subs = [
                "beam_vibration",
                f"ConvexRelaxationQP {beam_rmse_crqp}",
                f"SparseGraphLaplacian {beam_rmse_sgl}",
                "truss_noise",
                f"ConvexRelaxationQP {truss_rmse_crqp}",
                f"SparseGraphLaplacian {truss_rmse_sgl}",
            ]
            if not _contains_all_substrings(email_text, required_subs):
                metrics_ok = False
            sent_splits = re.split(r"(?<=[.!?])\s+", email_text.strip())
            dataset_sentences = [s for s in sent_splits if ("beam_vibration" in s and "truss_noise" in s)]
            if len(dataset_sentences) != 1:
                metrics_ok = False
        else:
            metrics_ok = False
        if metrics_ok:
            scores["status_email_includes_required_metrics_sentence"] = 1.0
        lower_email = email_text.lower()
        if any(k in lower_email for k in ["next", "recommend", "suggest", "plan", "propose", "follow-up"]):
            scores["status_email_has_next_step_recommendation"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()