import json
import csv
import sys
import re
from pathlib import Path
from datetime import date, datetime
from urllib.parse import urlparse


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if reader.fieldnames is None:
            return None
        return rows
    except Exception:
        return None


def _safe_float(s):
    try:
        return float(s)
    except Exception:
        return None


def _round_one_decimal(x: float) -> float:
    return round(x + 1e-12, 1)


def _compute_stats_from_cases(rows):
    per_condition = {}
    all_vals = []
    for r in rows:
        try:
            cond = r["condition"]
            ga = float(r["gestational_age_weeks"])
        except Exception:
            return None, None
        per_condition.setdefault(cond, []).append(ga)
        all_vals.append(ga)
    per_stats = {}
    for cond, vals in per_condition.items():
        per_stats[cond] = {
            "count": len(vals),
            "mean": _round_one_decimal(sum(vals) / len(vals)) if vals else None,
        }
    overall = {
        "count": len(all_vals),
        "mean": _round_one_decimal(sum(all_vals) / len(all_vals)) if all_vals else None,
    }
    return per_stats, overall


def _parse_cron_line(line: str):
    parts = re.split(r"\s+", line.strip(), maxsplit=5)
    if len(parts) < 6:
        return None
    return parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]


def _is_sunday_dow(dow: str) -> bool:
    s = dow.strip().lower()
    if s in {"0", "7", "sun"}:
        return True
    return False


def _domain_matches(url: str, expected_domain: str) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return host.lower().endswith(expected_domain.lower())
    except Exception:
        return False


def _iso_date_valid(s: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s or ""):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _get_section_by_heading(md_text: str, heading: str) -> str:
    lines = md_text.splitlines()
    indices = [i for i, ln in enumerate(lines) if ln.strip() == heading.strip()]
    if not indices:
        return ""
    start_idx = indices[-1]
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if lines[i].startswith("## "):
            end_idx = i
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def _last_heading_is(md_text: str, heading: str) -> bool:
    lines = [ln.strip() for ln in md_text.strip().splitlines() if ln.strip() != ""]
    last_heading = None
    for ln in lines:
        if ln.startswith("#"):
            last_heading = ln
    return last_heading == heading.strip()


def _find_bullet_lines(section_text: str):
    lines = section_text.splitlines()
    bullets = [ln for ln in lines if ln.strip().startswith(("- ", "* "))]
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present_pythonic": 0.0,
        "cron_schedule_valid": 0.0,
        "cron_schedule_runs_script": 0.0,
        "summary_csv_header_correct": 0.0,
        "summary_csv_per_condition_correct": 0.0,
        "summary_csv_all_row_correct": 0.0,
        "resources_json_has_acog": 0.0,
        "resources_json_has_smfm": 0.0,
        "resources_entries_field_validity": 0.0,
        "resources_queries_topic_focus": 0.0,
        "agenda_appended_section_today": 0.0,
        "agenda_condition_counts_listed": 0.0,
        "agenda_external_resources_listed": 0.0,
        "agenda_action_items_rules": 0.0,
    }

    # Check script presence and basic structure
    script_path = workspace / "scripts" / "generate_weekly_brief.py"
    if script_path.exists() and script_path.is_file():
        text = _read_text(script_path)
        if text:
            has_main_guard = "if __name__" in text
            has_def_main = "def main" in text
            is_python = script_path.suffix == ".py"
            if is_python and (has_main_guard or has_def_main):
                scores["script_present_pythonic"] = 1.0

    # Check cron schedule
    cron_path = workspace / "scheduler" / "cron_schedule.txt"
    if cron_path.exists() and cron_path.is_file():
        cron_text = _read_text(cron_path)
        cron_lines = [ln for ln in cron_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if len(cron_lines) == 1:
            minute_hour_dom_month_dow_cmd = _parse_cron_line(cron_lines[0])
            if minute_hour_dom_month_dow_cmd:
                minute, hour, dom, month, dow, cmd = minute_hour_dom_month_dow_cmd
                valid_time = (minute == "0" and hour == "18" and dom == "*" and month == "*" and _is_sunday_dow(dow))
                if valid_time:
                    scores["cron_schedule_valid"] = 1.0
                if "scripts/generate_weekly_brief.py" in cmd:
                    scores["cron_schedule_runs_script"] = 1.0

    # Compute expected stats from input data
    input_cases_path = workspace / "data" / "simulated_cases.csv"
    expected_per_stats = None
    expected_overall = None
    input_rows = _read_csv_dicts(input_cases_path)
    if input_rows is not None:
        expected_per_stats, expected_overall = _compute_stats_from_cases(input_rows)

    # Validate weekly_summary.csv
    summary_path = workspace / "output" / "weekly_summary.csv"
    if summary_path.exists() and summary_path.is_file():
        try:
            with summary_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            rows = None
        if rows and len(rows) >= 2:
            header = rows[0]
            if header == ["condition", "count", "mean_ga_weeks"]:
                scores["summary_csv_header_correct"] = 1.0
            if expected_per_stats is not None and expected_overall is not None:
                data_rows = rows[1:-1] if len(rows) > 1 else []
                expected_conditions_sorted = sorted(expected_per_stats.keys())
                ok_rows = True
                if len(data_rows) == len(expected_conditions_sorted):
                    for i, cond in enumerate(expected_conditions_sorted):
                        row = data_rows[i]
                        if len(row) != 3:
                            ok_rows = False
                            break
                        cond_field, count_field, mean_field = row
                        if cond_field != cond:
                            ok_rows = False
                            break
                        try:
                            count_val = int(count_field)
                        except Exception:
                            ok_rows = False
                            break
                        if count_val != expected_per_stats[cond]["count"]:
                            ok_rows = False
                            break
                        mean_val = _safe_float(mean_field)
                        if mean_val is None or _round_one_decimal(mean_val) != expected_per_stats[cond]["mean"]:
                            ok_rows = False
                            break
                else:
                    ok_rows = False
                if ok_rows:
                    scores["summary_csv_per_condition_correct"] = 1.0

                last_row = rows[-1]
                if len(last_row) == 3 and last_row[0] == "ALL":
                    try:
                        all_count = int(last_row[1])
                        all_mean = _safe_float(last_row[2])
                    except Exception:
                        all_count = None
                        all_mean = None
                    if (
                        all_count == expected_overall["count"]
                        and all_mean is not None
                        and _round_one_decimal(all_mean) == expected_overall["mean"]
                    ):
                        scores["summary_csv_all_row_correct"] = 1.0

    # Validate resources/resources.json
    resources_path = workspace / "output" / "resources" / "resources.json"
    resources = _load_json(resources_path)
    selected_acog = None
    selected_smfm = None
    if isinstance(resources, list):
        for item in resources:
            if not isinstance(item, dict):
                continue
            org = item.get("organization")
            url = item.get("result_url", "")
            if org == "ACOG" and _domain_matches(url, "acog.org"):
                if selected_acog is None:
                    selected_acog = item
            if org == "SMFM" and _domain_matches(url, "smfm.org"):
                if selected_smfm is None:
                    selected_smfm = item
        if selected_acog is not None:
            scores["resources_json_has_acog"] = 1.0
        if selected_smfm is not None:
            scores["resources_json_has_smfm"] = 1.0

        def _valid_item_fields(it: dict) -> bool:
            required_fields = ["organization", "query_used", "result_title", "result_url", "access_date"]
            for k in required_fields:
                if k not in it:
                    return False
                if not isinstance(it[k], str) or it[k].strip() == "":
                    return False
            if not (it["result_url"].startswith("http://") or it["result_url"].startsWith("https://")):
                return False
            if not _iso_date_valid(it["access_date"]):
                return False
            return True

        # fix .startsWith typo above by providing a backup check if AttributeError occurs
        def _valid_item_fields(it: dict) -> bool:
            required_fields = ["organization", "query_used", "result_title", "result_url", "access_date"]
            for k in required_fields:
                if k not in it:
                    return False
                if not isinstance(it[k], str) or it[k].strip() == "":
                    return False
            url_val = it["result_url"]
            if not (url_val.startswith("http://") or url_val.startswith("https://")):
                return False
            if not _iso_date_valid(it["access_date"]):
                return False
            return True

        if selected_acog is not None and selected_smfm is not None:
            if _valid_item_fields(selected_acog) and _valid_item_fields(selected_smfm):
                scores["resources_entries_field_validity"] = 1.0

        def _query_has_topic(q: str) -> bool:
            ql = q.lower()
            return ("hypertens" in ql) or ("gestational diabetes" in ql) or ("gdm" in ql)
        if selected_acog is not None and selected_smfm is not None:
            if _query_has_topic(selected_acog.get("query_used", "")) and _query_has_topic(selected_smfm.get("query_used", "")):
                scores["resources_queries_topic_focus"] = 1.0

    # Validate docs/meeting_agenda.md appended section
    agenda_path = workspace / "docs" / "meeting_agenda.md"
    agenda_text = _read_text(agenda_path) if agenda_path.exists() else ""
    today_str = date.today().isoformat()
    expected_heading = f"## Weekly MFM Journal Club Summary ({today_str})"
    if agenda_text:
        section_text = _get_section_by_heading(agenda_text, expected_heading)
        if section_text:
            if _last_heading_is(agenda_text, expected_heading):
                scores["agenda_appended_section_today"] = 1.0

            if expected_per_stats is not None:
                counts_ok = True
                for cond, stats in expected_per_stats.items():
                    count = stats["count"]
                    found_line = False
                    for ln in section_text.splitlines():
                        ln_l = ln.lower()
                        if cond.lower() in ln_l and re.search(rf"\b{count}\b", ln):
                            if "case" in ln_l:
                                found_line = True
                                break
                    if not found_line:
                        counts_ok = False
                        break
                if counts_ok:
                    scores["agenda_condition_counts_listed"] = 1.0

            if isinstance(resources, list) and selected_acog and selected_smfm:
                bullets = _find_bullet_lines(section_text)

                def _bullet_contains(title: str, url: str) -> bool:
                    for b in bullets:
                        if title in b and url in b:
                            return True
                    return False

                if _bullet_contains(selected_acog["result_title"], selected_acog["result_url"]) and \
                   _bullet_contains(selected_smfm["result_title"], selected_smfm["result_url"]) and \
                   ("External resources" in section_text or "external resources" in section_text.lower()):
                    scores["agenda_external_resources_listed"] = 1.0

            ai_ok = True
            required_bullets = []
            if expected_per_stats is not None:
                htn_count = expected_per_stats.get("Hypertensive disorder", {}).get("count", 0)
                gdm_count = expected_per_stats.get("Gestational diabetes", {}).get("count", 0)

                htn_bullet = "Action: schedule mini-review of hypertensive disorders of pregnancy."
                gdm_bullet = "Action: review inpatient glucose management for GDM."
                always_bullet = "Action: assign one SMFM Consult or ACOG bulletin from resources.json for discussion."

                if htn_count >= 3:
                    required_bullets.append(htn_bullet)
                if gdm_count >= 2:
                    required_bullets.append(gdm_bullet)
                required_bullets.append(always_bullet)

                for b in required_bullets:
                    if b not in section_text:
                        ai_ok = False
                        break

                if ai_ok:
                    if htn_count < 3 and htn_bullet in section_text:
                        ai_ok = False
                    if gdm_count < 2 and gdm_bullet in section_text:
                        ai_ok = False
            else:
                ai_ok = False

            if ai_ok:
                scores["agenda_action_items_rules"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()