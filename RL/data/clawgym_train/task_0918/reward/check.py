import csv
import json
import re
import sys
import subprocess
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Tuple, Optional


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


class LabsHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_labs_table = False
        self.current_tag = None
        self.in_header = False
        self.in_body = False
        self.current_row: List[str] = []
        self.headers: List[str] = []
        self.rows: List[Dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table" and attrs_dict.get("id") == "labs":
            self.in_labs_table = True
        elif self.in_labs_table and tag == "thead":
            self.in_header = True
        elif self.in_labs_table and tag == "tbody":
            self.in_body = True
        elif self.in_labs_table and tag == "tr":
            self.current_row = []
        elif self.in_labs_table and tag in ("th", "td"):
            self.current_tag = tag

    def handle_endtag(self, tag):
        if tag == "table" and self.in_labs_table:
            self.in_labs_table = False
        elif self.in_labs_table and tag == "thead":
            self.in_header = False
        elif self.in_labs_table and tag == "tbody":
            self.in_body = False
        elif self.in_labs_table and tag in ("th", "td"):
            self.current_tag = None
        elif self.in_labs_table and tag == "tr":
            if self.in_header and self.current_row:
                self.headers = [c.strip() for c in self.current_row]
            elif self.in_body and self.current_row:
                if self.headers and len(self.current_row) == len(self.headers):
                    row = {self.headers[i]: self.current_row[i].strip() for i in range(len(self.headers))}
                    self.rows.append(row)
            self.current_row = []

    def handle_data(self, data):
        if self.in_labs_table and self.current_tag in ("th", "td"):
            self.current_row.append(data.strip())


def _parse_labs_html(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    try:
        parser = LabsHTMLParser()
        parser.feed(text)
        # Ensure we have headers and rows
        if not parser.headers:
            return None
        return parser.rows
    except Exception:
        return None


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _compute_homa(glucose_str: str, insulin_str: str) -> Optional[float]:
    g = _to_float(glucose_str)
    i = _to_float(insulin_str)
    if g is None or i is None:
        return None
    try:
        homa = (g * i) / 405.0
        return round(homa + 1e-8, 1)
    except Exception:
        return None


def _load_messages_jsonl(path: Path) -> Optional[List[Dict]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None
    result = []
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            result.append(obj)
        except Exception:
            return None
    return result


def _parse_output_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            hdr = reader.fieldnames
            if hdr is None:
                return None
            rows = [dict(row) for row in reader]
            return hdr, rows
    except Exception:
        return None


def _count_words(text: str) -> int:
    # Count words as sequences of alphanumeric/underscore/apostrophe
    return len(re.findall(r"\b[\w']+\b", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "run_exit_zero": 0.0,
        "stdout_one_line": 0.0,
        "stdout_summary_format": 0.0,
        "stdout_summary_counts_correct": 0.0,
        "homa_csv_exists": 0.0,
        "homa_csv_header_correct": 0.0,
        "homa_csv_content_correct": 0.0,
        "mismatches_csv_exists": 0.0,
        "mismatches_csv_header_correct": 0.0,
        "mismatches_csv_content_correct": 0.0,
        "cohort_summary_csv_exists": 0.0,
        "cohort_summary_metrics_correct": 0.0,
        "messages_jsonl_exists": 0.0,
        "messages_count_matches": 0.0,
        "messages_fields_valid": 0.0,
        "messages_content_constraints": 0.0,
    }

    script_path = workspace / "pcos_audit.py"
    if script_path.exists():
        scores["script_present"] = 1.0

    # Load inputs for expected computation
    patients_csv_path = workspace / "input" / "patients.csv"
    labs_html_path = workspace / "input" / "labs.html"
    msgs_jsonl_path = workspace / "input" / "messages.jsonl"

    patients_rows = _read_csv_dicts(patients_csv_path) if patients_csv_path.exists() else None
    labs_rows = _parse_labs_html(labs_html_path) if labs_html_path.exists() else None
    msgs_rows = _load_messages_jsonl(msgs_jsonl_path) if msgs_jsonl_path.exists() else None

    # Build expected homa and categories from CSV values
    expected_homa: Dict[str, Tuple[Optional[float], Optional[str]]] = {}
    expected_n_patients = 0
    expected_count_homa_high = 0
    bmi_values: List[float] = []
    meds_by_patient: Dict[str, str] = {}
    med_counts: Dict[str, int] = {}
    pid_set_from_csv: set = set()

    if patients_rows is not None:
        for row in patients_rows:
            pid = row.get("patient_id")
            if not pid:
                continue
            pid_set_from_csv.add(pid)
            expected_n_patients += 1
            # HOMA from CSV
            homa_val = _compute_homa(row.get("fasting_glucose_mg_dl", ""), row.get("fasting_insulin_uU_ml", ""))
            category = None
            if homa_val is not None:
                category = "elevated" if homa_val > 2.0 else "within target"
                if category == "elevated":
                    expected_count_homa_high += 1
            expected_homa[pid] = (homa_val, category)
            # BMI
            b = _to_float(row.get("BMI", ""))
            if b is not None:
                bmi_values.append(b)
            # Meds for messages and summary
            meds_exact = row.get("meds_current", "") or ""
            meds_by_patient[pid] = meds_exact
            meds_list = [m.strip() for m in meds_exact.split(";") if m.strip()]
            for m in meds_list:
                key = m.lower()
                med_counts[key] = med_counts.get(key, 0) + 1

    # Expected mismatches
    required_fields = [
        "last_lab_date",
        "fasting_glucose_mg_dl",
        "fasting_insulin_uU_ml",
        "A1c_pct",
        "LDL_mg_dl",
        "HDL_mg_dl",
        "TG_mg_dl",
    ]
    expected_mismatches: List[Dict[str, str]] = []
    if patients_rows is not None and labs_rows is not None:
        labs_by_pid = {r.get("patient_id"): r for r in labs_rows if r.get("patient_id")}
        for prow in patients_rows:
            pid = prow.get("patient_id")
            if not pid:
                continue
            lrow = labs_by_pid.get(pid)
            if not lrow:
                # If missing in HTML, we cannot reliably define mismatches; skip as unspecified
                continue
            for field in required_fields:
                v_csv = (prow.get(field, "") if field in prow else "")
                v_html = (lrow.get(field, "") if field in lrow else "")
                # Compare as strings exactly
                if v_csv != v_html:
                    expected_mismatches.append({
                        "patient_id": pid,
                        "field": field,
                        "value_csv": v_csv,
                        "value_html": v_html,
                    })

    expected_mismatch_count = len(expected_mismatches)

    # Execute the user's script
    out_dir = workspace / "output"
    cmd = [
        sys.executable,
        str(script_path.name),
        "--patients",
        "input/patients.csv",
        "--labs",
        "input/labs.html",
        "--drafts",
        "input/messages.jsonl",
        "--out_dir",
        "output",
    ]
    run_completed = False
    stdout_text = ""
    if script_path.exists():
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            run_completed = True
            if proc.returncode == 0:
                scores["run_exit_zero"] = 1.0
            stdout_text = proc.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            run_completed = False
        except Exception:
            run_completed = False

    # Check stdout summary
    non_empty_lines = [ln for ln in stdout_text.splitlines() if ln.strip()]
    if len(non_empty_lines) == 1:
        scores["stdout_one_line"] = 1.0
    summary_line = non_empty_lines[0] if non_empty_lines else ""
    m = re.match(r"^Processed (\d+) patients; (\d+) HOMA-IR elevated; (\d+) mismatches found\.$", summary_line.strip())
    if m:
        scores["stdout_summary_format"] = 1.0
        try:
            n_pat = int(m.group(1))
            n_high = int(m.group(2))
            n_mis = int(m.group(3))
            if expected_n_patients and expected_homa:
                if n_pat == expected_n_patients and n_high == expected_count_homa_high and n_mis == expected_mismatch_count:
                    scores["stdout_summary_counts_correct"] = 1.0
        except Exception:
            pass

    # Validate homa_by_patient.csv
    homa_path = out_dir / "homa_by_patient.csv"
    if homa_path.exists():
        scores["homa_csv_exists"] = 1.0
        parsed = _parse_output_csv(homa_path)
        if parsed is not None:
            header, rows = parsed
            if header == ["patient_id", "homa_ir", "category"]:
                scores["homa_csv_header_correct"] = 1.0
            # Build a map from file
            try:
                file_map: Dict[str, Tuple[float, str]] = {}
                for r in rows:
                    pid = r.get("patient_id", "")
                    hstr = r.get("homa_ir", "")
                    cat = r.get("category", "")
                    if not pid or not hstr or not cat:
                        raise ValueError("missing fields in homa row")
                    hval = float(hstr)
                    # enforce one decimal in representation by reformatting
                    if f"{hval:.1f}" != hstr.strip():
                        # allow numeric but not exact one decimal formatting -> still acceptable? Requirement says rounded to 1 decimal.
                        # We'll require string to match rounding to 1 decimal.
                        raise ValueError("homa_ir not one decimal formatted")
                    if cat not in ("elevated", "within target"):
                        raise ValueError("invalid category")
                    file_map[pid] = (hval, cat)
                # Compare to expected
                ok = True
                if expected_homa:
                    # Ensure exactly same patient ids
                    if set(file_map.keys()) != set(expected_homa.keys()):
                        ok = False
                    else:
                        for pid, (exp_h, exp_cat) in expected_homa.items():
                            got = file_map.get(pid)
                            if exp_h is None or exp_cat is None or got is None:
                                ok = False
                                break
                            gh, gcat = got
                            if abs(gh - exp_h) > 1e-6 or gcat != exp_cat:
                                ok = False
                                break
                else:
                    ok = False
                if ok:
                    scores["homa_csv_content_correct"] = 1.0
            except Exception:
                pass

    # Validate lab_mismatches.csv
    mismatches_path = out_dir / "lab_mismatches.csv"
    if mismatches_path.exists():
        scores["mismatches_csv_exists"] = 1.0
        parsed = _parse_output_csv(mismatches_path)
        if parsed is not None:
            header, rows = parsed
            if header == ["patient_id", "field", "value_csv", "value_html"]:
                scores["mismatches_csv_header_correct"] = 1.0
            # Compare to expected mismatches exactly (order independent)
            try:
                file_rows = [
                    {
                        "patient_id": r.get("patient_id", ""),
                        "field": r.get("field", ""),
                        "value_csv": r.get("value_csv", ""),
                        "value_html": r.get("value_html", ""),
                    }
                    for r in rows
                ]
                # Sort both lists for deterministic comparison
                def keyf(d): return (d["patient_id"], d["field"], d["value_csv"], d["value_html"])
                file_sorted = sorted(file_rows, key=keyf)
                exp_sorted = sorted(expected_mismatches, key=keyf) if expected_mismatches is not None else []
                if expected_mismatches is not None and file_sorted == exp_sorted:
                    scores["mismatches_csv_content_correct"] = 1.0
            except Exception:
                pass

    # Validate cohort_summary.csv
    cohort_path = out_dir / "cohort_summary.csv"
    if cohort_path.exists():
        scores["cohort_summary_csv_exists"] = 1.0
        parsed = _parse_output_csv(cohort_path)
        if parsed is not None:
            header, rows = parsed
            req_header = ["metric", "value"]
            metrics_ok = False
            if header == req_header:
                # Compute expected metrics
                expected_metrics: Dict[str, str] = {}
                if expected_n_patients:
                    expected_metrics["n_patients"] = str(expected_n_patients)
                if bmi_values:
                    mean_bmi = round(sum(bmi_values) / len(bmi_values) + 1e-8, 1)
                    expected_metrics["mean_BMI"] = f"{mean_bmi:.1f}"
                    # BMI bins
                    lt_25 = sum(1 for b in bmi_values if b < 25.0)
                    b_25_29_9 = sum(1 for b in bmi_values if 25.0 <= b <= 29.9)
                    b_30_34_9 = sum(1 for b in bmi_values if 30.0 <= b <= 34.9)
                    ge_35 = sum(1 for b in bmi_values if b >= 35.0)
                    expected_metrics["bmi_lt_25"] = str(lt_25)
                    expected_metrics["bmi_25_29_9"] = str(b_25_29_9)
                    expected_metrics["bmi_30_34_9"] = str(b_30_34_9)
                    expected_metrics["bmi_ge_35"] = str(ge_35)
                expected_metrics["count_HOMA_IR_high (>2.0)"] = str(expected_count_homa_high)
                # Med counts: lowercase keys
                for med_name_lower, count in med_counts.items():
                    expected_metrics[f"med_{med_name_lower}"] = str(count)

                # Build dict from file rows
                file_metrics: Dict[str, str] = {}
                try:
                    for r in rows:
                        mname = r.get("metric", "")
                        val = r.get("value", "")
                        if mname:
                            file_metrics[mname] = val
                except Exception:
                    file_metrics = {}

                # All expected metrics must be present and equal
                all_present = True
                for k, v in expected_metrics.items():
                    if k not in file_metrics:
                        all_present = False
                        break
                    # For numeric values we can compare as strings directly
                    if str(file_metrics[k]).strip() != v:
                        all_present = False
                        break
                if all_present:
                    metrics_ok = True
            if metrics_ok:
                scores["cohort_summary_metrics_correct"] = 1.0

    # Validate messages_rewritten.jsonl
    msgs_out_path = out_dir / "messages_rewritten.jsonl"
    if msgs_out_path.exists():
        scores["messages_jsonl_exists"] = 1.0
        msgs_out = _load_messages_jsonl(msgs_out_path)
        if msgs_out is not None and msgs_rows is not None:
            # Count matches and patient id set matches
            in_ids = [m.get("patient_id") for m in msgs_rows if isinstance(m, dict)]
            out_ids = [m.get("patient_id") for m in msgs_out if isinstance(m, dict)]
            if len(in_ids) == len(out_ids) and set(in_ids) == set(out_ids):
                scores["messages_count_matches"] = 1.0
            # Fields valid
            fields_valid = True
            for m in msgs_out:
                if not isinstance(m, dict):
                    fields_valid = False
                    break
                if "patient_id" not in m or "rewritten_message" not in m:
                    fields_valid = False
                    break
                if not isinstance(m["rewritten_message"], str):
                    fields_valid = False
                    break
            if fields_valid:
                scores["messages_fields_valid"] = 1.0

            # Content constraints
            constraints_ok = True
            # Build maps for expectations
            expected_status: Dict[str, str] = {}
            expected_homa_str: Dict[str, str] = {}
            for pid, (hval, cat) in expected_homa.items():
                if hval is None or cat is None:
                    constraints_ok = False
                    break
                expected_homa_str[pid] = f"{hval:.1f}"
                expected_status[pid] = "elevated" if cat == "elevated" else "within target"
            if constraints_ok:
                for m in msgs_out:
                    pid = m.get("patient_id")
                    msg = (m.get("rewritten_message") or "").strip()
                    if not pid or pid not in expected_homa_str or pid not in expected_status or pid not in meds_by_patient:
                        constraints_ok = False
                        break
                    # a) word count 60-120
                    wc = _count_words(msg)
                    if wc < 60 or wc > 120:
                        constraints_ok = False
                        break
                    # b) start with "Hello,"
                    if not msg.startswith("Hello,"):
                        constraints_ok = False
                        break
                    # c) include HOMA-IR and status exact
                    homa_phrase = f"HOMA-IR: {expected_homa_str[pid]}"
                    if homa_phrase not in msg:
                        constraints_ok = False
                        break
                    status_phrase = f"status: {expected_status[pid]}"
                    if status_phrase not in msg:
                        constraints_ok = False
                        break
                    # d) include "Current meds: <exact meds_current from CSV>"
                    meds_exact = meds_by_patient.get(pid, "")
                    meds_phrase = f"Current meds: {meds_exact}"
                    if meds_phrase not in msg:
                        constraints_ok = False
                        break
                    # e) plan sentence
                    if expected_status[pid] == "elevated":
                        if "Plan: schedule labs in 3 months." not in msg:
                            constraints_ok = False
                            break
                    else:
                        if "Plan: recheck labs in 6 months." not in msg:
                            constraints_ok = False
                            break
                    # f) end with phrase
                    if not msg.endswith("Please reply to this message if you have questions."):
                        constraints_ok = False
                        break
            if constraints_ok:
                scores["messages_content_constraints"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()