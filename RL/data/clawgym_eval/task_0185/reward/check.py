import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_list(path: Path):
    try:
        data = json.loads(_read_text(path))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return None


def _save_json_list(path: Path, data):
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames if reader.fieldnames else []
    except Exception:
        return None, None


def _parse_schedule_yaml(path: Path) -> dict:
    # Minimal YAML parser for simple key: "value" pairs
    config = {}
    try:
        text = _read_text(path)
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # remove inline comments
            if "#" in val:
                val = val.split("#", 1)[0].strip()
            # strip surrounding quotes
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            config[key] = val
    except Exception:
        pass
    return config


def _parse_case_html(text: str) -> dict:
    # Extract key-value pairs from simple <tr><th>Key</th><td>Value</td></tr> structure
    result = {}
    try:
        pattern = re.compile(
            r"<tr>\s*<th>\s*([^<]+)\s*</th>\s*<td>\s*([^<]+)\s*</td>\s*</tr>",
            re.IGNORECASE | re.DOTALL,
        )
        for m in pattern.finditer(text):
            key = m.group(1).strip().lower()
            val = m.group(2).strip()
            if key == "case id":
                result["case_id"] = val
            elif key == "officer":
                result["officer"] = val
            elif key == "agency":
                result["agency"] = val
            elif key == "allegation":
                result["allegation"] = val
            elif key == "status":
                result["status"] = val
            elif key == "last updated":
                result["last_updated"] = val
    except Exception:
        return {}
    return result


def _load_cases_from_html(dir_path: Path) -> dict:
    cases = {}
    if not dir_path.exists():
        return cases
    for p in sorted(dir_path.glob("*.html")):
        text = _read_text(p)
        if not text:
            continue
        parsed = _parse_case_html(text)
        cid = parsed.get("case_id")
        if cid:
            cases[cid] = parsed
    return cases


def _parse_date(d: str):
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None


def _lower_or_blank(s):
    return (s or "").strip().lower()


def _extract_t_ids(s: str):
    # Extract tip IDs like T-0001 using regex to robustly compare sets
    if not s:
        return set()
    return set(re.findall(r"T-\d{4}", s))


def _find_line_with_tokens(lines, tokens):
    for line in lines:
        ok = True
        for tok in tokens:
            if tok not in line:
                ok = False
                break
        if ok:
            return True
    return False


def _compute_expected(workspace: Path, run_date_str: str):
    # Read configuration with fallbacks to explicit required paths
    schedule_path = workspace / "input" / "config" / "schedule.yaml"
    cfg = _parse_schedule_yaml(schedule_path) if schedule_path.exists() else {}
    output_dir_cfg = cfg.get("output_dir", "output/run")
    tips_glob = cfg.get("source_tip_glob", "input/tips/*.csv")
    html_dir_cfg = cfg.get("source_html_dir", "input/discipline_snapshots")
    state_file_cfg = cfg.get("state_file", "state/processed_tip_ids.json")
    daily_time = cfg.get("daily_time", "06:00")
    try:
        top_n = int(cfg.get("top_n", "5"))
    except Exception:
        top_n = 5

    run_date = _parse_date(run_date_str)
    # Load state
    state_file = workspace / state_file_cfg
    processed_ids = _load_json_list(state_file)
    if processed_ids is None:
        processed_ids = []

    # Load watchlist
    watchlist_path = workspace / "input" / "config" / "watchlist.csv"
    watch_agencies = set()
    watch_officers = set()
    wl_rows, wl_fields = _read_csv_dicts(watchlist_path)
    if wl_rows is not None:
        for row in wl_rows:
            t = (row.get("type") or "").strip().lower()
            flag = (row.get("flag") or "").strip().lower()
            if flag != "watch":
                continue
            if t == "agency":
                name = (row.get("name") or "").strip()
                if name:
                    watch_agencies.add(name)
            elif t == "officer":
                name = (row.get("name") or "").strip()
                if name:
                    watch_officers.add(name)

    # Load cases from HTML
    html_dir = workspace / html_dir_cfg
    cases = _load_cases_from_html(html_dir)

    # Load tips
    # Resolve glob relative to workspace
    tips_files = sorted(workspace.glob(tips_glob))
    tips = []
    for tf in tips_files:
        rows, fields = _read_csv_dicts(tf)
        if rows is None:
            continue
        for r in rows:
            tip_id = (r.get("tip_id") or "").strip()
            date_received = (r.get("date_received") or "").strip()
            d = _parse_date(date_received)
            if not tip_id or d is None:
                continue
            if d <= run_date and tip_id not in processed_ids:
                tips.append({
                    "tip_id": tip_id,
                    "date_received": d,
                    "agency": (r.get("agency") or "").strip(),
                    "allegation_type": (r.get("allegation_type") or "").strip(),
                    "severity": (r.get("severity") or "").strip(),
                    "description": (r.get("description") or "").strip(),
                    "officer_names": (r.get("officer_names") or "").strip(),
                    "source": (r.get("source") or "").strip(),
                    "prior_internal_affairs_flag": (r.get("prior_internal_affairs_flag") or "").strip(),
                    "related_case_id": (r.get("related_case_id") or "").strip(),
                })

    # Cluster tips
    clusters = {}
    for t in tips:
        if t.get("related_case_id"):
            key = t["related_case_id"]
        else:
            key = _lower_or_blank(t["agency"]) + "|" + _lower_or_blank(t["officer_names"]) + "|" + _lower_or_blank(t["allegation_type"])
        if key not in clusters:
            clusters[key] = {
                "cluster_key": key,
                "tips": [],
            }
        clusters[key]["tips"].append(t)

    severity_map = {"low": 1, "medium": 2, "high": 3}
    keyword_list = ["Bribery", "Record tampering", "Retaliation"]

    expected_clusters = []
    for key, data in clusters.items():
        tips_list = data["tips"]
        tip_ids = [x["tip_id"] for x in tips_list]
        most_recent_date = max(x["date_received"] for x in tips_list) if tips_list else None
        smallest_tip_id = min(tip_ids) if tip_ids else ""
        # Choose representative agency and allegation_type from first tip
        agency = tips_list[0]["agency"] if tips_list else ""
        allegation_type = tips_list[0]["allegation_type"] if tips_list else ""
        # Determine severity (highest)
        sev_strs = [(_lower_or_blank(x["severity"])) for x in tips_list]
        sev_num = max([severity_map.get(s, 0) for s in sev_strs]) if sev_strs else 0
        sev_label = ""
        for k, v in severity_map.items():
            if v == sev_num:
                sev_label = k.capitalize()
        # Link to case if key is related_case_id and exists in cases
        case_id = ""
        linked_status = ""
        source = "tips"
        if key in cases:
            case_id = key
            linked_status = cases[key].get("status", "")
            source = "tips+case"
        # Watchlist boost: if cluster’s agency OR any officer appears on watchlist
        officers = set([x["officer_names"].strip() for x in tips_list if x.get("officer_names")])
        watch_boost = 1 if (agency in watch_agencies or any(o in watch_officers for o in officers)) else 0
        # Keyword boost
        kw_boost = 1 if any(kw.lower() in allegation_type.lower() for kw in keyword_list) else 0
        # Linked status boost
        status_boost = 1 if linked_status in {"Pending Hearing", "Sustained"} else 0
        priority_score = sev_num + watch_boost + kw_boost + status_boost
        expected_clusters.append({
            "cluster_key": key,
            "tip_ids": tip_ids,
            "case_id": case_id,
            "agency": agency,
            "allegation_type": allegation_type,
            "severity": sev_label,
            "linked_status": linked_status,
            "priority_score": priority_score,
            "tips_count": len(tip_ids),
            "most_recent_date": most_recent_date,
            "smallest_tip_id": smallest_tip_id,
            "source": source,
        })

    # Sort by priority_score desc, most_recent_date desc, smallest_tip_id asc
    expected_clusters.sort(key=lambda x: (-x["priority_score"], -(x["most_recent_date"].toordinal() if x["most_recent_date"] else -10**9), x["smallest_tip_id"]))

    # Compute expected agency counts for processed tips this run
    agency_counts = {}
    for t in tips:
        ag = t["agency"]
        agency_counts[ag] = agency_counts.get(ag, 0) + 1

    # Determine output run dir
    base_output_dir = output_dir_cfg if output_dir_cfg else "output/run"
    run_dir = workspace / base_output_dir / run_date_str

    # Determine expected next_run string
    try:
        hour, minute = daily_time.split(":")
        hour = int(hour)
        minute = int(minute)
        next_dt = datetime(run_date.year, run_date.month, run_date.day, hour, minute) + timedelta(days=1)
        expected_next_run_str = next_dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        # Fallback to next day 00:00
        next_dt = datetime(run_date.year, run_date.month, run_date.day, 0, 0) + timedelta(days=1)
        expected_next_run_str = next_dt.strftime("%Y-%m-%d %H:%M")

    return {
        "expected_clusters": expected_clusters,
        "agency_counts": agency_counts,
        "run_dir": run_dir,
        "expected_next_run_str": expected_next_run_str,
        "processed_tip_ids": [t["tip_id"] for t in tips],
        "top_n": top_n,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    run_date = "2025-01-11"
    expected = _compute_expected(workspace, run_date)
    run_dir = expected["run_dir"]

    scores = {
        "prioritized_csv_exists": 0.0,
        "prioritized_csv_schema": 0.0,
        "prioritized_csv_content": 0.0,
        "daily_report_exists": 0.0,
        "daily_report_no_officer_names": 0.0,
        "daily_report_agency_counts": 0.0,
        "daily_report_top_section": 0.0,
        "next_run_correct": 0.0,
        "state_updated": 0.0,
        "run_script_supports_run_on": 0.0,
    }

    # Check prioritized_cases.csv
    prioritized_path = run_dir / "prioritized_cases.csv"
    if prioritized_path.exists():
        scores["prioritized_csv_exists"] = 1.0
        rows, headers = _read_csv_dicts(prioritized_path)
        if rows is not None and headers is not None:
            expected_headers = [
                "rank",
                "cluster_key",
                "source",
                "tip_ids",
                "case_id",
                "agency",
                "allegation_type",
                "severity",
                "linked_status",
                "priority_score",
                "tips_count",
            ]
            if headers == expected_headers:
                scores["prioritized_csv_schema"] = 1.0
            # Content checks
            try:
                exp_clusters = expected["expected_clusters"]
                if rows is not None and isinstance(rows, list) and len(rows) == len(exp_clusters) and len(exp_clusters) > 0:
                    ok_all = True
                    # Verify ranks continuous starting at 1 and order matches expected
                    for idx, row in enumerate(rows):
                        # rank check
                        try:
                            rank_val = int(row.get("rank", ""))
                        except Exception:
                            ok_all = False
                            break
                        if rank_val != idx + 1:
                            ok_all = False
                            break
                        exp = exp_clusters[idx]
                        # cluster_key
                        if row.get("cluster_key") != exp["cluster_key"]:
                            ok_all = False
                            break
                        # source
                        if row.get("source") != exp["source"]:
                            ok_all = False
                            break
                        # case_id
                        if (row.get("case_id") or "") != (exp["case_id"] or ""):
                            ok_all = False
                            break
                        # agency
                        if (row.get("agency") or "") != (exp["agency"] or ""):
                            ok_all = False
                            break
                        # allegation_type
                        if (row.get("allegation_type") or "") != (exp["allegation_type"] or ""):
                            ok_all = False
                            break
                        # severity
                        if (row.get("severity") or "") != (exp["severity"] or ""):
                            ok_all = False
                            break
                        # linked_status
                        if (row.get("linked_status") or "") != (exp["linked_status"] or ""):
                            ok_all = False
                            break
                        # priority_score
                        try:
                            ps = int(row.get("priority_score", ""))
                        except Exception:
                            ok_all = False
                            break
                        if ps != exp["priority_score"]:
                            ok_all = False
                            break
                        # tips_count
                        try:
                            tc = int(row.get("tips_count", ""))
                        except Exception:
                            ok_all = False
                            break
                        if tc != exp["tips_count"]:
                            ok_all = False
                            break
                        # tip_ids contain correct set
                        tip_ids_str = row.get("tip_ids", "")
                        found_ids = _extract_t_ids(tip_ids_str)
                        if set(exp["tip_ids"]) != found_ids:
                            ok_all = False
                            break
                    if ok_all:
                        scores["prioritized_csv_content"] = 1.0
            except Exception:
                pass
    # Check daily_report.txt
    daily_report_path = run_dir / "daily_report.txt"
    if daily_report_path.exists():
        scores["daily_report_exists"] = 1.0
        text = _read_text(daily_report_path)
        if text:
            # No officer names leakage
            if ("John Doe" not in text) and ("Jane Smith" not in text):
                scores["daily_report_no_officer_names"] = 1.0
            lines = text.splitlines()
            # Agency counts
            agency_counts = expected["agency_counts"]
            agency_ok = True
            for agency, count in agency_counts.items():
                # look for a line containing both agency and count
                if not _find_line_with_tokens(lines, [agency, str(count)]):
                    agency_ok = False
                    break
            if agency_counts and agency_ok:
                scores["daily_report_agency_counts"] = 1.0
            # Top N section entries for each expected cluster
            top_ok = True
            exp_clusters = expected["expected_clusters"]
            # Only check up to N or number of clusters
            max_check = min(len(exp_clusters), expected.get("top_n", 5))
            for idx in range(max_check):
                rank = idx + 1
                exp = exp_clusters[idx]
                if exp["case_id"]:
                    key_display = exp["case_id"]
                else:
                    # first tip id if no case
                    key_display = sorted(exp["tip_ids"])[0] if exp["tip_ids"] else ""
                tokens = [
                    str(rank),
                    key_display,
                    exp["agency"],
                    exp["allegation_type"],
                    str(exp["priority_score"]),
                    str(exp["tips_count"]),
                ]
                if not _find_line_with_tokens(lines, tokens):
                    top_ok = False
                    break
            if (len(exp_clusters) > 0) and top_ok:
                scores["daily_report_top_section"] = 1.0

    # Check next_run.txt
    next_run_path = run_dir / "next_run.txt"
    if next_run_path.exists():
        next_text = _read_text(next_run_path).strip()
        if next_text == expected["expected_next_run_str"]:
            scores["next_run_correct"] = 1.0

    # Check state updated
    state_path = workspace / "state" / "processed_tip_ids.json"
    state_list = _load_json_list(state_path)
    if isinstance(state_list, list):
        expected_new = set(expected["processed_tip_ids"])
        # ensure all expected new tips are present
        if expected_new and expected_new.issubset(set(state_list)):
            scores["state_updated"] = 1.0

    # Check presence of a runnable script that mentions --run-on
    # Search common script types in workspace root and immediate subdirs
    run_on_found = False
    script_exts = {".py", ".sh", ".bat", ".ps1", ".rb", ".pl", ".js"}
    try:
        for p in workspace.rglob("*"):
            if p.is_file() and p.suffix.lower() in script_exts:
                # Avoid checking very large files unnecessarily
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    if "--run-on" in text:
                        run_on_found = True
                        break
                except Exception:
                    continue
    except Exception:
        run_on_found = False
    if run_on_found:
        scores["run_script_supports_run_on"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()