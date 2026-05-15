import json
import sys
import subprocess
import csv
import re
from pathlib import Path
from datetime import datetime, timedelta, date
from html import unescape


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv(path: Path) -> list[dict] | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _isoweek_key(d: date) -> str:
    iso = d.isocalendar()
    # Compatible across Python versions returning namedtuple or tuple
    y = iso[0]
    w = iso[1]
    return f"{y}-W{w:02d}"


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _almost_equal(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _strip_tags(html_text: str) -> str:
    # Simple stripper for tags
    return re.sub(r"<[^>]*>", "", html_text)


def _compute_expected_from_inputs(workspace: Path) -> dict | None:
    input_dir = workspace / "input"
    temp_csv = input_dir / "reef_temp.csv"
    catch_csv = input_dir / "catch_log.csv"
    advisory_html = input_dir / "reef_advisory.html"
    checker_py = input_dir / "bleaching_check.py"

    temp_rows = _load_csv(temp_csv)
    catch_rows = _load_csv(catch_csv)
    adv_text = _read_text(advisory_html)

    if temp_rows is None or catch_rows is None or adv_text is None:
        return None

    # Parse temperature CSV
    temps: list[tuple[date, float]] = []
    for r in temp_rows:
        d = _parse_date(r.get("date", ""))
        try:
            t = float(r.get("temp_c", ""))
        except Exception:
            return None
        if d is None:
            return None
        temps.append((d, t))
    if not temps:
        return None
    temps.sort(key=lambda x: x[0])
    start = temps[0][0]
    end = temps[-1][0]
    # Temperature stats
    vals = [t for _, t in temps]
    mean_c = sum(vals) / len(vals)
    max_c = max(vals)
    days_above_30 = sum(1 for _, t in temps if t > 30.0)

    # Catch by species within date span
    catch_by_species: dict[str, dict] = {}
    for r in catch_rows:
        d = _parse_date(r.get("date", ""))
        if d is None:
            return None
        if d < start or d > end:
            continue
        species = r.get("species", "")
        if not species:
            return None
        try:
            kg = float(r.get("kg", ""))
        except Exception:
            return None
        entry = catch_by_species.setdefault(species, {"total_kg": 0.0, "days": set()})
        entry["total_kg"] += kg
        entry["days"].add(d)
    catch_summary = {
        sp: {"total_kg": data["total_kg"], "days_caught": len(data["days"])}
        for sp, data in catch_by_species.items()
    }

    # Advisory parse
    # Level
    level_match = re.search(r"Level:\s*(.*?)</p>", adv_text, flags=re.IGNORECASE | re.DOTALL)
    level = None
    if level_match:
        level = unescape(_strip_tags(level_match.group(1))).strip()
    # Effective dates
    eff_match = re.search(
        r"Effective:\s*(\d{4}-\d{2}-\d{2})\s*to\s*(\d{4}-\d{2}-\d{2})",
        adv_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    eff_start = eff_end = None
    if eff_match:
        eff_start = eff_match.group(1).strip()
        eff_end = eff_match.group(2).strip()
        if _parse_date(eff_start) is None or _parse_date(eff_end) is None:
            return None
    # Advice bullets
    bullets_raw = re.findall(r"<li>(.*?)</li>", adv_text, flags=re.IGNORECASE | re.DOTALL)
    advice_items: list[str] = []
    for b in bullets_raw:
        txt = unescape(_strip_tags(b)).strip()
        if txt:
            advice_items.append(txt)
    if level is None or eff_start is None or eff_end is None:
        return None

    # Compute expected checker outputs: try subprocess then fallback to internal logic
    expected_stdout_text = None
    expected_stderr_text = None

    if checker_py.exists():
        try:
            cmd = [sys.executable, str(checker_py), "--csv", str(temp_csv)]
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            expected_stdout_text = proc.stdout.decode("utf-8", errors="replace")
            expected_stderr_text = proc.stderr.decode("utf-8", errors="replace")
        except Exception:
            expected_stdout_text = None
            expected_stderr_text = None

    if expected_stdout_text is None or expected_stderr_text is None:
        # Fallback: replicate logic
        temps_map = {d: t for d, t in temps}
        expected_by_week: dict[str, set[date]] = {}
        present_by_week: dict[str, list[tuple[date, float]]] = {}

        for d in _daterange(start, end):
            wk = _isoweek_key(d)
            expected_by_week.setdefault(wk, set()).add(d)

        for d, t in temps:
            wk = _isoweek_key(d)
            present_by_week.setdefault(wk, []).append((d, t))

        stderr_lines: list[str] = []
        for wk in sorted(expected_by_week.keys()):
            exp_days = expected_by_week[wk]
            pres_days = {d for d, _ in present_by_week.get(wk, [])}
            missing = len(exp_days - pres_days)
            if missing > 0:
                stderr_lines.append(f"WARNING: Missing {missing} day(s) in {wk}")

        stdout_lines: list[str] = []
        for wk in sorted(present_by_week.keys()):
            vals_wk = [t for _, t in present_by_week[wk]]
            if not vals_wk:
                continue
            mean_t = sum(vals_wk) / len(vals_wk)
            if mean_t >= 30.5:
                level_r = "HIGH"
                stderr_lines.append(f"WARNING: Potential bleaching conditions in {wk} (mean >= 30.5C)")
            elif mean_t >= 30.0:
                level_r = "MODERATE"
            else:
                level_r = "LOW"
            stdout_lines.append(f"RISK[{wk}]={level_r} (mean={mean_t:.2f}C); days={len(vals_wk)}")

        expected_stdout_text = ("\n".join(stdout_lines) + ("\n" if stdout_lines else ""))
        expected_stderr_text = ("\n".join(stderr_lines) + ("\n" if stderr_lines else ""))

    # Parse expected risk mapping and warnings
    risk_by_week: dict[str, str] = {}
    for line in _normalize_newlines(expected_stdout_text).split("\n"):
        if not line.strip():
            continue
        m = re.match(r"RISK\[(\d{4}-W\d{2})\]=(LOW|MODERATE|HIGH)\b", line.strip())
        if m:
            risk_by_week[m.group(1)] = m.group(2)
    expected_warnings = [ln for ln in _normalize_newlines(expected_stderr_text).split("\n") if ln.strip()]

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "temperature": {"mean_c": mean_c, "max_c": max_c, "days_above_30c": days_above_30},
        "catch_by_species": catch_summary,
        "advisory": {
            "level": level,
            "effective_start": eff_start,
            "effective_end": eff_end,
            "advice": advice_items,
        },
        "expected_checker_stdout": expected_stdout_text,
        "expected_checker_stderr": expected_stderr_text,
        "expected_risk_by_week": risk_by_week,
        "expected_warnings": expected_warnings,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "bleaching_stdout_present": 0.0,
        "bleaching_stdout_content_correct": 0.0,
        "bleaching_stderr_present": 0.0,
        "bleaching_stderr_content_correct": 0.0,
        "reef_status_present": 0.0,
        "reef_status_json_valid": 0.0,
        "period_span_correct": 0.0,
        "temperature_summary_correct": 0.0,
        "catch_by_species_summary_correct": 0.0,
        "advisory_extract_correct": 0.0,
        "bleaching_risk_mapping_correct": 0.0,
        "warnings_list_correct": 0.0,
    }

    expected = _compute_expected_from_inputs(workspace)

    output_dir = workspace / "output"
    stdout_path = output_dir / "bleaching_check_stdout.txt"
    stderr_path = output_dir / "bleaching_check_stderr.txt"
    report_path = output_dir / "reef_status.json"

    # Check presence of stdout/stderr
    stdout_text = _read_text(stdout_path)
    if stdout_text is not None:
        scores["bleaching_stdout_present"] = 1.0
    stderr_text = _read_text(stderr_path)
    if stderr_text is not None:
        scores["bleaching_stderr_present"] = 1.0

    # Compare stdout/stderr content if expected available
    if expected is not None and stdout_text is not None:
        if _normalize_newlines(stdout_text) == _normalize_newlines(expected["expected_checker_stdout"]):
            scores["bleaching_stdout_content_correct"] = 1.0
    if expected is not None and stderr_text is not None:
        if _normalize_newlines(stderr_text) == _normalize_newlines(expected["expected_checker_stderr"]):
            scores["bleaching_stderr_content_correct"] = 1.0

    # JSON report existence and validity
    report_obj = _load_json(report_path)
    if report_obj is not None:
        scores["reef_status_present"] = 1.0
        # Validate schema minimally
        try:
            period = report_obj.get("period", {})
            temp = report_obj.get("temperature", {})
            cbs = report_obj.get("catch_by_species", [])
            adv = report_obj.get("advisory", {})
            br = report_obj.get("bleaching_risk_by_week", {})
            warns = report_obj.get("warnings", [])
            schema_ok = True
            schema_ok &= isinstance(period, dict) and isinstance(period.get("start", ""), str) and isinstance(period.get("end", ""), str)
            schema_ok &= isinstance(temp, dict) and isinstance(temp.get("mean_c", None), (int, float)) and isinstance(temp.get("max_c", None), (int, float)) and isinstance(temp.get("days_above_30c", None), int)
            schema_ok &= isinstance(cbs, list)
            schema_ok &= isinstance(adv, dict) and isinstance(adv.get("level", ""), str) and isinstance(adv.get("effective_start", ""), str) and isinstance(adv.get("effective_end", ""), str) and isinstance(adv.get("advice", []), list)
            schema_ok &= isinstance(br, dict)
            schema_ok &= isinstance(warns, list) and all(isinstance(w, str) for w in warns)
            if schema_ok:
                scores["reef_status_json_valid"] = 1.0
        except Exception:
            pass

    # Compare contents with expected
    if expected is not None and report_obj is not None:
        # Period
        rep_period = report_obj.get("period", {})
        if rep_period.get("start") == expected["period"]["start"] and rep_period.get("end") == expected["period"]["end"]:
            scores["period_span_correct"] = 1.0

        # Temperature
        rep_temp = report_obj.get("temperature", {})
        temp_ok = True
        if not isinstance(rep_temp.get("mean_c", None), (int, float)):
            temp_ok = False
        else:
            temp_ok &= _almost_equal(float(rep_temp.get("mean_c")), float(expected["temperature"]["mean_c"]), tol=0.01)
        if not isinstance(rep_temp.get("max_c", None), (int, float)):
            temp_ok = False
        else:
            temp_ok &= _almost_equal(float(rep_temp.get("max_c")), float(expected["temperature"]["max_c"]), tol=1e-9)
        if not isinstance(rep_temp.get("days_above_30c", None), int):
            temp_ok = False
        else:
            temp_ok &= int(rep_temp.get("days_above_30c")) == int(expected["temperature"]["days_above_30c"])
        if temp_ok:
            scores["temperature_summary_correct"] = 1.0

        # Catch by species
        rep_cbs_list = report_obj.get("catch_by_species", [])
        cbs_ok = True
        if not isinstance(rep_cbs_list, list):
            cbs_ok = False
        else:
            # Build maps for comparison
            rep_map: dict[str, dict] = {}
            for item in rep_cbs_list:
                if not isinstance(item, dict):
                    cbs_ok = False
                    break
                sp = item.get("species")
                if not isinstance(sp, str):
                    cbs_ok = False
                    break
                rep_map[sp] = {
                    "total_kg": item.get("total_kg"),
                    "days_caught": item.get("days_caught"),
                }
            if cbs_ok:
                # Species sets must match exactly
                if set(rep_map.keys()) != set(expected["catch_by_species"].keys()):
                    cbs_ok = False
                else:
                    for sp, data in expected["catch_by_species"].items():
                        rep_data = rep_map.get(sp)
                        if rep_data is None:
                            cbs_ok = False
                            break
                        tk = rep_data.get("total_kg")
                        dc = rep_data.get("days_caught")
                        if not isinstance(tk, (int, float)) or not isinstance(dc, int):
                            cbs_ok = False
                            break
                        if not _almost_equal(float(tk), float(data["total_kg"]), tol=1e-6):
                            cbs_ok = False
                            break
                        if int(dc) != int(data["days_caught"]):
                            cbs_ok = False
                            break
        if cbs_ok:
            scores["catch_by_species_summary_correct"] = 1.0

        # Advisory
        rep_adv = report_obj.get("advisory", {})
        adv_ok = True
        if not isinstance(rep_adv.get("level", ""), str) or rep_adv.get("level") != expected["advisory"]["level"]:
            adv_ok = False
        if rep_adv.get("effective_start") != expected["advisory"]["effective_start"]:
            adv_ok = False
        if rep_adv.get("effective_end") != expected["advisory"]["effective_end"]:
            adv_ok = False
        rep_advice = rep_adv.get("advice", [])
        if not isinstance(rep_advice, list):
            adv_ok = False
        else:
            expected_advice = expected["advisory"]["advice"]
            # Require exact match including order and text
            if rep_advice != expected_advice:
                adv_ok = False
        if adv_ok:
            scores["advisory_extract_correct"] = 1.0

        # Bleaching risk mapping
        rep_risk = report_obj.get("bleaching_risk_by_week", {})
        risk_ok = True
        if not isinstance(rep_risk, dict):
            risk_ok = False
        else:
            # Keys and values must match exactly
            if set(rep_risk.keys()) != set(expected["expected_risk_by_week"].keys()):
                risk_ok = False
            else:
                for wk, lvl in expected["expected_risk_by_week"].items():
                    if rep_risk.get(wk) != lvl:
                        risk_ok = False
                        break
        if risk_ok:
            scores["bleaching_risk_mapping_correct"] = 1.0

        # Warnings
        rep_warns = report_obj.get("warnings", [])
        warns_ok = True
        if not isinstance(rep_warns, list):
            warns_ok = False
        else:
            # Require exact list equality (order and content)
            rep_warns_clean = [w for w in rep_warns if isinstance(w, str)]
            if rep_warns_clean != expected["expected_warnings"]:
                warns_ok = False
        if warns_ok:
            scores["warnings_list_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()