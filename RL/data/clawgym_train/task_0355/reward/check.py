import json
import sys
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, time
import csv
from collections import defaultdict
import re


def _read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_hhmm(s: str) -> time:
    try:
        hh, mm = s.split(":")
        return time(int(hh), int(mm))
    except Exception:
        return None


def _in_range(t: time, start: time, end: time) -> bool:
    # Half-open interval: start <= t < end
    return (t >= start) and (t < end)


def _run_summarizer(workspace: Path, log_path: Path, cfg_path: Path) -> dict:
    """
    Attempt to run scripts/summarize_log.py to compute expected summary into a temp file.
    Returns parsed dict or None on failure.
    """
    script = workspace / "scripts" / "summarize_log.py"
    if not script.exists():
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "summary.json"
            cmd = [
                sys.executable,
                str(script),
                "--log",
                str(log_path),
                "--config",
                str(cfg_path),
                "--out",
                str(out_path),
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return _load_json_safe(out_path)
    except Exception:
        return None


def _compute_expected_summary_fallback(workspace: Path, log_path: Path, cfg_path: Path) -> dict:
    """
    Compute expected summary using the same logic as scripts/summarize_log.py
    """
    cfg = _load_json_safe(cfg_path)
    if cfg is None:
        return None
    try:
        bh_start = _parse_hhmm(cfg["business_hours"]["start"])
        bh_end = _parse_hhmm(cfg["business_hours"]["end"])
        er_start = _parse_hhmm(cfg["explicit_restricted_hours"]["start"])
        er_end = _parse_hhmm(cfg["explicit_restricted_hours"]["end"])
        explicit_filter_enabled = bool(cfg.get("explicit_filter_enabled", False))
        max_volume = int(cfg.get("max_volume", 70))
    except Exception:
        return None

    total_tracks = 0
    explicit_tracks = 0
    explicit_during_restricted = 0
    plays_outside_business_hours = 0
    loud_plays_over_max = 0

    volumes = []
    vol_by_hour = defaultdict(list)

    try:
        with log_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_tracks += 1
                ts = row.get("timestamp", "").strip()
                try:
                    dt = datetime.fromisoformat(ts)
                except Exception:
                    try:
                        dt = datetime.fromisoformat(ts.replace(" ", "T"))
                    except Exception:
                        return None
                t = dt.time()
                try:
                    vol = int(str(row.get("volume", "")).strip())
                except Exception:
                    return None
                exp_flag = str(row.get("explicit", "")).strip().lower() in ("true", "1", "yes", "y")

                if exp_flag:
                    explicit_tracks += 1
                    if _in_range(t, er_start, er_end):
                        explicit_during_restricted += 1

                if not _in_range(t, bh_start, bh_end):
                    plays_outside_business_hours += 1

                if vol > max_volume:
                    loud_plays_over_max += 1

                volumes.append(vol)
                vol_by_hour[f"{dt.hour:02d}"].append(vol)
    except Exception:
        return None

    avg_overall = round(sum(volumes) / len(volumes), 3) if volumes else 0.0
    avg_by_hour = {h: round(sum(vs) / len(vs), 3) for h, vs in sorted(vol_by_hour.items())}

    result = {
        "total_tracks": total_tracks,
        "explicit_tracks": explicit_tracks,
        "explicit_during_restricted_hours": explicit_during_restricted,
        "plays_outside_business_hours": plays_outside_business_hours,
        "loud_plays_over_max": loud_plays_over_max,
        "avg_volume_overall": avg_overall,
        "avg_volume_by_hour": avg_by_hour,
        "config": {
            "business_hours": cfg["business_hours"],
            "explicit_restricted_hours": cfg["explicit_restricted_hours"],
            "explicit_filter_enabled": explicit_filter_enabled,
            "max_volume": max_volume,
        },
    }
    return result


def _compare_floats(a, b, tol=1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_exists": 0.0,
        "summary_metrics_match_script": 0.0,
        "compliance_report_exists": 0.0,
        "compliance_report_policy_overview": 0.0,
        "compliance_report_config_snapshot": 0.0,
        "compliance_report_key_metrics_listed": 0.0,
        "compliance_report_violations_section": 0.0,
        "compliance_report_recommendations": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_purpose": 0.0,
        "meeting_notes_action_items_coverage": 0.0,
    }

    # Paths
    summary_path = workspace / "output" / "summary.json"
    report_path = workspace / "output" / "compliance_report.md"
    notes_path = workspace / "output" / "meeting_notes.md"
    log_path = workspace / "input" / "playlist_log.csv"
    cfg_path = workspace / "config" / "player.json"
    policy_path = workspace / "input" / "policy.md"

    # Load summary
    summary = _load_json_safe(summary_path)
    if summary is not None:
        scores["summary_exists"] = 1.0

    # Compute expected summary via script (preferred), fallback to internal
    expected_summary = None
    if log_path.exists() and cfg_path.exists():
        expected_summary = _run_summarizer(workspace, log_path, cfg_path)
        if expected_summary is None:
            expected_summary = _compute_expected_summary_fallback(workspace, log_path, cfg_path)

    # Compare summaries
    if summary is not None and expected_summary is not None:
        ok = True
        keys_to_check = [
            "total_tracks",
            "explicit_tracks",
            "explicit_during_restricted_hours",
            "plays_outside_business_hours",
            "loud_plays_over_max",
            "avg_volume_overall",
        ]
        for k in keys_to_check:
            if k not in summary or k not in expected_summary:
                ok = False
                break
            if isinstance(expected_summary[k], float):
                if not _compare_floats(summary[k], expected_summary[k]):
                    ok = False
                    break
            else:
                if summary[k] != expected_summary[k]:
                    ok = False
                    break
        # avg_volume_by_hour dict compare with tolerance
        if ok:
            exp_by_hr = expected_summary.get("avg_volume_by_hour", {})
            got_by_hr = summary.get("avg_volume_by_hour", {})
            if set(exp_by_hr.keys()) != set(got_by_hr.keys()):
                ok = False
            else:
                for h in exp_by_hr:
                    if not _compare_floats(got_by_hr.get(h), exp_by_hr[h]):
                        ok = False
                        break
        scores["summary_metrics_match_script"] = 1.0 if ok else 0.0

    # Compliance report checks
    report_txt = _read_text_safe(report_path)
    if report_txt:
        scores["compliance_report_exists"] = 1.0

    # Policy overview: ensure times and volume limit and keywords are present
    # Require "06:00", "22:00", "17:00", "70", and keywords "business" "hours", "explicit", "volume"
    if report_txt:
        tokens_ok = all(tok in report_txt for tok in ["06:00", "22:00", "17:00", "70"])
        kw = report_txt.lower()
        kw_ok = ("business" in kw and "hours" in kw and "explicit" in kw and "volume" in kw)
        scores["compliance_report_policy_overview"] = 1.0 if (tokens_ok and kw_ok) else 0.0

    # Config snapshot: check explicit_filter_enabled and business_hours presence with values
    if report_txt and cfg_path.exists():
        cfg = _load_json_safe(cfg_path)
        cfg_ok = False
        if cfg is not None:
            efe_val = str(bool(cfg.get("explicit_filter_enabled", False))).lower()
            bh_start = cfg.get("business_hours", {}).get("start")
            bh_end = cfg.get("business_hours", {}).get("end")
            # Require literal keys "explicit_filter_enabled" and "business_hours" present in report,
            # and explicit_filter_enabled value (true/false) present.
            has_keys = ("explicit_filter_enabled" in report_txt and "business_hours" in report_txt)
            has_val = (efe_val in report_txt.lower())
            cfg_ok = has_keys and has_val
            # Optionally verify business hours times appear
            if bh_start and bh_end:
                cfg_ok = cfg_ok and (bh_start in report_txt and bh_end in report_txt)
        scores["compliance_report_config_snapshot"] = 1.0 if cfg_ok else 0.0

    # Key metrics listed: ensure six keys appear with corresponding values on same line
    if report_txt and summary is not None:
        lines = report_txt.splitlines()
        metrics = {
            "total_tracks": summary.get("total_tracks"),
            "explicit_tracks": summary.get("explicit_tracks"),
            "explicit_during_restricted_hours": summary.get("explicit_during_restricted_hours"),
            "plays_outside_business_hours": summary.get("plays_outside_business_hours"),
            "loud_plays_over_max": summary.get("loud_plays_over_max"),
            "avg_volume_overall": summary.get("avg_volume_overall"),
        }
        all_present = True
        for k, v in metrics.items():
            if v is None:
                all_present = False
                break
            # Prepare value string to search
            if isinstance(v, float):
                v_str = f"{v:.3f}"
            else:
                v_str = str(v)
            found_line = False
            for ln in lines:
                if k in ln and v_str in ln:
                    found_line = True
                    break
            if not found_line:
                all_present = False
                break
        scores["compliance_report_key_metrics_listed"] = 1.0 if all_present else 0.0

    # Violations section: must include counts with descriptive phrases
    if report_txt and summary is not None:
        lines = report_txt.splitlines()
        vio_idx = None
        for i, ln in enumerate(lines):
            if "violations" in ln.lower():
                vio_idx = i
                break
        vio_ok = False
        if vio_idx is not None:
            section = "\n".join(lines[vio_idx:])  # from "Violations" to end
            def has_line_with(words, num):
                num_str = str(num)
                for ln in section.splitlines():
                    lnl = ln.lower()
                    if all(w in lnl for w in words) and (num_str in ln):
                        return True
                return False

            ex_during = summary.get("explicit_during_restricted_hours", 0)
            outside = summary.get("plays_outside_business_hours", 0)
            overmax = summary.get("loud_plays_over_max", 0)

            cond1 = has_line_with(["explicit", "restrict"], ex_during)
            cond2 = has_line_with(["outside", "business", "hours"], outside)
            cond3 = has_line_with(["over", "volume", "max"], overmax) or has_line_with(["over", "volume", "maximum"], overmax)
            vio_ok = cond1 and cond2 and cond3
        scores["compliance_report_violations_section"] = 1.0 if vio_ok else 0.0

    # Recommendations: present and logically address violations
    if report_txt and summary is not None:
        rec_idx = None
        rec_lines = report_txt.splitlines()
        for i, ln in enumerate(rec_lines):
            if "recommend" in ln.lower():
                rec_idx = i
                break
        rec_ok = False
        if rec_idx is not None:
            rec_section = "\n".join(rec_lines[rec_idx:])
            ex_during = summary.get("explicit_during_restricted_hours", 0)
            outside = summary.get("plays_outside_business_hours", 0)
            overmax = summary.get("loud_plays_over_max", 0)

            checks = []
            # For explicit violations: look for "explicit filter" or "clean"
            if ex_during > 0:
                cond_ex = (("explicit" in rec_section.lower() and "filter" in rec_section.lower()) or ("clean" in rec_section.lower()))
                checks.append(cond_ex)
            # For outside hours: look for schedule/opening/closing/hours
            if outside > 0:
                cond_out = any(w in rec_section.lower() for w in ["schedule", "opening", "closing", "hours"])
                checks.append(cond_out)
            # For volume: look for "volume" and guidance word
            if overmax > 0:
                l = rec_section.lower()
                cond_vol = ("volume" in l) and any(w in l for w in ["reduce", "lower", "limit", "guideline", "max", "70"])
                checks.append(cond_vol)

            # If no violations, recommendations can be empty; otherwise all checks must be true
            rec_ok = all(checks) if checks else True

        scores["compliance_report_recommendations"] = 1.0 if rec_ok else 0.0

    # Meeting notes checks
    notes_txt = _read_text_safe(notes_path)
    if notes_txt:
        scores["meeting_notes_exists"] = 1.0

    if notes_txt:
        # Purpose line should include the date and keywords
        purpose_ok = False
        for ln in notes_txt.splitlines():
            if ln.strip() == "":
                continue
            lnl = ln.lower()
            if ("2026-04-15" in ln) and ("background" in lnl) and ("compliance" in lnl):
                purpose_ok = True
            break  # only check first non-empty line
        scores["meeting_notes_purpose"] = 1.0 if purpose_ok else 0.0

        # Action items: 3-5 bullets with owners and coverage
        bullets = []
        for ln in notes_txt.splitlines():
            if re.match(r"^\s*([-*]\s+|\d+[.)]\s+)", ln):
                bullets.append(ln.strip())
        count_ok = 3 <= len(bullets) <= 5

        # Owners: require each bullet has an owner token
        owner_tokens = ["shift lead", "opener", "closer", "manager", "supervisor", "lead", "barista"]
        owners_ok = True
        for b in bullets:
            bl = b.lower()
            if not any(tok in bl for tok in owner_tokens):
                owners_ok = False
                break

        # Coverage: require explicit filter/clean and volume and schedule/hours as appropriate
        cov_ex = any(("explicit" in b.lower() and "filter" in b.lower()) or ("clean" in b.lower()) for b in bullets)
        cov_vol = any("volume" in b.lower() for b in bullets)
        cov_sched = any(any(w in b.lower() for w in ["schedule", "opening", "closing", "hours"]) for b in bullets)

        coverage_ok = cov_ex and cov_vol and cov_sched
        scores["meeting_notes_action_items_coverage"] = 1.0 if (count_ok and owners_ok and coverage_ok) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()