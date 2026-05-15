import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime, timedelta
import math
import sys


def _read_text_safe(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


class MetricsTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_metrics_table = False
        self.current_table_id = None
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_row = []
        self.rows = []
        self.capture_text = False
        self._data_buffer = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self.current_table_id = attrs_dict.get("id")
            self.in_metrics_table = (self.current_table_id == "metrics")
        if self.in_metrics_table and tag == "tbody":
            self.in_tbody = True
        if self.in_metrics_table and self.in_tbody and tag == "tr":
            self.in_tr = True
            self.current_row = []
        if self.in_metrics_table and self.in_tbody and self.in_tr and tag in ("td", "th"):
            self.in_td = True
            self.capture_text = True
            self._data_buffer = []

    def handle_endtag(self, tag):
        if self.in_metrics_table and self.in_tbody and self.in_tr and tag in ("td", "th"):
            if self.capture_text:
                text = "".join(self._data_buffer).strip()
                self.current_row.append(text)
                self._data_buffer = []
            self.in_td = False
            self.capture_text = False
        if self.in_metrics_table and self.in_tbody and tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_tr = False
        if self.in_metrics_table and tag == "tbody":
            self.in_tbody = False
        if tag == "table":
            self.in_metrics_table = False
            self.current_table_id = None

    def handle_data(self, data):
        if self.capture_text:
            self._data_buffer.append(data)


def _parse_html_metadata(path: Path):
    text = _read_text_safe(path)
    if text is None:
        return None
    exp_match = re.search(r"Experiment:\s*([A-Za-z0-9\-_]+)", text)
    experiment_id = exp_match.group(1) if exp_match else None
    groups_match = re.search(r"Groups:\s*intervention\s*=\s*([A-Za-z]+)\s*,\s*control\s*=\s*([A-Za-z]+)", text, re.IGNORECASE)
    intervention_group = groups_match.group(1) if groups_match else None
    control_group = groups_match.group(2) if groups_match else None
    ratio_match = re.search(r"Randomization ratio:\s*([0-9]+\s*:\s*[0-9]+)", text, re.IGNORECASE)
    ratio = ratio_match.group(1).replace(" ", "") if ratio_match else None
    expw_match = re.search(r"Exposure window:\s*up to\s*([0-9]+)\s*days", text, re.IGNORECASE)
    exposure_days = int(expw_match.group(1)) if expw_match else None
    parser = MetricsTableParser()
    try:
        parser.feed(text)
        metrics_rows = []
        for row in parser.rows:
            if len(row) >= 2:
                metrics_rows.append([row[0].strip(), row[1].strip()])
    except Exception:
        metrics_rows = []
    return {
        "experiment_id": experiment_id,
        "intervention_group": intervention_group,
        "control_group": control_group,
        "randomization_ratio": ratio,
        "exposure_days": exposure_days,
        "metrics_rows": metrics_rows,
    }


def _float_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    try:
        return abs(a - b) <= tol
    except Exception:
        return False


def _safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def _compute_group_summary(part_rows, out_rows, exposure_days):
    users = {}
    group_counts = {}
    for r in part_rows:
        uid = r.get("user_id")
        grp = r.get("group")
        enroll_date = _parse_date(r.get("enroll_date", ""))
        if uid is None or grp is None or enroll_date is None:
            continue
        users[uid] = {"group": grp, "enroll_date": enroll_date}
        group_counts[grp] = group_counts.get(grp, 0) + 1
    in_window_outcomes = []
    for r in out_rows:
        uid = r.get("user_id")
        if uid not in users:
            continue
        event_date = _parse_date(r.get("event_date", ""))
        if event_date is None:
            continue
        enroll_date = users[uid]["enroll_date"]
        if exposure_days is None:
            within = True
        else:
            within = event_date <= (enroll_date + timedelta(days=exposure_days))
        if within and event_date >= enroll_date:
            grp = users[uid]["group"]
            conv = _safe_float(r.get("converted"))
            sess = _safe_float(r.get("sessions"))
            if conv is None or sess is None:
                continue
            in_window_outcomes.append({"group": grp, "converted": conv, "sessions": sess, "user_id": uid})
    summary = {}
    users_with_outcome_by_group = {}
    for rec in in_window_outcomes:
        g = rec["group"]
        users_with_outcome_by_group.setdefault(g, set()).add(rec["user_id"])
    for grp, n_users in group_counts.items():
        recs = [r for r in in_window_outcomes if r["group"] == grp]
        n_with_outcome = len(users_with_outcome_by_group.get(grp, set()))
        conv_rate = sum(r["converted"] for r in recs) / len(recs) if len(recs) > 0 else 0.0
        avg_sessions = sum(r["sessions"] for r in recs) / len(recs) if len(recs) > 0 else 0.0
        summary[grp] = {
            "group": grp,
            "n_users": n_users,
            "n_with_outcome": n_with_outcome,
            "conversion_rate": conv_rate,
            "avg_sessions": avg_sessions,
        }
    return summary


def _two_proportion_z_test(x1, n1, x2, n2):
    p1 = x1 / n1 if n1 > 0 else 0.0
    p2 = x2 / n2 if n2 > 0 else 0.0
    p_pool = (x1 + x2) / (n1 + n2) if (n1 + n2) > 0 else 0.0
    se_pool = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) if n1 > 0 and n2 > 0 else float('inf')
    diff = p1 - p2
    if se_pool == 0 or math.isinf(se_pool):
        z = 0.0
        p_val = 1.0
    else:
        z = diff / se_pool
        p_val = 2 * 0.5 * math.erfc(abs(z) / math.sqrt(2))
    se_unpooled = math.sqrt((p1 * (1 - p1)) / n1 + (p2 * (1 - p2)) / n2) if n1 > 0 and n2 > 0 else float('inf')
    z_crit = 1.96
    ci_lower = diff - z_crit * se_unpooled if not math.isinf(se_unpooled) else float('nan')
    ci_upper = diff + z_crit * se_unpooled if not math.isinf(se_unpooled) else float('nan')
    return {
        "p1": p1, "p2": p2, "diff": diff,
        "ci_lower": ci_lower, "ci_upper": ci_upper,
        "p_value": p_val
    }


def _find_validation_check(checks, keywords):
    for c in checks:
        name = str(c.get("name", "")).lower()
        if all(k in name for k in keywords):
            return c
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metric_definitions_file_structure": 0.0,
        "metric_definitions_rowcount_match": 0.0,
        "group_summary_file_structure": 0.0,
        "group_summary_values_correct": 0.0,
        "effect_size_file_structure": 0.0,
        "effect_size_values_correct": 0.0,
        "validations_file_structure": 0.0,
        "validations_checks_present_and_passed": 0.0,
        "report_exists_and_sections": 0.0,
        "report_command_documented": 0.0,
        "report_results_and_significance": 0.0,
        "outputs_paths_exist": 0.0,
    }

    participants_csv = workspace / "input" / "participants.csv"
    outcomes_csv = workspace / "input" / "outcomes.csv"
    metadata_html = workspace / "input" / "experiment_metadata.html"

    out_metric_csv = workspace / "output" / "extracted" / "metric_definitions.csv"
    out_group_summary = workspace / "output" / "derived" / "group_summary.csv"
    out_effect_json = workspace / "output" / "derived" / "effect_size.json"
    out_validations_json = workspace / "output" / "validation" / "validation_results.json"
    out_report_md = workspace / "output" / "report" / "ab_test_readout.md"

    html_meta = _parse_html_metadata(metadata_html) if metadata_html.exists() else None
    html_metrics_rows = html_meta["metrics_rows"] if html_meta else []

    header, rows = _read_csv_safe(out_metric_csv) if out_metric_csv.exists() else (None, None)
    if header is not None and rows is not None:
        expected_header = ["metric", "definition"]
        if [h.strip() for h in header] == expected_header:
            scores["metric_definitions_file_structure"] = 1.0
        if html_metrics_rows is not None:
            html_row_count = len(html_metrics_rows)
            csv_row_count = len(rows)
            if html_row_count == csv_row_count:
                scores["metric_definitions_rowcount_match"] = 1.0
        else:
            scores["metric_definitions_rowcount_match"] = 0.0
    else:
        scores["metric_definitions_file_structure"] = 0.0
        scores["metric_definitions_rowcount_match"] = 0.0

    p_header, p_rows = _read_csv_safe(participants_csv) if participants_csv.exists() else (None, None)
    o_header, o_rows = _read_csv_safe(outcomes_csv) if outcomes_csv.exists() else (None, None)
    exposure_days = html_meta["exposure_days"] if html_meta else None
    expected_summary = None
    if p_rows is not None and o_rows is not None:
        expected_summary = _compute_group_summary(p_rows, o_rows, exposure_days)

    gs_header, gs_rows = _read_csv_safe(out_group_summary) if out_group_summary.exists() else (None, None)
    if gs_header is not None and gs_rows is not None:
        expected_gs_header = ["group", "n_users", "n_with_outcome", "conversion_rate", "avg_sessions"]
        if [h.strip() for h in gs_header] == expected_gs_header:
            scores["group_summary_file_structure"] = 1.0
        if expected_summary is not None and len(expected_summary) > 0:
            observed = {}
            for r in gs_rows:
                grp = r.get("group")
                if grp is None:
                    continue
                try:
                    n_users = int(str(r.get("n_users", "")).strip())
                    n_with = int(str(r.get("n_with_outcome", "")).strip())
                    conv = float(str(r.get("conversion_rate", "")).strip())
                    avg_sess = float(str(r.get("avg_sessions", "")).strip())
                    observed[grp] = {
                        "n_users": n_users,
                        "n_with_outcome": n_with,
                        "conversion_rate": conv,
                        "avg_sessions": avg_sess,
                    }
                except Exception:
                    observed[grp] = None
            ok = True
            for grp, exp in expected_summary.items():
                obs = observed.get(grp)
                if obs is None:
                    ok = False
                    break
                if obs.get("n_users") != exp.get("n_users"):
                    ok = False
                    break
                if obs.get("n_with_outcome") != exp.get("n_with_outcome"):
                    ok = False
                    break
                if not _float_equal(obs.get("conversion_rate", 0.0), exp.get("conversion_rate", 0.0), tol=1e-2):
                    ok = False
                    break
                if not _float_equal(obs.get("avg_sessions", 0.0), exp.get("avg_sessions", 0.0), tol=1e-2):
                    ok = False
                    break
            if ok and len(observed) == len(expected_summary):
                scores["group_summary_values_correct"] = 1.0
    else:
        scores["group_summary_file_structure"] = 0.0
        scores["group_summary_values_correct"] = 0.0

    eff = _load_json_safe(out_effect_json) if out_effect_json.exists() else None
    if isinstance(eff, dict):
        required_fields = ["group_A_rate", "group_B_rate", "abs_diff", "ci_lower", "ci_upper", "p_value", "test"]
        if all(k in eff for k in required_fields):
            scores["effect_size_file_structure"] = 1.0
        if expected_summary is not None and "A" in expected_summary and "B" in expected_summary:
            p1 = expected_summary["A"]["conversion_rate"]
            p2 = expected_summary["B"]["conversion_rate"]
            x1 = int(round(p1 * expected_summary["A"]["n_with_outcome"])) if expected_summary["A"]["n_with_outcome"] > 0 else 0
            x2 = int(round(p2 * expected_summary["B"]["n_with_outcome"])) if expected_summary["B"]["n_with_outcome"] > 0 else 0
            n1 = expected_summary["A"]["n_with_outcome"]
            n2 = expected_summary["B"]["n_with_outcome"]
            test_res = _two_proportion_z_test(x1, n1, x2, n2)
            ok_vals = True
            try:
                if not _float_equal(float(eff.get("group_A_rate")), p1, tol=1e-2):
                    ok_vals = False
                if not _float_equal(float(eff.get("group_B_rate")), p2, tol=1e-2):
                    ok_vals = False
                if not _float_equal(float(eff.get("abs_diff")), p1 - p2, tol=1e-2):
                    ok_vals = False
                if not _float_equal(float(eff.get("ci_lower")), test_res["ci_lower"], tol=2e-2):
                    ok_vals = False
                if not _float_equal(float(eff.get("ci_upper")), test_res["ci_upper"], tol=2e-2):
                    ok_vals = False
                if not _float_equal(float(eff.get("p_value")), test_res["p_value"], tol=2e-2):
                    ok_vals = False
            except Exception:
                ok_vals = False
            test_label = str(eff.get("test", "")).lower()
            if not ("two" in test_label and "proportion" in test_label and "z" in test_label):
                ok_vals = False
            if ok_vals:
                scores["effect_size_values_correct"] = 1.0
    else:
        scores["effect_size_file_structure"] = 0.0
        scores["effect_size_values_correct"] = 0.0

    validations = _load_json_safe(out_validations_json) if out_validations_json.exists() else None
    if isinstance(validations, list):
        struct_ok = True
        for item in validations:
            if not isinstance(item, dict) or "name" not in item or "passed" not in item or "details" not in item:
                struct_ok = False
                break
            if not isinstance(item.get("passed"), bool):
                struct_ok = False
                break
        if struct_ok:
            scores["validations_file_structure"] = 1.0

        checks_ok = True
        orphans_check = _find_validation_check(validations, ["outcomes", "participants"])
        if not orphans_check or not isinstance(orphans_check.get("passed"), bool) or orphans_check.get("passed") is not True:
            checks_ok = False

        dates_check = _find_validation_check(validations, ["event_date", "enroll"])
        if not dates_check or not isinstance(dates_check.get("passed"), bool) or dates_check.get("passed") is not True:
            checks_ok = False

        ratio_check = _find_validation_check(validations, ["randomization", "ratio"])
        if not ratio_check or ratio_check.get("passed") is not True:
            checks_ok = False
        else:
            det = ratio_check.get("details")
            det_text = json.dumps(det) if not isinstance(det, str) else det
            if not (("A" in det_text or "a" in det_text) and ("B" in det_text or "b" in det_text)):
                checks_ok = False

        metrics_row_check = _find_validation_check(validations, ["metric_definitions", "row", "count"])
        if not metrics_row_check or metrics_row_check.get("passed") is not True:
            checks_ok = False

        if checks_ok:
            scores["validations_checks_present_and_passed"] = 1.0

    else:
        scores["validations_file_structure"] = 0.0
        scores["validations_checks_present_and_passed"] = 0.0

    report_text = _read_text_safe(out_report_md) if out_report_md.exists() else None
    if isinstance(report_text, str):
        text_lower = report_text.lower()
        sections_ok = all(s in text_lower for s in ["design snapshot", "data validation", "results", "next steps"])
        if sections_ok:
            scores["report_exists_and_sections"] = 1.0

        lines = [ln.strip() for ln in report_text.splitlines()]
        non_empty = [ln for ln in lines if ln]
        cmd_ok = False
        for i, ln in enumerate(non_empty[:10]):
            lnl = ln.lower()
            if "python" in lnl and "input/participants.csv" in lnl and "input/outcomes.csv" in lnl and "input/experiment_metadata.html" in lnl and "output" in lnl:
                if ".py" in lnl:
                    cmd_ok = True
                    break
        if cmd_ok:
            scores["report_command_documented"] = 1.0

        results_ok = False
        if ("p-value" in report_text or "p value" in report_text or "p=" in report_text.lower()) and ("0.05" in report_text or "alpha=0.05" in text_lower or "α=0.05" in report_text):
            if ("group" in text_lower and "a" in text_lower and "b" in text_lower) or ("A" in report_text and "B" in report_text):
                if "significant" in text_lower:
                    results_ok = True
        if results_ok:
            scores["report_results_and_significance"] = 1.0
    else:
        scores["report_exists_and_sections"] = 0.0
        scores["report_command_documented"] = 0.0
        scores["report_results_and_significance"] = 0.0

    outputs_exist = all([
        out_metric_csv.exists(),
        out_group_summary.exists(),
        out_effect_json.exists(),
        out_validations_json.exists(),
        out_report_md.exists(),
    ])
    if outputs_exist:
        scores["outputs_paths_exist"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()