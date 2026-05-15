import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_single_line_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    if len(lines) != 1:
        return None
    try:
        obj = json.loads(lines[0])
        if isinstance(obj, dict):
            return obj
        return None
    except Exception:
        return None


def parse_simple_yaml_kv(path: Path) -> Optional[dict]:
    try:
        content = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    result: Dict[str, object] = {}
    for raw in content:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            hash_idx = line.find("#")
            if hash_idx >= 0:
                line = line[:hash_idx].strip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if re.fullmatch(r"-?\d+", val):
            try:
                parsed = int(val)
            except Exception:
                parsed = val
        elif re.fullmatch(r"-?\d+\.\d+", val):
            try:
                parsed = float(val)
            except Exception:
                parsed = val
        elif val.lower() in ("true", "false"):
            parsed = val.lower() == "true"
        else:
            parsed = val
        result[key] = parsed
    return result


def parse_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [row for row in reader]
            return (reader.fieldnames, rows)
    except Exception:
        return None


def compute_expected_from_input(input_csv: Path) -> Optional[Tuple[Dict[str, Dict[str, float]], int]]:
    parsed = parse_csv(input_csv)
    if not parsed:
        return None
    header, rows = parsed
    for col in ("region", "units", "price"):
        if col not in header:
            return None
    agg: Dict[str, Dict[str, float]] = {}
    row_count = 0
    for row in rows:
        try:
            region = row["region"]
            units = float(row["units"])
            price = float(row["price"])
        except Exception:
            return None
        revenue = units * price
        if region not in agg:
            agg[region] = {"sum_units": 0.0, "sum_revenue": 0.0}
        agg[region]["sum_units"] += units
        agg[region]["sum_revenue"] += revenue
        row_count += 1
    return agg, row_count


def round2(x: float) -> float:
    return round(x + 0.0, 2)


def is_sorted_ascending(strings: List[str]) -> bool:
    return strings == sorted(strings)


def is_relative_path(p: str) -> bool:
    try:
        path = Path(p)
        return not path.is_absolute()
    except Exception:
        if p.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", p):
            return False
        return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_engine_chunked": 0.0,
        "config_chunk_size_three": 0.0,
        "aggregated_csv_structure": 0.0,
        "aggregated_csv_sorted_by_region": 0.0,
        "aggregated_csv_values_correct": 0.0,
        "run_log_single_line_and_keys": 0.0,
        "run_log_counts_consistent": 0.0,
        "run_log_paths_match_config_and_relative": 0.0,
        "pipeline_code_chunked_and_logging_present": 0.0,
        "docs_section_v2_present_and_config_keys": 0.0,
        "docs_runlog_schema_listed": 0.0,
        "docs_v1_v2_memory_extensibility": 0.0,
        "docs_open_questions_updated": 0.0,
        "email_subject_exact": 0.0,
        "email_includes_config_and_paths": 0.0,
        "email_includes_counts_from_log": 0.0,
        "email_requests_feedback_dask_spark_and_log_fields": 0.0,
    }

    cfg_path = workspace / "config" / "pipeline.yaml"
    code_path = workspace / "src" / "pipeline.py"
    input_csv_path = workspace / "input" / "data" / "sales_small.csv"
    out_csv_path = workspace / "outputs" / "region_metrics.csv"
    run_log_path = workspace / "outputs" / "run.log"
    methodology_path = workspace / "docs" / "methodology.md"
    email_path = workspace / "outbox" / "collab_update_email.txt"

    cfg = parse_simple_yaml_kv(cfg_path) or {}

    try:
        if cfg.get("engine") == "chunked":
            scores["config_engine_chunked"] = 1.0
    except Exception:
        pass
    try:
        if str(cfg.get("chunk_size")) == "3" or cfg.get("chunk_size") == 3:
            scores["config_chunk_size_three"] = 1.0
    except Exception:
        pass

    expected_calc = compute_expected_from_input(input_csv_path)
    expected_agg: Optional[Dict[str, Dict[str, float]]] = None
    expected_row_count: Optional[int] = None
    if expected_calc is not None:
        expected_agg, expected_row_count = expected_calc

    parsed_out = parse_csv(out_csv_path)
    header_out: Optional[List[str]] = None
    rows_out: List[Dict[str, str]] = []
    if parsed_out is not None:
        header_out, rows_out = parsed_out

    if header_out is not None:
        if header_out == ["region", "sum_units", "sum_revenue"]:
            scores["aggregated_csv_structure"] = 1.0

    if rows_out:
        regions_order = [r.get("region", "") for r in rows_out]
        if all(isinstance(r, str) for r in regions_order) and is_sorted_ascending(regions_order):
            scores["aggregated_csv_sorted_by_region"] = 1.0

    correct_values = False
    if rows_out and expected_agg is not None:
        actual_map: Dict[str, Dict[str, float]] = {}
        try:
            for r in rows_out:
                reg = r["region"]
                su_raw = r.get("sum_units", "")
                sr_raw = r.get("sum_revenue", "")
                try:
                    su_val = float(su_raw)
                    sr_val = float(sr_raw)
                except Exception:
                    raise ValueError("Non-numeric aggregate values")
                actual_map[reg] = {"sum_units": su_val, "sum_revenue": sr_val}
            exp_regions = sorted(expected_agg.keys())
            act_regions = sorted(actual_map.keys())
            if exp_regions == act_regions:
                ok_all = True
                for reg in exp_regions:
                    exp_su = expected_agg[reg]["sum_units"]
                    exp_sr = expected_agg[reg]["sum_revenue"]
                    act_su = actual_map[reg]["sum_units"]
                    act_sr = actual_map[reg]["sum_revenue"]
                    if int(round(act_su)) != int(round(exp_su)):
                        ok_all = False
                        break
                    if round2(act_sr) != round2(exp_sr):
                        ok_all = False
                        break
                if ok_all:
                    correct_values = True
        except Exception:
            correct_values = False
    if correct_values:
        scores["aggregated_csv_values_correct"] = 1.0

    run_log = parse_single_line_json(run_log_path)
    if run_log is not None:
        expected_keys = {"engine", "chunk_size", "input_path", "output_path", "row_count", "group_count"}
        if set(run_log.keys()) == expected_keys:
            scores["run_log_single_line_and_keys"] = 1.0

    if run_log is not None and expected_row_count is not None and rows_out is not None:
        try:
            log_row_count = int(run_log.get("row_count"))
            out_regions = set()
            for r in rows_out:
                out_regions.add(r.get("region", ""))
            log_group_count = int(run_log.get("group_count"))
            if log_row_count == expected_row_count and log_group_count == len(out_regions):
                scores["run_log_counts_consistent"] = 1.0
        except Exception:
            pass

    if run_log is not None and cfg:
        try:
            ip = str(run_log.get("input_path"))
            op = str(run_log.get("output_path"))
            cfg_ip = str(cfg.get("input_path"))
            cfg_op = str(cfg.get("output_path"))
            if ip == cfg_ip and op == cfg_op and is_relative_path(ip) and is_relative_path(op):
                scores["run_log_paths_match_config_and_relative"] = 1.0
        except Exception:
            pass

    code_text = read_text(code_path) or ""
    code_ok = False
    if code_text:
        if ("engine" in code_text) and ("chunksize" in code_text) and ("run.log" in code_text):
            code_ok = True
    if code_ok:
        scores["pipeline_code_chunked_and_logging_present"] = 1.0

    doc_text = read_text(methodology_path) or ""
    v2_header = "## Pipeline architecture v2 (chunked pandas)"
    v2_section = ""
    if doc_text:
        lines = doc_text.splitlines()
        in_v2 = False
        for ln in lines:
            if ln.strip() == v2_header:
                in_v2 = True
                v2_section = ""
                continue
            if in_v2 and ln.startswith("## "):
                break
            if in_v2:
                v2_section += ln + "\n"
    if v2_section:
        if ("engine" in v2_section) and ("chunk_size" in v2_section):
            scores["docs_section_v2_present_and_config_keys"] = 1.0
        if all(k in v2_section for k in ["engine", "chunk_size", "input_path", "output_path", "row_count", "group_count"]):
            scores["docs_runlog_schema_listed"] = 1.0
        v2_lower = v2_section.lower()
        if ("memory" in v2_lower) and ("extens" in v2_lower):
            scores["docs_v1_v2_memory_extensibility"] = 1.0

    openq_section = ""
    if doc_text:
        lines = doc_text.splitlines()
        in_open = False
        for ln in lines:
            if ln.strip().lower() == "### open questions":
                in_open = True
                openq_section = ""
                continue
            if in_open and ln.startswith("### "):
                break
            if in_open:
                openq_section += ln + "\n"
    if openq_section:
        oq_lower = openq_section.lower()
        memory_addressed = ("memory" in oq_lower) and ("chunk" in oq_lower)
        has_future = ("dask" in oq_lower) or ("spark" in oq_lower)
        if memory_addressed and has_future:
            scores["docs_open_questions_updated"] = 1.0

    email_text = read_text(email_path) or ""
    if email_text:
        email_lines = email_text.splitlines()
        if email_lines:
            subj = email_lines[0].strip("\r\n")
            if subj == "Subject: Scalable pipeline v2 (chunked pandas) — ready for review":
                scores["email_subject_exact"] = 1.0
        body = "\n".join(email_lines[1:]) if len(email_lines) > 1 else ""
        body_lower = body.lower()
        includes_engine_cfg = ("engine" in body_lower and "chunked" in body_lower)
        includes_chunk_size_cfg = ("chunk_size" in body_lower and re.search(r"\b3\b", body_lower) is not None)
        includes_output_paths = ("outputs/region_metrics.csv" in body) and ("outputs/run.log" in body)
        if includes_engine_cfg and includes_chunk_size_cfg and includes_output_paths:
            scores["email_includes_config_and_paths"] = 1.0
        if run_log is not None:
            rc = run_log.get("row_count")
            gc = run_log.get("group_count")
            try:
                rc_str = str(int(rc))
                gc_str = str(int(gc))
            except Exception:
                rc_str = str(rc)
                gc_str = str(gc)
            rc_pattern = re.compile(r"row_count[^0-9]{0,10}" + re.escape(rc_str))
            gc_pattern = re.compile(r"group_count[^0-9]{0,10}" + re.escape(gc_str))
            if rc_pattern.search(body_lower) and gc_pattern.search(body_lower):
                scores["email_includes_counts_from_log"] = 1.0
        asks_feedback = (("dask" in body_lower) or ("spark" in body_lower)) and ("log" in body_lower) and ("field" in body_lower) and (("feedback" in body_lower) or ("suggestion" in body_lower))
        if asks_feedback:
            scores["email_requests_feedback_dask_spark_and_log_fields"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()