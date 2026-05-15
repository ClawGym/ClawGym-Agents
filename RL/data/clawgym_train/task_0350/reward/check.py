import json
import csv
import sys
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except Exception as e:
        return None, str(e)


def _safe_load_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows, None
    except Exception as e:
        return None, str(e)


def _is_iso_datetime(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def _extract_queries_list(obj: Any) -> List[str]:
    queries: List[str] = []
    if isinstance(obj, dict):
        if "queries" in obj:
            return _extract_queries_list(obj["queries"])
        try:
            for v in obj.values():
                queries.extend(_extract_queries_list(v))
        except Exception:
            pass
        if "query" in obj and isinstance(obj["query"], str):
            queries.append(obj["query"])
        return queries
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, str):
                queries.append(item)
            elif isinstance(item, dict) and isinstance(item.get("query"), str):
                queries.append(item["query"])
    return queries


def _official_fiji_domain(netloc: str) -> bool:
    d = (netloc or "").lower()
    return (
        d == "parliament.gov.fj"
        or d.endswith(".parliament.gov.fj")
        or d == "gov.fj"
        or d.endswith(".gov.fj")
    )


def _normalize_netloc_from_url(url: str) -> Optional[str]:
    try:
        p = urlparse(url)
        if not p.scheme or not p.netloc:
            return None
        return p.netloc.lower()
    except Exception:
        return None


def _read_participants_by_role(path: Path) -> Dict[str, List[str]]:
    participants_by_role: Dict[str, List[str]] = {}
    rows, _ = _safe_load_csv(path)
    if rows is None:
        return participants_by_role
    for r in rows:
        name = (r.get("name") or "").strip()
        role = (r.get("role") or "").strip()
        if not name or not role:
            continue
        participants_by_role.setdefault(role, []).append(name)
    return participants_by_role


def _find_lines_containing(text: str, substrings: List[str]) -> List[str]:
    lines = text.splitlines()
    hits: List[str] = []
    for line in lines:
        if all(sub.lower() in line.lower() for sub in substrings):
            hits.append(line)
    return hits


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_exists_at_path": 0.0,
        "script_references_curl": 0.0,
        "queries_log_json_valid": 0.0,
        "queries_cover_filters_per_topic": 0.0,
        "results_json_valid_and_official_domains": 0.0,
        "results_queries_match_log": 0.0,
        "downloads_report_valid": 0.0,
        "downloads_urls_from_results": 0.0,
        "errors_log_matches_failures": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_lists_downloads": 0.0,
        "meeting_notes_issues_summarized": 0.0,
        "action_items_present_per_download": 0.0,
        "action_items_assigned_to_roles": 0.0,
    }

    # Inputs
    topics_path = workspace / "input" / "topics.json"
    participants_path = workspace / "input" / "participants.csv"
    topics_data, _ = _safe_load_json(topics_path)
    topics_list: List[Dict[str, Any]] = []
    if isinstance(topics_data, dict) and isinstance(topics_data.get("topics"), list):
        for t in topics_data["topics"]:
            if isinstance(t, dict) and "name" in t:
                topics_list.append(t)

    participants_by_role = _read_participants_by_role(participants_path)

    # Deliverable script checks
    script_path = workspace / "scripts" / "fiji_civic_fetcher.py"
    if script_path.exists() and script_path.is_file():
        scores["script_exists_at_path"] = 1.0
        script_text = _safe_read_text(script_path) or ""
        if "curl" in script_text:
            scores["script_references_curl"] = 1.0

    # Output paths
    queries_log_path = workspace / "output" / "search" / "queries_log.json"
    results_json_path = workspace / "output" / "search" / "results.json"
    downloads_dir = workspace / "output" / "downloads"
    downloads_report_path = workspace / "output" / "downloads_report.json"
    errors_log_path = workspace / "output" / "errors.log"
    meeting_notes_path = workspace / "output" / "meeting_notes.md"

    # Load queries log
    queries_log, _ = _safe_load_json(queries_log_path)
    queries_list: List[str] = []
    if queries_log is not None:
        queries_list = _extract_queries_list(queries_log)
    # Validate queries_log
    ql_valid = (
        queries_log is not None
        and isinstance(queries_list, list)
        and len(queries_list) >= max(0, 2 * len(topics_list))
    )
    if ql_valid:
        scores["queries_log_json_valid"] = 1.0

    # Check coverage of site filters per topic
    cover_ok = True
    if not topics_list or not queries_list:
        cover_ok = False
    else:
        lower_queries = [q.lower() for q in queries_list]
        for t in topics_list:
            name = (t.get("name") or "").strip().lower()
            if not name:
                cover_ok = False
                break
            has_gov = any(name in q and ("site:gov.fj" in q or "site:.gov.fj" in q or ".gov.fj" in q) for q in lower_queries)
            has_parl = any(name in q and ("site:parliament.gov.fj" in q) for q in lower_queries)
            if not (has_gov and has_parl):
                cover_ok = False
                break
    if cover_ok:
        scores["queries_cover_filters_per_topic"] = 1.0

    # Load results
    results_data, _ = _safe_load_json(results_json_path)
    results_list: List[Dict[str, Any]] = []
    if isinstance(results_data, list):
        for item in results_data:
            if isinstance(item, dict):
                results_list.append(item)
    elif isinstance(results_data, dict):
        if isinstance(results_data.get("results"), list):
            for item in results_data["results"]:
                if isinstance(item, dict):
                    results_list.append(item)

    # Validate results schema and domains
    results_valid = True
    titles_by_url: Dict[str, str] = {}
    if results_list:
        for item in results_list:
            if not all(k in item for k in ("query", "url", "source_domain", "result_rank", "fetched_at")):
                results_valid = False
                break
            if not isinstance(item.get("query"), str):
                results_valid = False
                break
            url = item.get("url")
            if not isinstance(url, str) or not url:
                results_valid = False
                break
            netloc = _normalize_netloc_from_url(url)
            if not netloc:
                results_valid = False
                break
            src_dom = item.get("source_domain")
            if not isinstance(src_dom, str) or src_dom.lower() != netloc:
                results_valid = False
                break
            if not _official_fiji_domain(netloc):
                results_valid = False
                break
            try:
                rank = int(item.get("result_rank"))
                if rank < 1:
                    results_valid = False
                    break
            except Exception:
                results_valid = False
                break
            if not _is_iso_datetime(str(item.get("fetched_at"))):
                results_valid = False
                break
            title_val = item.get("title")
            if isinstance(title_val, str) and title_val.strip():
                titles_by_url[url] = title_val.strip()
    else:
        results_valid = False

    if results_valid:
        scores["results_json_valid_and_official_domains"] = 1.0

    # Check that result queries match queries log
    if ql_valid and results_valid:
        queries_set = set(queries_list)
        res_queries_match = all(isinstance(it.get("query"), str) and it["query"] in queries_set for it in results_list)
        if res_queries_match:
            scores["results_queries_match_log"] = 1.0

    # Load downloads report
    downloads_data, _ = _safe_load_json(downloads_report_path)
    downloads_list: Optional[List[Dict[str, Any]]] = None
    if isinstance(downloads_data, list):
        downloads_list = [d for d in downloads_data if isinstance(d, dict)]
    elif isinstance(downloads_data, dict) and isinstance(downloads_data.get("downloads"), list):
        downloads_list = [d for d in downloads_data["downloads"] if isinstance(d, dict)]

    # Validate downloads report entries
    downloads_valid = True
    success_entries: List[Dict[str, Any]] = []
    failure_entries: List[Dict[str, Any]] = []
    if downloads_list is None or len(downloads_list) == 0:
        downloads_valid = False
    else:
        for entry in downloads_list:
            required = ["topic", "url", "saved_path", "exit_code", "stderr_excerpt", "bytes_downloaded"]
            if not all(k in entry for k in required):
                downloads_valid = False
                break
            if not isinstance(entry.get("topic"), str) or not entry["topic"]:
                downloads_valid = False
                break
            durl = entry.get("url")
            if not isinstance(durl, str) or not durl:
                downloads_valid = False
                break
            if not _normalize_netloc_from_url(durl):
                downloads_valid = False
                break
            try:
                exit_code = int(entry.get("exit_code"))
            except Exception:
                downloads_valid = False
                break
            try:
                bytes_dl = int(entry.get("bytes_downloaded"))
                if bytes_dl < 0:
                    downloads_valid = False
                    break
            except Exception:
                downloads_valid = False
                break
            if not isinstance(entry.get("stderr_excerpt"), str):
                downloads_valid = False
                break
            sp = entry.get("saved_path")
            if exit_code == 0:
                if not isinstance(sp, str) or not sp:
                    downloads_valid = False
                    break
                sp_path = (workspace / sp) if not Path(sp).is_absolute() else Path(sp)
                try:
                    sp_path_resolved = sp_path.resolve()
                except Exception:
                    sp_path_resolved = sp_path
                try:
                    downloads_dir_resolved = downloads_dir.resolve()
                except Exception:
                    downloads_dir_resolved = downloads_dir
                if not str(sp_path_resolved).startswith(str(downloads_dir_resolved)):
                    downloads_valid = False
                    break
                if not sp_path_resolved.exists() or not sp_path_resolved.is_file():
                    downloads_valid = False
                    break
                try:
                    actual_size = sp_path_resolved.stat().st_size
                except Exception:
                    downloads_valid = False
                    break
                if actual_size != bytes_dl:
                    downloads_valid = False
                    break
                success_entries.append(entry)
            else:
                if sp is not None:
                    downloads_valid = False
                    break
                if bytes_dl != 0:
                    downloads_valid = False
                    break
                failure_entries.append(entry)

    if downloads_valid:
        scores["downloads_report_valid"] = 1.0

    # Check that all downloads came from results URLs
    if downloads_valid and results_valid:
        results_urls_set = {it.get("url") for it in results_list if isinstance(it.get("url"), str)}
        from_results_ok = all(isinstance(e.get("url"), str) and e["url"] in results_urls_set for e in downloads_list or [])
        if from_results_ok:
            scores["downloads_urls_from_results"] = 1.0

    # Errors log validation against failures
    errors_log_text = _safe_read_text(errors_log_path)
    if downloads_valid:
        if failure_entries:
            if errors_log_text is not None and errors_log_text.strip():
                match_all_codes = True
                for fe in failure_entries:
                    try:
                        code = int(fe.get("exit_code"))
                    except Exception:
                        match_all_codes = False
                        break
                    if str(code) not in errors_log_text:
                        match_all_codes = False
                        break
                if match_all_codes:
                    scores["errors_log_matches_failures"] = 1.0
        else:
            if errors_log_text is not None:
                scores["errors_log_matches_failures"] = 1.0

    # Meeting notes sections present
    mn_text = _safe_read_text(meeting_notes_path)
    if mn_text is not None:
        required_sections = ["Summary", "Findings per topic", "Issues encountered", "Action items"]
        if all(sec.lower() in mn_text.lower() for sec in required_sections):
            scores["meeting_notes_sections_present"] = 1.0

    # Meeting notes list downloads and titles
    if mn_text is not None and downloads_valid:
        if success_entries:
            all_ok = True
            for se in success_entries:
                sp = se.get("saved_path")
                bn = Path(sp).name if isinstance(sp, str) else ""
                if bn and bn.lower() not in mn_text.lower():
                    all_ok = False
                    break
                url = se.get("url")
                title = titles_by_url.get(url)
                if title and title.strip():
                    if title.lower() not in mn_text.lower():
                        all_ok = False
                        break
            if all_ok:
                scores["meeting_notes_lists_downloads"] = 1.0
        else:
            scores["meeting_notes_lists_downloads"] = 1.0

    # Meeting notes issues summarized
    if mn_text is not None and downloads_valid:
        fail_count = len(failure_entries)
        if fail_count > 0:
            has_count = str(fail_count) in mn_text
            mentions_errors_log = "errors.log" in mn_text.lower()
            if has_count and mentions_errors_log:
                scores["meeting_notes_issues_summarized"] = 1.0
        else:
            scores["meeting_notes_issues_summarized"] = 1.0

    # Action items presence per download and assignments
    if mn_text is not None and downloads_valid:
        successes = success_entries
        expected_lines: List[Tuple[str, str, str]] = []
        for se in successes:
            topic = se.get("topic") or ""
            sp = se.get("saved_path")
            filename = Path(sp).name if isinstance(sp, str) else ""
            expected_lines.append(("Data", f"Extract key facts from {filename} for {topic}.", topic))
            expected_lines.append(("Comms", f"Draft a 3-sentence plain-language summary for {topic}.", topic))
            expected_lines.append(("Outreach", f"Identify one youth group or community contact to brief on {topic}.", topic))
        if successes:
            present_ok = True
            present_lines: List[Tuple[str, str]] = []
            for role, phrase, _tp in expected_lines:
                hits = _find_lines_containing(mn_text, [phrase])
                if not hits:
                    present_ok = False
                    break
                else:
                    present_lines.append((role, hits[0]))
            if present_ok:
                scores["action_items_present_per_download"] = 1.0
            assigned_ok = True
            if present_ok:
                for role, line in present_lines:
                    role_names = participants_by_role.get(role, [])
                    if role_names:
                        if not any(name in line for name in role_names):
                            assigned_ok = False
                            break
                    else:
                        if "unassigned" not in line.lower():
                            assigned_ok = False
                            break
            if present_ok and assigned_ok:
                scores["action_items_assigned_to_roles"] = 1.0
        else:
            scores["action_items_present_per_download"] = 1.0
            scores["action_items_assigned_to_roles"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()