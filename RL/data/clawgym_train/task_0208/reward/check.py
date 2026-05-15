import json
import csv
import re
import sys
import shlex
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any


def _safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(p: Path) -> Optional[Any]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_iso_datetime(s: str) -> bool:
    if not isinstance(s, str):
        return False
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _parse_watchlist_yaml(p: Path) -> Optional[List[Dict[str, str]]]:
    text = _safe_read_text(p)
    if text is None:
        return None
    items: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Start of new item with inline key: value
        m_dash_kv = re.match(r"^-\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$", line)
        if m_dash_kv:
            if current is not None:
                items.append(current)
            current = {}
            key = m_dash_kv.group(1)
            val = m_dash_kv.group(2).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            current[key] = val
            continue
        # Start of new item without kv
        if line.startswith("-"):
            if current is not None:
                items.append(current)
            current = {}
            continue
        # key: value line within item
        m_kv = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$", line)
        if m_kv and current is not None:
            key = m_kv.group(1)
            val = m_kv.group(2).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            current[key] = val
            continue
        # Ignore anything else (like top-level "watch_items:")
    if current is not None:
        items.append(current)
    # Validate that each item has required keys
    required = {"org", "topic", "domain", "baseline_key"}
    for it in items:
        if not required.issubset(set(it.keys())):
            return None
    return items


def _load_baseline_json(p: Path) -> Optional[Dict[str, Dict[str, int]]]:
    data = _safe_load_json(p)
    if not isinstance(data, dict):
        return None
    for k, v in data.items():
        if not isinstance(v, dict):
            return None
        by = v.get("baseline_year")
        if not isinstance(by, int):
            return None
    return data  # type: ignore


def _collect_dates(workspace: Path) -> Dict[str, set]:
    dates = {"raw": set(), "agg": set(), "report": set(), "log": set(), "all": set()}
    raw_base = workspace / "data" / "raw"
    if raw_base.exists():
        for child in raw_base.iterdir():
            if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name):
                dates["raw"].add(child.name)
                dates["all"].add(child.name)
    agg_base = workspace / "data" / "aggregates"
    if agg_base.exists():
        for child in agg_base.iterdir():
            if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name):
                dates["agg"].add(child.name)
                dates["all"].add(child.name)
    rep_base = workspace / "reports"
    if rep_base.exists():
        for child in rep_base.iterdir():
            if child.is_file():
                m = re.fullmatch(r"weekly_discipline_watch_(\d{4}-\d{2}-\d{2})\.md", child.name)
                if m:
                    dates["report"].add(m.group(1))
                    dates["all"].add(m.group(1))
    log_base = workspace / "logs"
    if log_base.exists():
        for child in log_base.iterdir():
            if child.is_file():
                m = re.fullmatch(r"discipline_watch_(\d{4}-\d{2}-\d{2})\.log", child.name)
                if m:
                    dates["log"].add(m.group(1))
                    dates["all"].add(m.group(1))
    return dates


def _select_date(dates: Dict[str, set]) -> Optional[str]:
    inter = dates["raw"] & dates["agg"] & dates["report"] & dates["log"]
    if inter:
        return sorted(inter)[-1]
    if dates["all"]:
        return sorted(dates["all"])[-1]
    return None


def _find_raw_file_for_item(raw_dir: Path, org: str) -> Optional[Path]:
    # Expect pattern: <org>_<topic_slug>_search.json (topic_slug is not strictly defined here)
    pattern = re.compile(rf"^{re.escape(org)}_.+_search\.json$")
    candidates = []
    if raw_dir.exists():
        for p in raw_dir.iterdir():
            if p.is_file() and pattern.fullmatch(p.name):
                candidates.append(p)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        candidates.sort(key=lambda x: len(x.name))
        return candidates[0]
    return None


def _validate_result_item(item: dict) -> bool:
    keys = ["title", "snippet", "url", "retrieved_at", "org", "topic", "domain"]
    for k in keys:
        if k not in item:
            return False
    if not isinstance(item["title"], str):
        return False
    if not isinstance(item["snippet"], str):
        return False
    if not isinstance(item["url"], str):
        return False
    if not isinstance(item["org"], str) or not isinstance(item["topic"], str) or not isinstance(item["domain"], str):
        return False
    if not _parse_iso_datetime(item["retrieved_at"]):
        return False
    return True


def _compute_metrics_from_raw(raw_items: List[dict]) -> Dict[str, Any]:
    total = len(raw_items)
    def contains_update(text: str) -> bool:
        if not isinstance(text, str):
            return False
        tl = text.lower()
        for kw in ["update", "amendment", "revision", "new", "release"]:
            if kw in tl:
                return True
        return False
    update_hits = 0
    years = []
    year_re = re.compile(r"\b(20\d{2})\b")
    for it in raw_items:
        t = it.get("title", "")
        s = it.get("snippet", "")
        if contains_update(t) or contains_update(s):
            update_hits += 1
        for part in (t, s):
            for m in year_re.finditer(part):
                try:
                    y = int(m.group(1))
                except Exception:
                    continue
                if 2000 <= y <= 2099:
                    years.append(y)
    latest_year = max(years) if years else None
    percent = round(update_hits / max(total, 1), 2)
    return {
        "total_results": total,
        "update_keyword_hits": update_hits,
        "percent_update_mentions": percent,
        "latest_year": latest_year,
    }


def _read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _extract_section(text: str, header: str, next_header: Optional[str] = None) -> str:
    lines = text.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if header.lower() in ln.lower():
            start_idx = i
            break
    if start_idx is None:
        return ""
    if next_header is None:
        return "\n".join(lines[start_idx + 1:])
    for j in range(start_idx + 1, len(lines)):
        if next_header.lower() in lines[j].lower():
            return "\n".join(lines[start_idx + 1:j])
    return "\n".join(lines[start_idx + 1:])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cron_schedule_correct_and_invokes_script": 0.0,
        "script_references_inputs": 0.0,
        "outputs_date_consistent": 0.0,
        "raw_snapshots_structure": 0.0,
        "aggregates_consistent_with_raw": 0.0,
        "report_sections_and_content": 0.0,
        "logs_include_counts": 0.0,
    }

    # Load inputs (used as gates, not scored individually)
    watchlist_path = workspace / "input" / "watchlist.yaml"
    baseline_path = workspace / "input" / "baseline.json"
    watch_items = _parse_watchlist_yaml(watchlist_path) or []
    baseline_map = _load_baseline_json(baseline_path) or {}

    # Cron schedule and script presence
    cron_path = workspace / "schedule" / "discipline_watch.cron"
    cron_ok = False
    script_path: Optional[Path] = None
    if cron_path.exists():
        cron_text = _safe_read_text(cron_path) or ""
        lines = [ln for ln in cron_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if len(lines) == 1:
            parts = lines[0].strip().split()
            if len(parts) >= 6:
                # Strict: every Monday at 07:00 local time
                if parts[0] == "0" and parts[1] == "7" and parts[2] == "*" and parts[3] == "*" and parts[4] == "1":
                    cron_ok = True
                # Extract command to locate script
                cmd = " ".join(parts[5:])
                try:
                    tokens = shlex.split(cmd)
                except Exception:
                    tokens = parts[5:]
                for tok in tokens:
                    if tok in ("python", "python3", "bash", "sh", "/bin/bash", "/usr/bin/env"):
                        continue
                    cand = Path(tok)
                    if not cand.is_absolute():
                        cand = workspace / tok
                    if cand.exists() and cand.is_file():
                        script_path = cand
                        break
    if cron_ok and script_path is not None:
        scores["cron_schedule_correct_and_invokes_script"] = 1.0

    # Script references inputs explicitly
    if script_path is not None:
        script_text = _safe_read_text(script_path) or ""
        if ("input/watchlist.yaml" in script_text) and ("input/baseline.json" in script_text):
            scores["script_references_inputs"] = 1.0

    # Determine which date to validate
    date_sets = _collect_dates(workspace)
    selected_date = _select_date(date_sets)
    if selected_date and (selected_date in date_sets["raw"]) and (selected_date in date_sets["agg"]) and (selected_date in date_sets["report"]) and (selected_date in date_sets["log"]):
        scores["outputs_date_consistent"] = 1.0

    # Validate raw snapshots and compute metrics
    raw_valid = True
    computed_metrics: Dict[tuple, Dict[str, Any]] = {}
    if selected_date and watch_items:
        raw_day_dir = workspace / "data" / "raw" / selected_date
        if not raw_day_dir.exists():
            raw_valid = False
        else:
            for wi in watch_items:
                org = wi.get("org", "")
                topic = wi.get("topic", "")
                domain = wi.get("domain", "")
                fpath = _find_raw_file_for_item(raw_day_dir, org)
                if fpath is None:
                    raw_valid = False
                    break
                data = _safe_load_json(fpath)
                if not isinstance(data, list):
                    raw_valid = False
                    break
                if len(data) > 5:
                    raw_valid = False
                    break
                if len(data) > 0:
                    for it in data:
                        if not isinstance(it, dict) or not _validate_result_item(it):
                            raw_valid = False
                            break
                        if it.get("org") != org or it.get("topic") != topic or it.get("domain") != domain:
                            raw_valid = False
                            break
                    if not raw_valid:
                        break
                metrics = _compute_metrics_from_raw(data)
                computed_metrics[(org, topic)] = metrics
    else:
        raw_valid = False
    if raw_valid:
        scores["raw_snapshots_structure"] = 1.0

    # Validate aggregates CSV
    agg_ok = False
    if selected_date and watch_items and computed_metrics and baseline_map:
        agg_csv = workspace / "data" / "aggregates" / selected_date / "watch_stats.csv"
        rows = _read_csv(agg_csv) if agg_csv.exists() else None
        if rows is not None:
            expected_columns = ["org", "topic", "total_results", "update_keyword_hits", "percent_update_mentions", "latest_year", "baseline_year", "status"]
            try:
                with agg_csv.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f)
                    header = next(reader)
            except Exception:
                header = []
            if header == expected_columns and len(rows) == len(watch_items):
                consistent = True
                seen = set()
                for row in rows:
                    org = row.get("org", "")
                    topic = row.get("topic", "")
                    key = (org, topic)
                    if key in seen:
                        consistent = False
                        break
                    seen.add(key)
                    exp = computed_metrics.get(key)
                    if exp is None:
                        consistent = False
                        break
                    try:
                        total_csv = int(row.get("total_results", ""))
                        upd_csv = int(row.get("update_keyword_hits", ""))
                        pct_csv = row.get("percent_update_mentions", "")
                        ly_raw = (row.get("latest_year", "") or "").strip().lower()
                        latest_csv = None if ly_raw in ("", "null", "none") else int(row.get("latest_year", ""))
                        baseline_csv = int(row.get("baseline_year", ""))
                        status_csv = row.get("status", "")
                    except Exception:
                        consistent = False
                        break
                    if total_csv != exp["total_results"]:
                        consistent = False
                        break
                    if upd_csv != exp["update_keyword_hits"]:
                        consistent = False
                        break
                    if pct_csv != f"{exp['percent_update_mentions']:.2f}":
                        consistent = False
                        break
                    if exp["latest_year"] is None:
                        if latest_csv is not None:
                            consistent = False
                            break
                    else:
                        if latest_csv != exp["latest_year"]:
                            consistent = False
                            break
                    # Baseline lookup and status
                    baseline_key = None
                    for wi in watch_items:
                        if wi.get("org") == org and wi.get("topic") == topic:
                            baseline_key = wi.get("baseline_key")
                            break
                    if baseline_key is None or baseline_key not in baseline_map:
                        consistent = False
                        break
                    by = baseline_map[baseline_key]["baseline_year"]
                    if baseline_csv != by:
                        consistent = False
                        break
                    exp_status = "ahead" if (isinstance(exp["latest_year"], int) and exp["latest_year"] > by) else "same_or_behind"
                    if status_csv != exp_status:
                        consistent = False
                        break
                agg_ok = consistent
    if agg_ok:
        scores["aggregates_consistent_with_raw"] = 1.0

    # Validate report markdown
    report_ok = False
    if selected_date and watch_items and computed_metrics:
        report_path = workspace / "reports" / f"weekly_discipline_watch_{selected_date}.md"
        report_text = _safe_read_text(report_path)
        if report_text is not None:
            lines = report_text.splitlines()
            expected_title = f"Weekly Rule & Discipline Watch — {selected_date}"
            title_ok = bool(lines) and (lines[0].strip() == expected_title)
            # Each watch item appears with metrics values somewhere
            items_ok = True
            for wi in watch_items:
                org = wi.get("org", "")
                topic = wi.get("topic", "")
                key = (org, topic)
                m = computed_metrics.get(key, {})
                total_str = str(m.get("total_results", ""))
                upd_str = str(m.get("update_keyword_hits", ""))
                pct_str = f"{m.get('percent_update_mentions', 0):.2f}"
                if (org not in report_text) or (topic not in report_text) or (total_str not in report_text) or (upd_str not in report_text) or (pct_str not in report_text):
                    items_ok = False
                    break
            # Potential Updates to Review section present and mentions flagged items
            pur_section = _extract_section(report_text, "Potential Updates to Review", next_header=None)
            pur_ok = bool(pur_section)
            if pur_ok:
                flagged = []
                for wi in watch_items:
                    org = wi["org"]
                    topic = wi["topic"]
                    key = (org, topic)
                    m = computed_metrics.get(key, {})
                    baseline_key = wi.get("baseline_key")
                    by = None
                    if isinstance(baseline_key, str) and baseline_key in baseline_map:
                        by = baseline_map[baseline_key]["baseline_year"]
                    latest = m.get("latest_year")
                    status = "ahead" if (isinstance(latest, int) and isinstance(by, int) and latest > by) else "same_or_behind"
                    pct = m.get("percent_update_mentions", 0.0)
                    if status == "ahead" or pct >= 0.40:
                        flagged.append((org, topic))
                for org, topic in flagged:
                    if (org not in pur_section) and (topic not in pur_section):
                        pur_ok = False
                        break
            # Appendix: ensure every captured result title and URL appear somewhere in report
            appendix_ok = True
            raw_day_dir = workspace / "data" / "raw" / selected_date
            for wi in watch_items:
                org = wi["org"]
                fpath = _find_raw_file_for_item(raw_day_dir, org)
                if fpath is None:
                    appendix_ok = False
                    break
                data = _safe_load_json(fpath)
                if not isinstance(data, list):
                    appendix_ok = False
                    break
                for it in data:
                    if not isinstance(it, dict):
                        appendix_ok = False
                        break
                    title = it.get("title", "")
                    url = it.get("url", "")
                    if title and title not in report_text:
                        appendix_ok = False
                        break
                    if url and url not in report_text:
                        appendix_ok = False
                        break
                if not appendix_ok:
                    break
            report_ok = title_ok and items_ok and pur_ok and appendix_ok
    if report_ok:
        scores["report_sections_and_content"] = 1.0

    # Validate logs include start/end and counts per watch item
    logs_ok = False
    if selected_date and watch_items and computed_metrics:
        log_path = workspace / "logs" / f"discipline_watch_{selected_date}.log"
        log_text = _safe_read_text(log_path)
        if log_text is not None:
            lt = log_text.lower()
            has_start = "start" in lt
            has_end = "end" in lt
            counts_ok = True
            lines = log_text.splitlines()
            for wi in watch_items:
                org = wi.get("org", "")
                topic = wi.get("topic", "")
                exp_total = computed_metrics.get((org, topic), {}).get("total_results")
                if exp_total is None:
                    counts_ok = False
                    break
                found = False
                for ln in lines:
                    if org in ln and topic in ln and re.search(r"\d+", ln):
                        nums = [int(x) for x in re.findall(r"\d+", ln)]
                        if any(n == exp_total for n in nums):
                            found = True
                            break
                if not found:
                    counts_ok = False
                    break
            logs_ok = has_start and has_end and counts_ok
    if logs_ok:
        scores["logs_include_counts"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()