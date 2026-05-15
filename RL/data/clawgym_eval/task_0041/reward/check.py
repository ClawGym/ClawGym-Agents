import json
import csv
import sys
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional


REQUIRED_THRESHOLDS = {
    "min_snr_db": 62.0,
    "max_power_mw": 45.0,
    "min_bandwidth_khz": 180.0,
}

EXPECTED_COLUMNS = [
    "design_id",
    "test_date",
    "pass_fail",
    "snr_db",
    "bandwidth_khz",
    "power_mw",
    "supply_v",
    "notes",
]


def _load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _load_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None, "Missing header"
            rows = []
            for row in reader:
                rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows, reader.fieldnames, None
    except Exception as e:
        return None, None, str(e)


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _run_process_logs(workspace: Path) -> Tuple[bool, str]:
    script = workspace / "scripts" / "process_logs.py"
    if not script.exists():
        return False, "scripts/process_logs.py missing"
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            text=True,
        )
        if proc.returncode != 0:
            return False, f"Non-zero exit: {proc.returncode}\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
        return True, proc.stdout
    except Exception as e:
        return False, str(e)


def _discover_input_csvs(workspace: Path) -> List[Path]:
    input_dir = workspace / "input" / "logs"
    if not input_dir.exists():
        return []
    return sorted([p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"])


def _compute_expected_from_inputs(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[Dict[str, str]]], Optional[Dict]]:
    csv_paths = _discover_input_csvs(workspace)
    if not csv_paths:
        return None, None, None

    all_rows: List[Dict[str, str]] = []
    for p in csv_paths:
        rows, headers, err = _load_csv(p)
        if rows is None or headers is None:
            return None, None, None
        all_rows.extend(rows)

    latest_map: Dict[str, Dict[str, str]] = {}
    latest_date_map: Dict[str, datetime] = {}
    for row in all_rows:
        did = row.get("design_id", "")
        dt_str = row.get("test_date", "")
        dt = _parse_date(dt_str)
        if dt is None:
            return None, None, None
        prev_dt = latest_date_map.get(did)
        if prev_dt is None or dt > prev_dt:
            latest_date_map[did] = dt
            latest_map[did] = row

    thresholds = REQUIRED_THRESHOLDS

    def meets_thresholds(r: Dict[str, str]) -> Optional[bool]:
        snr = _safe_float(r.get("snr_db", ""))
        bw = _safe_float(r.get("bandwidth_khz", ""))
        pwr = _safe_float(r.get("power_mw", ""))
        if snr is None or bw is None or pwr is None:
            return None
        return (
            snr >= thresholds["min_snr_db"]
            and pwr <= thresholds["max_power_mw"]
            and bw >= thresholds["min_bandwidth_khz"]
        )

    latest_designs = list(latest_map.keys())
    candidates: List[Dict[str, str]] = []
    rejections_latest: Dict[str, str] = {}
    for did in latest_designs:
        r = latest_map[did]
        pf = r.get("pass_fail", "")
        if pf != "PASS":
            rejections_latest[did] = "fail_flag"
        else:
            mt = meets_thresholds(r)
            if mt is None:
                rejections_latest[did] = "threshold"
            elif mt:
                candidates.append(r)
            else:
                rejections_latest[did] = "threshold"

    def cand_key(r: Dict[str, str]):
        snr = _safe_float(r.get("snr_db", "")) or float("-inf")
        bw = _safe_float(r.get("bandwidth_khz", "")) or float("-inf")
        pwr = _safe_float(r.get("power_mw", "")) or float("inf")
        return (-snr, -bw, pwr)

    candidates_sorted = sorted(candidates, key=cand_key)
    candidates_with_rank: List[Dict[str, str]] = []
    for idx, r in enumerate(candidates_sorted, start=1):
        nr = dict(r)
        nr["rank"] = str(idx)
        candidates_with_rank.append(nr)

    candidate_keys = {(r["design_id"], r["test_date"]) for r in candidates_sorted}
    latest_keys = {(latest_map[did]["design_id"], latest_map[did]["test_date"]) for did in latest_designs}

    rejected_rows: List[Dict[str, str]] = []
    for r in all_rows:
        key = (r.get("design_id", ""), r.get("test_date", ""))
        if key in candidate_keys:
            continue
        if key not in latest_keys:
            reason = "not_latest"
        else:
            did = r.get("design_id", "")
            reason = rejections_latest.get(did, "threshold")
        nr = dict(r)
        nr["reject_reason"] = reason
        rejected_rows.append(nr)

    summary = {
        "thresholds": {
            "min_snr_db": thresholds["min_snr_db"],
            "max_power_mw": thresholds["max_power_mw"],
            "min_bandwidth_khz": thresholds["min_bandwidth_khz"],
        },
        "total_records": len(all_rows),
        "total_unique_designs": len(latest_designs),
        "candidates_count": len(candidates_sorted),
        "rejected_count": len(rejected_rows),
        "top_designs": [
            {"design_id": r["design_id"], "snr_db": _safe_float(r.get("snr_db", ""))}
            for r in candidates_sorted[:3]
        ],
    }

    return candidates_with_rank, rejected_rows, summary


def _compare_float_str(a: str, b: str, tol: float = 1e-6) -> bool:
    fa = _safe_float(a)
    fb = _safe_float(b)
    if fa is None or fb is None:
        return a == b
    return abs(fa - fb) <= tol


def _rows_match_expected(actual_row: Dict[str, str], expected_row: Dict[str, str], compare_fields: List[str]) -> bool:
    for k in compare_fields:
        av = actual_row.get(k, "")
        ev = expected_row.get(k, "")
        if k in ("snr_db", "bandwidth_khz", "power_mw"):
            if not _compare_float_str(str(av), str(ev)):
                return False
        else:
            if str(av) != str(ev):
                return False
    return True


def _fmt_num_key(val: str) -> str:
    f = _safe_float(val)
    if f is None:
        return "INVALID"
    return f"{f:.6f}"


def _validate_lab_notes(lab_path: Path, summary: Dict) -> float:
    try:
        text = lab_path.read_text(encoding="utf-8")
    except Exception:
        return 0.0
    header = "## Automated Screening"
    if header not in text:
        return 0.0
    parts = text.split(header, 1)
    if len(parts) < 2:
        return 0.0
    after_header = parts[1]
    m = re.search(r"\n##\s", after_header)
    if m:
        section_content = after_header[: m.start()]
    else:
        section_content = after_header
    section = section_content.strip()
    if "Pending automation" in section:
        return 0.0
    tvals = summary.get("thresholds", {})
    patterns = []
    for val in [tvals.get("min_snr_db"), tvals.get("max_power_mw"), tvals.get("min_bandwidth_khz")]:
        if isinstance(val, (int, float)):
            sval = str(val)
            if sval.endswith(".0"):
                base = sval[:-2]
                patterns.append(rf"(?<![\d.]){re.escape(base)}(?:\.0)?(?![\d.])")
            else:
                patterns.append(rf"(?<![\d.]){re.escape(sval)}(?![\d.])")
    for pat in patterns:
        if not re.search(pat, section):
            return 0.0
    count_checks = [
        ("total_records", summary.get("total_records")),
        ("unique_designs", summary.get("total_unique_designs")),
        ("candidates", summary.get("candidates_count")),
        ("rejected", summary.get("rejected_count")),
    ]
    for _label, val in count_checks:
        if not isinstance(val, int):
            return 0.0
        pat = rf"(?<![\d.]){val}(?![\d.])"
        if not re.search(pat, section):
            return 0.0
    top_designs = summary.get("top_designs", [])
    if len(top_designs) > 0:
        first = top_designs[0]
        did = str(first.get("design_id", ""))
        snr = first.get("snr_db")
        if did == "" or not isinstance(snr, (int, float)):
            return 0.0
        bullet_found = False
        for line in section.splitlines():
            if re.match(r"^\s*[-*]\s+", line):
                if did in line and re.search(rf"(?<![\d.]){re.escape(str(snr))}(?![\d.])", line):
                    bullet_found = True
                    break
        if not bullet_found:
            return 0.0
    return 1.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "thresholds_updated_exact": 0.0,
        "script_runs_and_generates_outputs": 0.0,
        "top_candidates_csv_correct": 0.0,
        "rejected_csv_correct": 0.0,
        "summary_json_correct": 0.0,
        "lab_notes_section_updated": 0.0,
    }

    config_path = workspace / "configs" / "filters.json"
    cfg, _ = _load_json(config_path)
    if cfg is not None and isinstance(cfg, dict):
        if set(cfg.keys()) == set(REQUIRED_THRESHOLDS.keys()):
            try:
                if (
                    float(cfg.get("min_snr_db")) == REQUIRED_THRESHOLDS["min_snr_db"]
                    and float(cfg.get("max_power_mw")) == REQUIRED_THRESHOLDS["max_power_mw"]
                    and float(cfg.get("min_bandwidth_khz")) == REQUIRED_THRESHOLDS["min_bandwidth_khz"]
                ):
                    scores["thresholds_updated_exact"] = 1.0
            except Exception:
                pass

    ran, _ = _run_process_logs(workspace)
    top_path = workspace / "output" / "top_candidates.csv"
    rej_path = workspace / "output" / "rejected.csv"
    sum_path = workspace / "output" / "summary.json"
    outputs_exist = top_path.exists() and rej_path.exists() and sum_path.exists()
    if ran and outputs_exist:
        scores["script_runs_and_generates_outputs"] = 1.0

    exp_candidates, exp_rejected, exp_summary = _compute_expected_from_inputs(workspace)

    rows_top, headers_top, _ = _load_csv(top_path)
    if rows_top is not None and headers_top is not None and exp_candidates is not None:
        expected_header = EXPECTED_COLUMNS + ["rank"]
        if headers_top == expected_header:
            if len(rows_top) == len(exp_candidates):
                ok = True
                act_map = {r.get("design_id", ""): r for r in rows_top}
                exp_map = {r.get("design_id", ""): r for r in exp_candidates}
                if set(act_map.keys()) != set(exp_map.keys()):
                    ok = False
                else:
                    for did in exp_map:
                        ar = act_map[did]
                        er = exp_map[did]
                        comp_fields = EXPECTED_COLUMNS + ["rank"]
                        if not _rows_match_expected(ar, er, comp_fields):
                            ok = False
                            break
                if ok:
                    try:
                        ranks = [int(r.get("rank", "0")) for r in rows_top]
                        if ranks != list(range(1, len(rows_top) + 1)):
                            ok = False
                    except Exception:
                        ok = False
                    def sort_key(r):
                        return (
                            -(_safe_float(r.get("snr_db", "")) or float("-inf")),
                            -(_safe_float(r.get("bandwidth_khz", "")) or float("-inf")),
                            (_safe_float(r.get("power_mw", "")) or float("inf")),
                        )
                    sorted_rows = sorted(rows_top, key=sort_key)
                    if [r["design_id"] for r in rows_top] != [r["design_id"] for r in sorted_rows]:
                        ok = False
                if ok:
                    scores["top_candidates_csv_correct"] = 1.0

    rows_rej, headers_rej, _ = _load_csv(rej_path)
    if rows_rej is not None and headers_rej is not None and exp_rejected is not None:
        expected_header = EXPECTED_COLUMNS + ["reject_reason"]
        if headers_rej == expected_header and len(rows_rej) == len(exp_rejected):
            ok = True
            def key_tuple(r: Dict[str, str]) -> Tuple:
                return (
                    r.get("design_id", ""),
                    r.get("test_date", ""),
                    r.get("pass_fail", ""),
                    _fmt_num_key(r.get("snr_db", "")),
                    _fmt_num_key(r.get("bandwidth_khz", "")),
                    _fmt_num_key(r.get("power_mw", "")),
                    r.get("supply_v", ""),
                    r.get("notes", ""),
                    r.get("reject_reason", ""),
                )
            exp_keys = [key_tuple(r) for r in exp_rejected]
            act_keys = [key_tuple(r) for r in rows_rej]
            if sorted(exp_keys) != sorted(act_keys):
                ok = False
            if ok:
                scores["rejected_csv_correct"] = 1.0

    summary, _ = _load_json(sum_path)
    if summary is not None and isinstance(summary, dict) and exp_summary is not None:
        ok = True
        th = summary.get("thresholds")
        if not isinstance(th, dict):
            ok = False
        else:
            try:
                if not (
                    float(th.get("min_snr_db")) == REQUIRED_THRESHOLDS["min_snr_db"]
                    and float(th.get("max_power_mw")) == REQUIRED_THRESHOLDS["max_power_mw"]
                    and float(th.get("min_bandwidth_khz")) == REQUIRED_THRESHOLDS["min_bandwidth_khz"]
                ):
                    ok = False
            except Exception:
                ok = False
        if summary.get("total_records") != exp_summary.get("total_records"):
            ok = False
        if summary.get("total_unique_designs") != exp_summary.get("total_unique_designs"):
            ok = False
        if summary.get("candidates_count") != exp_summary.get("candidates_count"):
            ok = False
        if summary.get("rejected_count") != exp_summary.get("rejected_count"):
            ok = False
        td = summary.get("top_designs")
        if not isinstance(td, list):
            ok = False
        else:
            exp_td = exp_summary.get("top_designs", [])
            if len(td) != len(exp_td):
                ok = False
            else:
                for a, e in zip(td, exp_td):
                    if not isinstance(a, dict):
                        ok = False
                        break
                    if a.get("design_id") != e.get("design_id"):
                        ok = False
                        break
                    try:
                        if float(a.get("snr_db")) != float(e.get("snr_db")):
                            ok = False
                            break
                    except Exception:
                        ok = False
                        break
        if ok:
            scores["summary_json_correct"] = 1.0

    lab_path = workspace / "docs" / "lab_notes.md"
    if exp_summary is not None and lab_path.exists():
        scores["lab_notes_section_updated"] = _validate_lab_notes(lab_path, exp_summary)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()