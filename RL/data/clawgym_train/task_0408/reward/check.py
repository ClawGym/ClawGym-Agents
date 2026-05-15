import json
import sys
import subprocess
import re
import csv
import tempfile
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_tsv_entrepreneurship(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for r in reader:
                rows.append({
                    "region": r["region"],
                    "population": int(r["population"]),
                    "new_businesses": int(r["new_businesses"]),
                })
        return rows
    except Exception:
        return None


def _compute_expected_summary(rows: List[Dict[str, Any]]) -> Tuple[float, List[Dict[str, Any]]]:
    total_pop = 0
    total_new = 0
    per_region: List[Dict[str, Any]] = []
    for r in rows:
        total_pop += r["population"]
        total_new += r["new_businesses"]
        rate = (r["new_businesses"] / r["population"]) * 1000.0
        per_region.append({
            "region": r["region"],
            "rate_per_1000": round(rate, 2),
        })
    overall = round((total_new / total_pop) * 1000.0, 2) if total_pop > 0 else 0.0
    top3 = sorted(per_region, key=lambda x: x["rate_per_1000"], reverse=True)[:3]
    return overall, top3


def _approx_equal_two_decimals(a: Any, b: Any) -> bool:
    try:
        return round(float(a), 2) == round(float(b), 2)
    except Exception:
        return False


def _extract_section(text: str) -> Optional[str]:
    m = re.search(r"<!-- START DATA SUMMARY -->(.*?)<!-- END DATA SUMMARY -->", text, re.DOTALL)
    return m.group(1).strip() if m else None


def _extract_pre_section(text: str) -> Optional[str]:
    m = re.search(r"^(.*)<!-- START DATA SUMMARY -->", text, re.DOTALL)
    return m.group(1) if m else None


def _extract_post_section(text: str) -> Optional[str]:
    m = re.search(r"<!-- END DATA SUMMARY -->(.*)$", text, re.DOTALL)
    return m.group(1) if m else None


def _normalize_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = s.split("\n")
    lines = [ln.rstrip() for ln in lines]
    return "\n".join(lines).strip("\n")


def _run_python_script(python_exe: str, args: List[str], cwd: Path, timeout: int = 30) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            [python_exe] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return 1, "", str(e)


def _run_aggregator_and_compare(workspace: Path, summary: dict) -> bool:
    script_path = workspace / "scripts" / "aggregate.py"
    tsv_path = workspace / "input" / "entrepreneurship.tsv"
    if not script_path.exists() or not tsv_path.exists():
        return False
    try:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "summary.json"
            rc, out, err = _run_python_script(
                sys.executable,
                [str(script_path), str(tsv_path), str(out_path)],
                workspace
            )
            if rc != 0:
                return False
            gen = _safe_load_json(out_path)
            if gen is None:
                return False
            # Compare dictionaries exactly
            return gen == summary
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_json_present_and_parseable": 0.0,
        "summary_structure_and_metadata_valid": 0.0,
        "summary_values_correct_vs_tsv": 0.0,
        "aggregator_reproduces_summary": 0.0,
        "validate_summary_script_passed": 0.0,
        "brief_section_content_correct": 0.0,
        "brief_other_content_unchanged": 0.0,
        "check_brief_consistency_script_passed": 0.0,
    }

    summary_path = workspace / "data" / "summary.json"
    tsv_path = workspace / "input" / "entrepreneurship.tsv"
    brief_path = workspace / "docs" / "policy_brief.md"
    validate_script = workspace / "tests" / "validate_summary.py"
    consistency_script = workspace / "tests" / "check_brief_consistency.py"

    # Load summary.json
    summary = None
    if summary_path.exists():
        summary = _safe_load_json(summary_path)
    if summary is not None:
        scores["summary_json_present_and_parseable"] = 1.0

    # Validate summary structure and metadata
    structure_ok = False
    if summary is not None and isinstance(summary, dict):
        has_keys = all(k in summary for k in [
            "source_file",
            "year",
            "overall_avg_new_business_rate_per_1000",
            "top_regions_by_rate"
        ])
        types_ok = False
        if has_keys:
            try:
                source_ok = summary["source_file"] == "input/entrepreneurship.tsv"
                year_ok = int(summary["year"]) == 2023
                overall = summary["overall_avg_new_business_rate_per_1000"]
                overall_ok = isinstance(overall, (int, float))
                top = summary["top_regions_by_rate"]
                top_ok = isinstance(top, list) and len(top) == 3 and all(
                    isinstance(item, dict)
                    and "region" in item
                    and "rate_per_1000" in item
                    and isinstance(item["region"], str)
                    and isinstance(item["rate_per_1000"], (int, float))
                    for item in top
                )
                types_ok = source_ok and year_ok and overall_ok and top_ok
            except Exception:
                types_ok = False
        structure_ok = has_keys and types_ok
    if structure_ok:
        scores["summary_structure_and_metadata_valid"] = 1.0

    # Validate summary values vs TSV
    values_ok = False
    if structure_ok:
        rows = _parse_tsv_entrepreneurship(tsv_path)
        if rows is not None:
            exp_overall, exp_top3 = _compute_expected_summary(rows)
            got_overall = summary["overall_avg_new_business_rate_per_1000"]
            got_top = summary["top_regions_by_rate"]
            overall_match = _approx_equal_two_decimals(got_overall, exp_overall)
            top_match = True
            if len(got_top) != 3 or len(exp_top3) != 3:
                top_match = False
            else:
                for i in range(3):
                    g = got_top[i]
                    e = exp_top3[i]
                    if g.get("region") != e.get("region") or not _approx_equal_two_decimals(g.get("rate_per_1000"), e.get("rate_per_1000")):
                        top_match = False
                        break
            values_ok = overall_match and top_match
    if values_ok:
        scores["summary_values_correct_vs_tsv"] = 1.0

    # Check aggregator reproducibility (without modifying workspace)
    if structure_ok:
        if _run_aggregator_and_compare(workspace, summary):
            scores["aggregator_reproduces_summary"] = 1.0

    # Run validate_summary.py test
    if validate_script.exists():
        rc, out, err = _run_python_script(sys.executable, [str(validate_script), str(summary_path)], workspace)
        if rc == 0 and "OK" in (out or ""):
            scores["validate_summary_script_passed"] = 1.0

    # Brief section content correct
    brief_text = _safe_read_text(brief_path) if brief_path.exists() else None
    brief_ok = False
    if brief_text is not None and structure_ok:
        section = _extract_section(brief_text)
        if section is not None:
            avg = float(summary["overall_avg_new_business_rate_per_1000"])
            avg_str = f"{avg:.2f}"
            top = summary["top_regions_by_rate"]
            expected_lines = [
                f"Overall average new business formation rate per 1,000 residents: {avg_str}",
                f"1) {top[0]['region']}: {top[0]['rate_per_1000']:.2f} per 1,000",
                f"2) {top[1]['region']}: {top[1]['rate_per_1000']:.2f} per 1,000",
                f"3) {top[2]['region']}: {top[2]['rate_per_1000']:.2f} per 1,000",
            ]
            lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
            if len(lines) >= 4:
                line_match = True
                for i, exp in enumerate(expected_lines):
                    if i >= len(lines) or lines[i] != exp:
                        line_match = False
                        break
                if line_match:
                    brief_ok = True
    if brief_ok:
        scores["brief_section_content_correct"] = 1.0

    # Check that other parts of the brief are unchanged (pre and post sections), only if section content is correct
    unchanged_ok = False
    if brief_text is not None and brief_ok:
        baseline_brief = (
            "# Regulatory Options to Strengthen New Business Formation\n\n"
            "This brief summarizes recent patterns in new business formation to inform options for regulatory reforms that lower barriers to entrepreneurship while protecting public interests. The data below provide an empirical grounding for proposed measures.\n\n"
            "## Data Summary\n"
            "<!-- START DATA SUMMARY -->\n"
            "[Replace this section with the validated summary derived from data/summary.json as instructed.]\n"
            "<!-- END DATA SUMMARY -->\n\n"
            "## Policy Context\n"
            "Regulatory frameworks can influence entry costs, licensing timelines, and compliance burdens. Evidence-informed adjustments can improve dynamism without compromising safety or consumer protection.\n\n"
            "## Preliminary Options\n"
            "- Streamline licensing processes with clear time limits and online submissions.\n"
            "- Introduce graduated compliance requirements proportional to firm size.\n"
            "- Pilot regulatory sandboxes for innovative business models.\n"
        )
        baseline_pre = _extract_pre_section(baseline_brief)
        baseline_post = _extract_post_section(baseline_brief)
        actual_pre = _extract_pre_section(brief_text)
        actual_post = _extract_post_section(brief_text)
        if baseline_pre is not None and baseline_post is not None and actual_pre is not None and actual_post is not None:
            if _normalize_text(baseline_pre) == _normalize_text(actual_pre) and _normalize_text(baseline_post) == _normalize_text(actual_post):
                unchanged_ok = True
    if unchanged_ok:
        scores["brief_other_content_unchanged"] = 1.0

    # Run check_brief_consistency.py test
    if consistency_script.exists():
        rc2, out2, err2 = _run_python_script(sys.executable, [str(consistency_script)], workspace)
        if rc2 == 0 and "CONSISTENT" in (out2 or ""):
            scores["check_brief_consistency_script_passed"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()