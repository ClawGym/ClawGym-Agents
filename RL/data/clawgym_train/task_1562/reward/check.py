import json
import sys
import csv
import re
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_metadata(md_text: str) -> Tuple[Optional[float], Optional[Tuple[float, float]], Optional[str], Dict[str, str]]:
    panel_area = None
    irr_range = None
    setup_sentence = None
    kv: Dict[str, str] = {}
    lines = [ln.strip() for ln in md_text.splitlines() if ln.strip()]
    # Extract key-value pairs and a sentence describing the setup
    for ln in lines:
        if ":" in ln and not ln.startswith("#"):
            # key: value pairs like 'panel_area_m2: 0.5'
            parts = ln.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            kv[key] = val
            if key == "panel_area_m2":
                try:
                    panel_area = float(val)
                except Exception:
                    panel_area = None
            if key == "comparison_irradiance_range":
                # expect "700-800"
                m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*-\s*([0-9]+(?:\.[0-9]+)?)\s*$", val)
                if m:
                    try:
                        lo = float(m.group(1))
                        hi = float(m.group(2))
                        irr_range = (lo, hi)
                    except Exception:
                        irr_range = None
        else:
            # A prose sentence without colon and not a header; pick the first that ends with a period
            if setup_sentence is None and ln.endswith(".") and not ln.startswith("#"):
                setup_sentence = ln
    return panel_area, irr_range, setup_sentence, kv


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _safe_float(val: Any) -> Optional[float]:
    try:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _compute_metrics(rows: List[Dict[str, Any]], lo: float, hi: float, panel_area: float) -> Optional[Dict[str, float]]:
    try:
        used = []
        for r in rows:
            irr = _safe_float(r.get("irradiance_Wm2"))
            volt = _safe_float(r.get("voltage_V"))
            curr = _safe_float(r.get("current_A"))
            temp = _safe_float(r.get("panel_temp_C"))
            if None in (irr, volt, curr, temp):
                continue
            if irr < lo or irr > hi:
                continue
            power = volt * curr
            denom = irr * panel_area
            if denom == 0:
                continue
            eff = power / denom
            used.append((power, temp, eff))
        rows_used = len(used)
        if rows_used == 0:
            return {"rows_used": 0, "mean_power_W": float("nan"), "mean_panel_temp_C": float("nan"), "mean_efficiency": float("nan")}
        mean_power = sum(p for p, _, _ in used) / rows_used
        mean_temp = sum(t for _, t, _ in used) / rows_used
        mean_eff = sum(e for _, _, e in used) / rows_used
        return {
            "rows_used": rows_used,
            "mean_power_W": mean_power,
            "mean_panel_temp_C": mean_temp,
            "mean_efficiency": mean_eff,
        }
    except Exception:
        return None


def _close(a: float, b: float, rel: float = 1e-3, abs_tol: float = 1e-3) -> bool:
    try:
        if a == b:
            return True
        diff = abs(a - b)
        return diff <= max(rel * max(abs(a), abs(b)), abs_tol)
    except Exception:
        return False


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _extract_percent_numbers(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r"(-?\d+(?:\.\d+)?)\s*%", text):
        try:
            nums.append(float(m.group(1)))
        except Exception:
            continue
    return nums


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "status_summary_exists": 0.0,
        "status_summary_range_and_area": 0.0,
        "status_summary_before_metrics": 0.0,
        "status_summary_after_metrics": 0.0,
        "status_summary_improvement_percent": 0.0,
        "report_exists": 0.0,
        "report_contains_metadata_sentence": 0.0,
        "report_mentions_inputs_range_improvement": 0.0,
        "email_exists": 0.0,
        "email_has_subject_and_contact_details": 0.0,
        "email_mentions_report_and_improvement": 0.0,
        "email_sentence_count_2_to_3": 0.0,
    }

    # Load metadata
    meta_path = workspace / "input" / "metadata.md"
    meta_text = _read_text(meta_path)
    panel_area = None
    irr_range = None
    setup_sentence = None
    meta_kv = {}
    if meta_text is not None:
        panel_area, irr_range, setup_sentence, meta_kv = _parse_metadata(meta_text)

    # Load input CSVs
    before_rows = _read_csv_rows(workspace / "input" / "before_cleaning.csv")
    after_rows = _read_csv_rows(workspace / "input" / "after_cleaning.csv")

    # Compute expected metrics if possible
    expected_before = None
    expected_after = None
    expected_improvement = None
    if panel_area is not None and irr_range is not None and before_rows is not None and after_rows is not None:
        expected_before = _compute_metrics(before_rows, irr_range[0], irr_range[1], panel_area)
        expected_after = _compute_metrics(after_rows, irr_range[0], irr_range[1], panel_area)
        if expected_before and expected_after and expected_before.get("rows_used", 0) > 0:
            b_mean_power = expected_before["mean_power_W"]
            a_mean_power = expected_after["mean_power_W"]
            try:
                expected_improvement = ((a_mean_power - b_mean_power) / b_mean_power) * 100.0
            except Exception:
                expected_improvement = None

    # Check outputs/status_summary.json
    summary_path = workspace / "outputs" / "status_summary.json"
    summary = _load_json(summary_path)
    if summary is not None and isinstance(summary, dict):
        scores["status_summary_exists"] = 1.0
        # range and area
        try:
            range_used = summary.get("range_used")
            panel_area_out = summary.get("panel_area_m2")
            has_range = isinstance(range_used, list) and len(range_used) == 2 and all(isinstance(x, (int, float)) for x in range_used)
            has_area = isinstance(panel_area_out, (int, float))
            if has_range and has_area and irr_range is not None and panel_area is not None:
                if _close(float(range_used[0]), irr_range[0]) and _close(float(range_used[1]), irr_range[1]) and _close(float(panel_area_out), float(panel_area)):
                    scores["status_summary_range_and_area"] = 1.0
        except Exception:
            pass

        # before metrics
        try:
            before_out = summary.get("before")
            if isinstance(before_out, dict) and expected_before is not None:
                rows_ok = int(before_out.get("rows", -1)) == int(expected_before.get("rows_used", -2))
                mp_ok = _close(float(before_out.get("mean_power_W")), float(expected_before.get("mean_power_W")))
                me_ok = _close(float(before_out.get("mean_efficiency")), float(expected_before.get("mean_efficiency")))
                mt_ok = _close(float(before_out.get("mean_panel_temp_C")), float(expected_before.get("mean_panel_temp_C")))
                if rows_ok and mp_ok and me_ok and mt_ok:
                    scores["status_summary_before_metrics"] = 1.0
        except Exception:
            pass

        # after metrics
        try:
            after_out = summary.get("after")
            if isinstance(after_out, dict) and expected_after is not None:
                rows_ok = int(after_out.get("rows", -1)) == int(expected_after.get("rows_used", -2))
                mp_ok = _close(float(after_out.get("mean_power_W")), float(expected_after.get("mean_power_W")))
                me_ok = _close(float(after_out.get("mean_efficiency")), float(expected_after.get("mean_efficiency")))
                mt_ok = _close(float(after_out.get("mean_panel_temp_C")), float(expected_after.get("mean_panel_temp_C")))
                if rows_ok and mp_ok and me_ok and mt_ok:
                    scores["status_summary_after_metrics"] = 1.0
        except Exception:
            pass

        # improvement percent
        try:
            imp_out = summary.get("improvement_percent_power")
            if imp_out is not None and expected_improvement is not None:
                if _close(float(imp_out), float(expected_improvement), rel=1e-3, abs_tol=1e-3):
                    scores["status_summary_improvement_percent"] = 1.0
        except Exception:
            pass

    # Check outputs/report.md
    report_path = workspace / "outputs" / "report.md"
    report_text = _read_text(report_path)
    if report_text is not None:
        scores["report_exists"] = 1.0
        # Contains one sentence from metadata.md describing the setup
        if setup_sentence:
            if _normalize_spaces(setup_sentence) in _normalize_spaces(report_text):
                scores["report_contains_metadata_sentence"] = 1.0
        # Mentions inputs, range values, and improvement percent
        has_before_src = "input/before_cleaning.csv" in report_text
        has_after_src = "input/after_cleaning.csv" in report_text
        has_range_vals = False
        if irr_range is not None:
            # Accept either hyphenated or separate values presence
            if str(int(irr_range[0])) in report_text and str(int(irr_range[1])) in report_text:
                has_range_vals = True
        has_improvement = False
        if expected_improvement is not None:
            nums = _extract_percent_numbers(report_text)
            for n in nums:
                if abs(n - expected_improvement) <= 0.5:
                    has_improvement = True
                    break
        if has_before_src and has_after_src and has_range_vals and has_improvement:
            scores["report_mentions_inputs_range_improvement"] = 1.0

    # Check outputs/email_to_advisor.txt
    email_path = workspace / "outputs" / "email_to_advisor.txt"
    email_text = _read_text(email_path)
    if email_text is not None:
        scores["email_exists"] = 1.0
        # Load club contact
        contact_path = workspace / "input" / "club_contact.json"
        contact = _load_json(contact_path) or {}
        advisor_name = contact.get("advisor_name")
        advisor_email = contact.get("email")
        club_name = contact.get("club_name")

        # Subject line and contact details
        lines = email_text.splitlines()
        has_subject = any(l.strip().lower().startswith("subject:") for l in lines)
        has_advisor = isinstance(advisor_name, str) and advisor_name in email_text
        has_email = isinstance(advisor_email, str) and advisor_email in email_text
        has_club = isinstance(club_name, str) and club_name in email_text
        if has_subject and has_advisor and has_email and has_club:
            scores["email_has_subject_and_contact_details"] = 1.0

        # Mentions report and improvement percent
        mentions_report = "outputs/report.md" in email_text
        mentions_improvement = False
        if expected_improvement is not None:
            nums = _extract_percent_numbers(email_text)
            for n in nums:
                if abs(n - expected_improvement) <= 0.5:
                    mentions_improvement = True
                    break
        if mentions_report and mentions_improvement:
            scores["email_mentions_report_and_improvement"] = 1.0

        # Sentence count 2–3 in body (exclude header-like lines)
        body_lines = [l for l in lines if not re.match(r"^\s*(subject|to|from):", l.strip(), flags=re.I)]
        body = " ".join(body_lines).strip()
        # Count sentences by ., !, or ?
        # Avoid counting decimal periods in numbers with percent by replacing them temporarily
        tmp = re.sub(r"(\d)\.(\d)", r"\1DECIMAL_POINT\2", body)
        parts = re.split(r"[.!?]+", tmp)
        sentences = [s.strip() for s in parts if s.strip()]
        count = len(sentences)
        if 2 <= count <= 3:
            scores["email_sentence_count_2_to_3"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()