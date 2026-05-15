import json
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Set


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Any]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _parse_catalog_yaml(path: Path) -> Optional[Dict[str, Set[str]]]:
    """
    Minimal parser for the specific YAML structure in input/metrics_catalog.yaml.
    Returns dict: metric_name -> set(labels)
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    in_metrics = False
    current_name = None
    metrics: Dict[str, Set[str]] = {}
    for raw in lines:
        line = raw.strip()
        if not in_metrics:
            if line.startswith("metrics:"):
                in_metrics = True
            continue
        # Expect entries like:
        # - name: http_requests_total
        #   type: counter
        #   labels: [method, route, status]
        if line.startswith("- "):
            # start of a new item; may contain name inline
            m = re.search(r"\bname:\s*([^\s]+)", line)
            if m:
                current_name = m.group(1)
                metrics[current_name] = set()
            else:
                current_name = None
            continue
        if current_name is None:
            # try to see if name appears in following lines (nested style)
            if line.startswith("name:"):
                parts = line.split("name:", 1)
                if len(parts) == 2:
                    nm = parts[1].strip()
                    current_name = nm
                    metrics[current_name] = set()
            continue
        # we have a current metric; look for labels
        if line.startswith("labels:"):
            # labels: [a, b, c]
            parts = line.split("labels:", 1)
            if len(parts) == 2:
                list_part = parts[1].strip()
                # Expect brackets
                if list_part.startswith("[") and list_part.endswith("]"):
                    inner = list_part[1:-1].strip()
                    if inner == "":
                        labels = []
                    else:
                        labels = [lbl.strip() for lbl in inner.split(",")]
                    metrics[current_name] = set(labels)
                else:
                    # Unexpected format; try to parse comma-separated even without brackets
                    raw_list = list_part
                    raw_list = raw_list.strip()
                    if raw_list:
                        labels = [lbl.strip() for lbl in raw_list.split(",")]
                        metrics[current_name] = set(labels)
                    else:
                        metrics[current_name] = set()
    # Basic sanity
    if not metrics:
        return None
    return metrics


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    """
    Compute expected summary fields from the given inputs and threshold 3.
    Returns a dict with keys matching summary.json content requirements.
    """
    catalog_path = workspace / "input" / "metrics_catalog.yaml"
    scan_path = workspace / "input" / "instrumentation_scan.jsonl"
    runtime_path = workspace / "input" / "runtime_samples.jsonl"

    catalog = _parse_catalog_yaml(catalog_path)
    scan_items = _load_jsonl(scan_path)
    runtime_items = _load_jsonl(runtime_path)

    if catalog is None or scan_items is None or runtime_items is None:
        return None

    # Build scan map: metric_name -> set(labels)
    scan_map: Dict[str, Set[str]] = {}
    for obj in scan_items:
        try:
            name = obj["metric_name"]
            labels = obj.get("labels", [])
            scan_map[name] = set(labels)
        except Exception:
            return None

    # Build runtime metrics sets and label combinations
    runtime_names: Set[str] = set()
    runtime_label_sets: Dict[str, Set[Tuple[Tuple[str, str], ...]]] = {}
    for obj in runtime_items:
        try:
            name = obj["metric_name"]
            runtime_names.add(name)
            labels_map = obj.get("labels", {})
            # Normalize combination as a sorted tuple of (k,v)
            combo = tuple(sorted((str(k), str(v)) for k, v in labels_map.items()))
            runtime_label_sets.setdefault(name, set()).add(combo)
        except Exception:
            return None

    catalog_names = set(catalog.keys())
    scan_names = set(scan_map.keys())

    missing_in_scan = sorted(list(catalog_names - scan_names))
    undocumented_in_scan = sorted(list(scan_names - catalog_names))
    runtime_only = sorted(list(runtime_names - (catalog_names | scan_names)))

    # Label mismatches: metrics present in both with different label sets
    label_mismatches = []
    for name in sorted(list(catalog_names & scan_names)):
        if catalog.get(name, set()) != scan_map.get(name, set()):
            label_mismatches.append({
                "metric": name,
                "catalog_labels": sorted(list(catalog.get(name, set()))),
                "scan_labels": sorted(list(scan_map.get(name, set()))),
            })

    # Label cardinality for metrics observed in runtime
    threshold = 3
    label_cardinality = []
    for name in sorted(runtime_label_sets.keys()):
        unique_sets_count = len(runtime_label_sets[name])
        label_cardinality.append({
            "metric": name,
            "unique_label_sets": unique_sets_count,
            "exceeds_threshold": bool(unique_sets_count > threshold),
        })

    expected = {
        "totals": {
            "catalog": len(catalog_names),
            "scan": len(scan_names),
            "runtime_unique": len(runtime_names),
        },
        "missing_in_scan": missing_in_scan,
        "undocumented_in_scan": undocumented_in_scan,
        "runtime_only": runtime_only,
        "label_mismatches": label_mismatches,
        "label_cardinality": label_cardinality,
        "threshold": threshold,
    }
    return expected


def _is_sorted_strings(arr: List[str]) -> bool:
    return arr == sorted(arr)


def _is_sorted_by_metric(arr: List[Dict[str, Any]]) -> bool:
    try:
        metrics = [d["metric"] for d in arr]
        return metrics == sorted(metrics)
    except Exception:
        return False


def _contains_term_and_number_in_same_line(text: str, term: str, number: int) -> bool:
    for line in text.splitlines():
        if term.lower() in line.lower() and str(number) in line:
            return True
    return False


def _line_contains_any(line: str, keywords: List[str]) -> bool:
    low = line.lower()
    return any(k.lower() in low for k in keywords)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_under_scripts_present": 0.0,
        "summary_json_present_and_valid_json": 0.0,
        "summary_totals_correct": 0.0,
        "summary_missing_in_scan_correct_sorted": 0.0,
        "summary_undocumented_in_scan_correct_sorted": 0.0,
        "summary_runtime_only_correct_sorted": 0.0,
        "summary_label_mismatches_correct_sorted": 0.0,
        "summary_label_cardinality_correct_sorted": 0.0,
        "summary_threshold_correct": 0.0,
        "report_totals_and_threshold_present": 0.0,
        "report_categories_listed": 0.0,
        "report_label_mismatch_described_with_action": 0.0,
        "report_exceeds_threshold_highlighted": 0.0,
        "report_missing_metric_action_proposed": 0.0,
        "status_email_subject_and_recipient_present": 0.0,
        "status_email_counts_and_threshold_present": 0.0,
        "status_email_action_items_reference_metrics": 0.0,
        "status_email_points_to_report_path": 0.0,
        "run_log_contains_required_command_and_args": 0.0,
    }

    # Check for script under scripts/
    scripts_dir = workspace / "scripts"
    if scripts_dir.exists() and scripts_dir.is_dir():
        # At least one file (not directory) under scripts
        has_file = any(p.is_file() for p in scripts_dir.iterdir())
        if has_file:
            scores["script_under_scripts_present"] = 1.0

    # Compute expected from inputs
    expected = _compute_expected(workspace)

    # Load summary.json
    out_dir = workspace / "output" / "metrics_audit"
    summary_path = out_dir / "summary.json"
    summary = _load_json(summary_path) if summary_path.exists() else None
    if summary is not None and isinstance(summary, dict):
        scores["summary_json_present_and_valid_json"] = 1.0

    # Validate summary against expected
    if expected is not None and summary is not None and isinstance(summary, dict):
        # Totals
        try:
            totals = summary.get("totals", {})
            if (
                isinstance(totals, dict)
                and totals.get("catalog") == expected["totals"]["catalog"]
                and totals.get("scan") == expected["totals"]["scan"]
                and totals.get("runtime_unique") == expected["totals"]["runtime_unique"]
            ):
                scores["summary_totals_correct"] = 1.0
        except Exception:
            pass

        # Threshold
        try:
            if summary.get("threshold") == expected["threshold"]:
                scores["summary_threshold_correct"] = 1.0
        except Exception:
            pass

        # missing_in_scan
        try:
            mis = summary.get("missing_in_scan", [])
            if (
                isinstance(mis, list)
                and mis == expected["missing_in_scan"]
                and _is_sorted_strings(mis)
            ):
                scores["summary_missing_in_scan_correct_sorted"] = 1.0
        except Exception:
            pass

        # undocumented_in_scan
        try:
            uis = summary.get("undocumented_in_scan", [])
            if (
                isinstance(uis, list)
                and uis == expected["undocumented_in_scan"]
                and _is_sorted_strings(uis)
            ):
                scores["summary_undocumented_in_scan_correct_sorted"] = 1.0
        except Exception:
            pass

        # runtime_only
        try:
            ro = summary.get("runtime_only", [])
            if (
                isinstance(ro, list)
                and ro == expected["runtime_only"]
                and _is_sorted_strings(ro)
            ):
                scores["summary_runtime_only_correct_sorted"] = 1.0
        except Exception:
            pass

        # label_mismatches
        try:
            lm = summary.get("label_mismatches", [])
            ok = False
            if isinstance(lm, list) and _is_sorted_by_metric(lm) and isinstance(expected["label_mismatches"], list):
                # Compare as sets ignoring label order
                def norm(items):
                    return [{"metric": d["metric"],
                             "catalog_labels": set(d.get("catalog_labels", [])),
                             "scan_labels": set(d.get("scan_labels", []))}
                            for d in items]
                lm_norm = norm(lm)
                exp_norm = norm(expected["label_mismatches"])
                # Ensure same metrics and corresponding labels
                if len(lm_norm) == len(exp_norm):
                    ok = True
                    for d1, d2 in zip(sorted(lm_norm, key=lambda x: x["metric"]),
                                      sorted(exp_norm, key=lambda x: x["metric"])):
                        if d1["metric"] != d2["metric"] or d1["catalog_labels"] != d2["catalog_labels"] or d1["scan_labels"] != d2["scan_labels"]:
                            ok = False
                            break
            if ok:
                scores["summary_label_mismatches_correct_sorted"] = 1.0
        except Exception:
            pass

        # label_cardinality
        try:
            lc = summary.get("label_cardinality", [])
            ok = False
            if isinstance(lc, list) and _is_sorted_by_metric(lc) and isinstance(expected["label_cardinality"], list):
                # Map by metric for comparison
                lc_map = {}
                valid_struct = True
                for d in lc:
                    if not isinstance(d, dict):
                        valid_struct = False
                        break
                    m = d.get("metric")
                    u = d.get("unique_label_sets")
                    e = d.get("exceeds_threshold")
                    if not isinstance(m, str) or not isinstance(u, int) or not isinstance(e, bool):
                        valid_struct = False
                        break
                    lc_map[m] = (u, e)
                if valid_struct:
                    exp_map = {d["metric"]: (d["unique_label_sets"], d["exceeds_threshold"]) for d in expected["label_cardinality"]}
                    # exact match of keys and values
                    if lc_map == exp_map:
                        ok = True
            if ok:
                scores["summary_label_cardinality_correct_sorted"] = 1.0
        except Exception:
            pass

    # report.md checks
    report_path = out_dir / "report.md"
    report_text = _read_text(report_path) if report_path.exists() else None
    if report_text is not None and expected is not None:
        # Totals and threshold present
        conds = [
            _contains_term_and_number_in_same_line(report_text, "catalog", expected["totals"]["catalog"]),
            _contains_term_and_number_in_same_line(report_text, "scan", expected["totals"]["scan"]),
            (_contains_term_and_number_in_same_line(report_text, "runtime unique", expected["totals"]["runtime_unique"])
             or _contains_term_and_number_in_same_line(report_text, "runtime", expected["totals"]["runtime_unique"])),
            _contains_term_and_number_in_same_line(report_text, "threshold", expected["threshold"]),
        ]
        if all(conds):
            scores["report_totals_and_threshold_present"] = 1.0

        # Categories listed
        cat_ok = True
        for name in expected["missing_in_scan"]:
            if name not in report_text:
                cat_ok = False
                break
        if cat_ok:
            for name in expected["undocumented_in_scan"]:
                if name not in report_text:
                    cat_ok = False
                    break
        if cat_ok:
            for name in expected["runtime_only"]:
                if name not in report_text:
                    cat_ok = False
                    break
        if cat_ok:
            scores["report_categories_listed"] = 1.0

        # Label mismatch described with action
        lm_ok = False
        if expected["label_mismatches"]:
            # For each mismatch, ensure metric name appears, labels mentioned, and action suggested
            needed_verbs = ["rename", "update", "align", "fix", "standardize", "change", "correct"]
            for lm in expected["label_mismatches"]:
                metric = lm["metric"]
                labels_a = list(lm["catalog_labels"])
                labels_b = list(lm["scan_labels"])
                # Check a line containing metric and one of the verbs
                lines = report_text.splitlines()
                line_with_metric_and_action = any((metric in ln and _line_contains_any(ln, needed_verbs)) for ln in lines)
                labels_mentioned = (any(lbl in report_text for lbl in labels_a) and any(lbl in report_text for lbl in labels_b))
                if line_with_metric_and_action and labels_mentioned:
                    lm_ok = True
                else:
                    lm_ok = False
                    break
        else:
            # No mismatches expected, consider satisfied if none described
            lm_ok = True
        if lm_ok:
            scores["report_label_mismatch_described_with_action"] = 1.0

        # Exceeds threshold highlighted
        ex_ok = True
        exceeders = [d["metric"] for d in expected["label_cardinality"] if d["exceeds_threshold"]]
        if exceeders:
            lines = report_text.splitlines()
            for met in exceeders:
                if not any((met in ln and (_line_contains_any(ln, ["exceed", "exceeds", "above", "overflow", "hotspot", "threshold"]))) for ln in lines):
                    ex_ok = False
                    break
        if ex_ok:
            scores["report_exceeds_threshold_highlighted"] = 1.0

        # Missing metric action proposed
        mm_ok = True
        action_verbs = ["instrument", "add", "implement", "emit", "rename", "document", "track", "create"]
        for met in expected["missing_in_scan"]:
            if not any((met in ln and _line_contains_any(ln, action_verbs)) for ln in report_text.splitlines()):
                mm_ok = False
                break
        if mm_ok:
            scores["report_missing_metric_action_proposed"] = 1.0

    # status_email.txt checks
    email_path = out_dir / "status_email.txt"
    email_text = _read_text(email_path) if email_path.exists() else None
    if email_text is not None and expected is not None:
        # Subject and recipient
        subj_ok = False
        recip_ok = "metrics-team@example.com" in email_text
        for line in email_text.splitlines():
            if line.lower().startswith("subject:") and "metrics audit results (local run)".lower() in line.lower():
                subj_ok = True
                break
        if subj_ok and recip_ok:
            scores["status_email_subject_and_recipient_present"] = 1.0

        # Counts and threshold
        cnt_ok = (
            _contains_term_and_number_in_same_line(email_text, "catalog", expected["totals"]["catalog"])
            and _contains_term_and_number_in_same_line(email_text, "scan", expected["totals"]["scan"])
            and (_contains_term_and_number_in_same_line(email_text, "runtime unique", expected["totals"]["runtime_unique"])
                 or _contains_term_and_number_in_same_line(email_text, "runtime", expected["totals"]["runtime_unique"]))
            and _contains_term_and_number_in_same_line(email_text, "threshold", expected["threshold"])
        )
        if cnt_ok:
            scores["status_email_counts_and_threshold_present"] = 1.0

        # Action items referencing metrics (bulleted)
        bullets = [ln for ln in email_text.splitlines() if ln.strip().startswith(("-", "*", "•"))]
        act_ok = False
        if bullets:
            # Require at least action items mentioning each of these metrics: missing metric and mismatch metric
            needed = set()
            for met in expected["missing_in_scan"]:
                needed.add(met)
            for lm in expected["label_mismatches"]:
                needed.add(lm["metric"])
            found = set()
            for b in bullets:
                for met in list(needed):
                    if met in b:
                        found.add(met)
            if needed.issubset(found):
                act_ok = True
        if act_ok:
            scores["status_email_action_items_reference_metrics"] = 1.0

        # Points to report path
        if "output/metrics_audit/report.md" in email_text:
            scores["status_email_points_to_report_path"] = 1.0

    # run.log checks
    runlog_path = out_dir / "run.log"
    runlog_text = _read_text(runlog_path) if runlog_path.exists() else None
    if runlog_text is not None:
        # Look for the first non-empty line (the command) and ensure required args present
        first_line = ""
        for ln in runlog_text.splitlines():
            if ln.strip():
                first_line = ln.strip()
                break
        required_subs = [
            "--catalog input/metrics_catalog.yaml",
            "--scan input/instrumentation_scan.jsonl",
            "--runtime input/runtime_samples.jsonl",
            "--threshold 3",
            "--outdir output/metrics_audit",
        ]
        if first_line and all(s in first_line for s in required_subs):
            scores["run_log_contains_required_command_and_args"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) >= 2 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()