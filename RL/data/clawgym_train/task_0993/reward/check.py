import json
import re
import sys
import hashlib
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_neighbors_yaml(text: str) -> Tuple[Optional[List[str]], Optional[Dict[str, str]]]:
    neighbors = None
    aliases = None
    mode = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if not line.startswith(" ") and line.endswith(":"):
            key = line.strip().rstrip(":")
            if key == "neighbors":
                mode = "neighbors"
                neighbors = []
            elif key == "aliases":
                mode = "aliases"
                aliases = {}
            else:
                mode = None
            continue
        if mode == "neighbors":
            m = re.match(r"\s*-\s+(.*)$", line)
            if m:
                item = m.group(1).strip()
                if item.startswith('"') and item.endswith('"') and len(item) >= 2:
                    item = item[1:-1]
                neighbors.append(item)
        elif mode == "aliases":
            m = re.match(r"\s*([^:]+):\s*(.*)$", line)
            if m:
                k = m.group(1).strip()
                v = m.group(2).strip()
                if v.startswith('"') and v.endswith('"') and len(v) >= 2:
                    v = v[1:-1]
                aliases[k] = v
    return neighbors, aliases


def _parse_recipients_yaml(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    result = {
        "from_name": None,
        "from_email": None,
        "to_emails": [],
        "cc_emails": [],
    }
    section = None
    current_item = None
    list_context = None
    indent_level = None
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        top_m = re.match(r"^([a-zA-Z_]+):\s*(.*)$", line)
        if top_m and not line.startswith(" "):
            key = top_m.group(1)
            val = top_m.group(2).strip()
            section = key
            list_context = None
            current_item = None
            indent_level = None
            if key in ("from_name", "from_email"):
                if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                    val = val[1:-1]
                result[key] = val
            elif key in ("to", "cc"):
                list_context = key
            continue
        if list_context in ("to", "cc"):
            m_item = re.match(r"^(\s*)-\s+(.*)$", line)
            if m_item:
                indent_level = len(m_item.group(1))
                content = m_item.group(2).strip()
                current_item = {}
                kv = re.match(r"^([^:]+):\s*(.*)$", content)
                if kv:
                    k = kv.group(1).strip()
                    v = kv.group(2).strip()
                    if v.startswith('"') and v.endswith('"') and len(v) >= 2:
                        v = v[1:-1]
                    current_item[k] = v
                if "email" in current_item:
                    if list_context == "to":
                        result["to_emails"].append(current_item["email"])
                    else:
                        result["cc_emails"].append(current_item["email"])
                continue
            if current_item is not None:
                if indent_level is None:
                    indent_level = 2
                m_cont = re.match(r"^\s{"+str(indent_level+2)+r",}([^:]+):\s*(.*)$", line)
                if m_cont:
                    k = m_cont.group(1).strip()
                    v = m_cont.group(2).strip()
                    if v.startswith('"') and v.endswith('"') and len(v) >= 2:
                        v = v[1:-1]
                    current_item[k] = v
                    if k == "email":
                        if list_context == "to":
                            result["to_emails"].append(current_item["email"])
                        else:
                            result["cc_emails"].append(current_item["email"])
                else:
                    m_cont2 = re.match(r"^\s+([^:]+):\s*(.*)$", line)
                    if m_cont2:
                        k = m_cont2.group(1).strip()
                        v = m_cont2.group(2).strip()
                        if v.startswith('"') and v.endswith('"') and len(v) >= 2:
                            v = v[1:-1]
                        current_item[k] = v
                        if k == "email":
                            if list_context == "to":
                                result["to_emails"].append(current_item["email"])
                            else:
                                result["cc_emails"].append(current_item["email"])
    return result


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _list_update_files(updates_dir: Path) -> List[Path]:
    if not updates_dir.is_dir():
        return []
    files = [p for p in updates_dir.iterdir() if p.is_file() and p.suffix == ".txt"]
    files.sort(key=lambda p: p.name)
    return files


def _parse_update_line(line: str) -> Optional[Tuple[date, str, str, str]]:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != 4:
        return None
    date_s, country, headline, source = parts
    if not date_s or not country or not headline or not source:
        return None
    try:
        d = datetime.strptime(date_s, "%Y-%m-%d").date()
    except Exception:
        return None
    return d, country, headline, source


def _collect_updates(workspace: Path, neighbors: List[str], aliases: Dict[str, str]) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, int]]]:
    updates_dir = workspace / "input" / "daily_updates"
    files = _list_update_files(updates_dir)
    all_updates: List[Dict[str, Any]] = []
    per_file_counts: Dict[str, Dict[str, int]] = {}
    neighbors_set = set(neighbors or [])
    for f in files:
        rel = f.relative_to(workspace).as_posix()
        text = _read_text_safe(f)
        valid = 0
        skipped = 0
        if text is None:
            per_file_counts[rel] = {"valid": 0, "skipped": 0, "processed": 0}
            continue
        processed = 0
        for raw in text.splitlines():
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            processed += 1
            parsed = _parse_update_line(raw.strip("\n"))
            if not parsed:
                skipped += 1
                continue
            d, country, headline, source = parsed
            if aliases and country in aliases:
                country_norm = aliases[country]
            else:
                country_norm = country
            if country_norm not in neighbors_set:
                skipped += 1
                continue
            valid += 1
            all_updates.append({
                "file": rel,
                "is_alert": Path(rel).name.startswith("ALERT_"),
                "date": d,
                "date_s": d.strftime("%Y-%m-%d"),
                "country": country_norm,
                "headline": headline,
                "source": source,
            })
        per_file_counts[rel] = {"valid": valid, "skipped": skipped, "processed": processed}
    return all_updates, per_file_counts


def _compute_window(valid_updates: List[Dict[str, Any]]) -> Optional[Tuple[date, date]]:
    if not valid_updates:
        return None
    max_d = max(u["date"] for u in valid_updates)
    start = max_d - timedelta(days=6)
    return start, max_d


def _filter_updates_in_window(valid_updates: List[Dict[str, Any]], window: Tuple[date, date]) -> List[Dict[str, Any]]:
    start, end = window
    return [u for u in valid_updates if start <= u["date"] <= end]


def _run_validator(workspace: Path) -> Optional[str]:
    script = workspace / "input" / "scripts" / "validate_updates.py"
    updates_dir = workspace / "input" / "daily_updates"
    if not script.is_file() or not updates_dir.is_dir():
        return None
    try:
        result = subprocess.run(
            ["python3", str(script.relative_to(workspace)), str(updates_dir.relative_to(workspace))],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        combined = result.stdout + (result.stderr or "")
        return combined
    except Exception:
        return None


def _extract_window_from_text(text: str) -> Optional[Tuple[date, date]]:
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", text)
    if not m:
        return None
    try:
        s = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        e = datetime.strptime(m.group(2), "%Y-%m-%d").date()
        return s, e
    except Exception:
        return None


def _find_country_sections(markdown: str, countries: List[str]) -> Dict[str, List[str]]:
    lines = markdown.splitlines()
    known = set(countries)
    bullets_by_country: Dict[str, List[str]] = {c: [] for c in countries}
    current_country: Optional[str] = None
    for raw in lines:
        line = raw.strip("\n")
        lstripped = line.lstrip("#").strip()
        if lstripped.rstrip(":") in known:
            current_country = lstripped.rstrip(":")
            continue
        if line.startswith("#") and lstripped.rstrip(":") not in known:
            current_country = None
        if current_country and line.strip().startswith("- "):
            bullets_by_country[current_country].append(line.strip())
    bullets_by_country = {k: v for k, v in bullets_by_country.items() if v}
    return bullets_by_country


def _count_country_updates(updates: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for u in updates:
        counts[u["country"]] = counts.get(u["country"], 0) + 1
    return counts


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "weekly_summary_exists": 0.0,
        "weekly_summary_header_window_correct": 0.0,
        "weekly_summary_country_items_correct": 0.0,
        "weekly_summary_ordering_per_country": 0.0,
        "weekly_summary_diagnostics_included": 0.0,
        "weekly_summary_excludes_malformed": 0.0,
        "draft_email_exists": 0.0,
        "draft_email_headers_recipients_correct": 0.0,
        "draft_email_subject_window_correct": 0.0,
        "draft_email_summary_counts_correct": 0.0,
        "draft_email_country_breakdown_correct": 0.0,
        "draft_email_urgent_alerts_section_correct": 0.0,
        "draft_email_references_report": 0.0,
        "automation_log_exists": 0.0,
        "automation_log_entries_per_file_counts_correct": 0.0,
        "state_json_exists": 0.0,
        "state_json_hashes_and_window_correct": 0.0,
    }

    neighbors_yaml = workspace / "input" / "config" / "neighbors.yaml"
    recipients_yaml = workspace / "input" / "recipients.yaml"
    neighbors_list: Optional[List[str]] = None
    aliases: Optional[Dict[str, str]] = None
    neighbors_text = _read_text_safe(neighbors_yaml)
    if neighbors_text is not None:
        neighbors_list, aliases = _parse_simple_neighbors_yaml(neighbors_text)
    if neighbors_list is None:
        neighbors_list = []
    if aliases is None:
        aliases = {}

    updates, per_file_counts = _collect_updates(workspace, neighbors_list, aliases)
    window = _compute_window(updates)
    updates_in_window = _filter_updates_in_window(updates, window) if window else []
    countries_in_window = sorted({u["country"] for u in updates_in_window})
    counts_by_country_window = _count_country_updates(updates_in_window)
    total_valid_in_window = len(updates_in_window)
    alert_updates_in_window = [u for u in updates_in_window if u["is_alert"]]

    summary_path = workspace / "output" / "weekly_summary.md"
    summary_text = _read_text_safe(summary_path)
    if summary_text is not None:
        scores["weekly_summary_exists"] = 1.0
        if window:
            mwin = _extract_window_from_text(summary_text)
            if mwin and mwin[0] == window[0] and mwin[1] == window[1]:
                scores["weekly_summary_header_window_correct"] = 1.0
        all_present = True
        for u in updates_in_window:
            bullet = f"- {u['date_s']}: {u['headline']} ({u['source']})"
            if bullet not in summary_text:
                all_present = False
                break
        if total_valid_in_window > 0 and all_present:
            scores["weekly_summary_country_items_correct"] = 1.0
        if countries_in_window:
            sections = _find_country_sections(summary_text, countries_in_window)
            ordered_ok = True
            assessed_any = False
            for country in countries_in_window:
                if country in sections:
                    assessed_any = True
                    dates_in_section = []
                    for line in sections[country]:
                        m = re.match(r"-\s+(\d{4}-\d{2}-\d{2}):\s+.*\(.+\)\s*$", line)
                        if m:
                            dates_in_section.append(m.group(1))
                    if dates_in_section != sorted(dates_in_section):
                        ordered_ok = False
                        break
                    for u in [x for x in updates_in_window if x["country"] == country]:
                        bullet = f"- {u['date_s']}: {u['headline']} ({u['source']})"
                        if bullet not in sections[country]:
                            ordered_ok = False
                            break
                    if not ordered_ok:
                        break
            if assessed_any and ordered_ok:
                scores["weekly_summary_ordering_per_country"] = 1.0
        validator_out = _run_validator(workspace)
        if validator_out is not None:
            if ("Diagnostics" in summary_text or "diagnostics" in summary_text) and validator_out in summary_text:
                scores["weekly_summary_diagnostics_included"] = 1.0
        if "Headline with missing source" not in summary_text:
            scores["weekly_summary_excludes_malformed"] = 1.0

    email_path = workspace / "output" / "draft_email.txt"
    email_text = _read_text_safe(email_path)
    if email_text is not None:
        scores["draft_email_exists"] = 1.0
        rec_text = _read_text_safe(recipients_yaml)
        to_emails: List[str] = []
        cc_emails: List[str] = []
        if rec_text is not None:
            rec = _parse_recipients_yaml(rec_text)
            to_emails = rec.get("to_emails") or []
            cc_emails = rec.get("cc_emails") or []
        to_m = re.search(r"^To:\s*(.+)$", email_text, flags=re.MULTILINE | re.IGNORECASE)
        cc_m = re.search(r"^Cc:\s*(.+)$", email_text, flags=re.MULTILINE | re.IGNORECASE)
        headers_ok = True
        if to_emails:
            if not to_m:
                headers_ok = False
            else:
                to_line = to_m.group(1)
                for em in to_emails:
                    if em not in to_line:
                        headers_ok = False
                        break
        if cc_emails and headers_ok:
            if not cc_m:
                headers_ok = False
            else:
                cc_line = cc_m.group(1)
                for em in cc_emails:
                    if em not in cc_line:
                        headers_ok = False
                        break
        if headers_ok and (to_emails or cc_emails):
            scores["draft_email_headers_recipients_correct"] = 1.0
        subj_m = re.search(r"^Subject:\s*(.+)$", email_text, flags=re.MULTILINE | re.IGNORECASE)
        if subj_m and window:
            subj = subj_m.group(1)
            ew_s = window[0].strftime("%Y-%m-%d")
            ew_e = window[1].strftime("%Y-%m-%d")
            if re.search(r"weekly neighbors round-up", subj, flags=re.IGNORECASE) and f"{ew_s} to {ew_e}" in subj:
                scores["draft_email_subject_window_correct"] = 1.0
        if window:
            numbers_ok = True
            body = email_text
            if re.search(rf"\b{total_valid_in_window}\b", body) is None:
                numbers_ok = False
            if re.search(rf"\b{len(countries_in_window)}\b", body) is None:
                numbers_ok = False
            if numbers_ok:
                scores["draft_email_summary_counts_correct"] = 1.0
        breakdown_ok = True
        if window and countries_in_window:
            for c in countries_in_window:
                n = counts_by_country_window.get(c, 0)
                pattern = rf"^{re.escape(c)}:\s+{n}\s+updates\s*$"
                if re.search(pattern, email_text, flags=re.MULTILINE) is None:
                    breakdown_ok = False
                    break
            if breakdown_ok:
                scores["draft_email_country_breakdown_correct"] = 1.0
        if alert_updates_in_window:
            alert_ok = True
            if re.search(r"Urgent alerts", email_text, flags=re.IGNORECASE) is None:
                alert_ok = False
            else:
                for a in alert_updates_in_window:
                    found = False
                    for line in email_text.splitlines():
                        if a["date_s"] in line and a["country"] in line and a["headline"] in line:
                            found = True
                            break
                    if not found:
                        alert_ok = False
                        break
            if alert_ok:
                scores["draft_email_urgent_alerts_section_correct"] = 1.0
        if "output/weekly_summary.md" in email_text:
            scores["draft_email_references_report"] = 1.0

    log_path = workspace / "output" / "automation.log"
    log_text = _read_text_safe(log_path)
    if log_text is not None:
        scores["automation_log_exists"] = 1.0
        entries_by_file: Dict[str, Dict[str, Any]] = {}
        for raw in log_text.splitlines():
            line = raw.strip()
            if not line:
                continue
            m = re.match(r"^([0-9T:\-\.Z\+]+)\s+\|\s+processed\s+(.+?)\s+\|\s+valid=(\d+)\s+skipped=(\d+)\s*$", line)
            if not m:
                continue
            ts_s, path_s, valid_s, skipped_s = m.groups()
            ts_ok = True
            try:
                if ts_s.endswith("Z"):
                    datetime.fromisoformat(ts_s[:-1])
                else:
                    datetime.fromisoformat(ts_s)
            except Exception:
                ts_ok = False
            norm_path = Path(path_s).as_posix()
            entries_by_file[norm_path] = {
                "timestamp_ok": ts_ok,
                "valid": int(valid_s),
                "skipped": int(skipped_s),
            }
        updates_dir = workspace / "input" / "daily_updates"
        update_files = _list_update_files(updates_dir)
        all_ok = True
        for f in update_files:
            rel = f.relative_to(workspace).as_posix()
            candidates = []
            if rel in entries_by_file:
                candidates.append(entries_by_file[rel])
            dot_rel = "./" + rel
            if dot_rel in entries_by_file:
                candidates.append(entries_by_file[dot_rel])
            if not candidates:
                for k, v in entries_by_file.items():
                    if k.endswith("/" + Path(rel).name) or k.endswith(rel):
                        candidates.append(v)
            if not candidates:
                all_ok = False
                break
            entry = candidates[-1]
            expected = per_file_counts.get(rel, {"valid": 0, "skipped": 0})
            if entry.get("valid") != expected["valid"] or entry.get("skipped") != expected["skipped"] or not entry.get("timestamp_ok"):
                all_ok = False
                break
        if update_files and all_ok:
            scores["automation_log_entries_per_file_counts_correct"] = 1.0

    state_path = workspace / "output" / "state.json"
    state_obj = None
    if state_path.is_file():
        scores["state_json_exists"] = 1.0
        try:
            state_obj = json.loads(_read_text_safe(state_path) or "")
        except Exception:
            state_obj = None
    if state_obj is not None:
        ok = True
        files_map = state_obj.get("files")
        last_window = state_obj.get("last_report_window")
        if not isinstance(files_map, dict) or not isinstance(last_window, dict):
            ok = False
        else:
            updates_dir = workspace / "input" / "daily_updates"
            update_files = _list_update_files(updates_dir)
            for f in update_files:
                rel = f.relative_to(workspace).as_posix()
                found_key = None
                if rel in files_map:
                    found_key = rel
                else:
                    dot_rel = "./" + rel
                    if dot_rel in files_map:
                        found_key = dot_rel
                    else:
                        for k in files_map.keys():
                            if isinstance(k, str) and (k.endswith("/" + Path(rel).name) or k.endswith(rel)):
                                found_key = k
                if found_key is None:
                    ok = False
                    break
                entry = files_map.get(found_key, {})
                sha = entry.get("sha256")
                lp = entry.get("last_processed")
                if not isinstance(sha, str) or len(sha) != 64 or not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
                    ok = False
                    break
                actual_sha = _sha256_file(f)
                if actual_sha is None or actual_sha.lower() != sha.lower():
                    ok = False
                    break
                try:
                    lp_s = str(lp)
                    if lp_s.endswith("Z"):
                        datetime.fromisoformat(lp_s[:-1])
                    else:
                        datetime.fromisoformat(lp_s)
                except Exception:
                    ok = False
                    break
            if ok and window:
                s = last_window.get("start")
                e = last_window.get("end")
                try:
                    s_d = datetime.strptime(s, "%Y-%m-%d").date()
                    e_d = datetime.strptime(e, "%Y-%m-%d").date()
                except Exception:
                    ok = False
                else:
                    if s_d != window[0] or e_d != window[1]:
                        ok = False
        if ok:
            scores["state_json_hashes_and_window_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()