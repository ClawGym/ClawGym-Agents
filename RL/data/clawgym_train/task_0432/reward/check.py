import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            header = reader.fieldnames
            return rows, header
    except Exception:
        return None, None


def _parse_iso(dt_str: str) -> Optional[datetime]:
    if not isinstance(dt_str, str):
        return None
    s = dt_str.strip()
    if not s:
        return None
    try:
        # Accept 'Z' for UTC by converting to +00:00
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _extract_host(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.netloc or ""
        # Strip port if present
        if ":" in host:
            host = host.split(":")[0]
        host = host.strip().lower()
        return host if host else None
    except Exception:
        return None


def _host_matches_allowed(host: str, allowed: List[str]) -> bool:
    host = (host or "").lower()
    for dom in allowed:
        dom = dom.lower()
        if host == dom or host.endswith("." + dom):
            return True
    return False


def _semicolon_split(s: str) -> List[str]:
    return [part.strip() for part in s.split(";") if part.strip()]


def _extract_section(md_text: str, title: str) -> str:
    """
    Extracts lines of a section identified by title (case-insensitive contains match),
    until the next known section heading or end of document.
    """
    if not isinstance(md_text, str):
        return ""
    lines = md_text.splitlines()
    lowered = [ln.lower() for ln in lines]
    titles = ["overview", "counts", "per-domain breakdown", "component coverage details"]
    target = title.lower()
    start_idx = None
    for i, ln in enumerate(lowered):
        if target in ln:
            start_idx = i
            break
    if start_idx is None:
        return ""
    # Find end index: next heading line containing any other title text
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        lj = lowered[j]
        if any(t in lj for t in titles) and titles.index(target) != titles.index(next((t for t in titles if t in lj), target)):
            end_idx = j
            break
        # Also consider markdown headings as section boundaries
        if lines[j].strip().startswith(("# ", "## ", "### ")):
            # But don't break if the heading is within the same section title
            if target not in lj:
                end_idx = j
                break
    return "\n".join(lines[start_idx:end_idx])


def _is_truthy_str(s: str) -> Optional[bool]:
    if not isinstance(s, str):
        return None
    sl = s.strip().lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    return None


def _compute_counts_from_links(rows: List[Dict[str, str]]) -> Tuple[int, int, int, Dict[str, int]]:
    total = len(rows)
    found_cnt = 0
    per_domain: Dict[str, int] = {}
    for r in rows:
        f = _is_truthy_str(r.get("found", ""))
        if f is True:
            found_cnt += 1
            sd = (r.get("source_domain") or "").strip().lower()
            if sd:
                per_domain[sd] = per_domain.get(sd, 0) + 1
    missing = total - found_cnt
    return total, found_cnt, missing, per_domain


def _safe_float_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_present": 0.0,
        "schedule_cron_valid": 0.0,
        "links_csv_structure": 0.0,
        "links_row_count_matches_components": 0.0,
        "links_components_coverage_complete": 0.0,
        "links_domains_and_query": 0.0,
        "links_found_url_source_domain_valid": 0.0,
        "links_retrieved_at_iso_valid": 0.0,
        "links_queried_domains_match_allowed": 0.0,
        "stats_json_structure": 0.0,
        "stats_consistent_with_links": 0.0,
        "daily_summary_sections_present": 0.0,
        "daily_summary_overview_content": 0.0,
        "daily_summary_counts_consistent": 0.0,
        "daily_summary_per_domain_consistent": 0.0,
        "daily_summary_missing_components_list": 0.0,
        "log_last_run_entry_present": 0.0,
    }

    # Load inputs
    components_csv_path = workspace / "input" / "components.csv"
    project_info_path = workspace / "input" / "project_info.json"

    components_rows, components_header = _load_csv_dicts(components_csv_path)
    project_info = _load_json(project_info_path)

    expected_components: List[Tuple[str, str]] = []
    allowed_domains: List[str] = []
    project_name = None

    if components_rows is not None and components_header is not None and "component" in components_header and "search_terms" in components_header:
        for r in components_rows:
            comp = (r.get("component") or "").strip()
            terms = (r.get("search_terms") or "").strip()
            if comp:
                expected_components.append((comp, terms))
    if isinstance(project_info, dict):
        allowed_domains = project_info.get("allowed_domains") or []
        if not isinstance(allowed_domains, list):
            allowed_domains = []
        allowed_domains = [str(d).strip() for d in allowed_domains if str(d).strip()]
        project_name = project_info.get("project_name")

    # Parse schedule.cron to validate and extract script path reference
    schedule_path = workspace / "config" / "schedule.cron"
    schedule_text = _read_text(schedule_path)
    script_path_from_cron: Optional[Path] = None
    if schedule_text is not None:
        non_comment_lines = []
        for ln in schedule_text.splitlines():
            stripped = ln.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            non_comment_lines.append(stripped)
        if len(non_comment_lines) == 1:
            line = non_comment_lines[0]
            parts = line.split()
            cron_ok = False
            if len(parts) >= 6:
                cron_ok = (parts[0] == "30" and parts[1] == "9" and parts[2] == "*" and parts[3] == "*" and parts[4] == "1-5")
            # Validate logs redirection mention
            logs_ok = ("logs/last_run.log" in line)
            # Extract script path reference that includes scripts/run_check
            script_token = None
            m = re.search(r"(\S*scripts/run_check\S*)", line)
            if m:
                script_token = m.group(1)
            # Map to local workspace path using trailing scripts/run_check... portion
            if script_token:
                # Normalize possible quotes
                script_token = script_token.strip('\'"')
                # Extract trailing part from scripts/...
                idx = script_token.rfind("scripts/")
                trailing = script_token[idx:] if idx != -1 else script_token
                candidate = workspace / trailing
                if candidate.exists() and candidate.is_file():
                    script_path_from_cron = candidate
            if cron_ok and logs_ok and script_token is not None:
                scores["schedule_cron_valid"] = 1.0
        # else leave default 0.0

    # script_present derived from cron script path existence
    if script_path_from_cron is not None and script_path_from_cron.exists() and script_path_from_cron.is_file():
        scores["script_present"] = 1.0

    # Validate output/links.csv
    links_csv_path = workspace / "output" / "links.csv"
    links_rows, links_header = _load_csv_dicts(links_csv_path)

    # links_csv_structure: exact headers as specified
    expected_header = [
        "component",
        "search_terms",
        "queried_domains",
        "search_query",
        "found",
        "title",
        "url",
        "source_domain",
        "retrieved_at_iso",
    ]
    if links_rows is not None and links_header is not None:
        if links_header == expected_header:
            scores["links_csv_structure"] = 1.0

    # links_row_count_matches_components and links_components_coverage_complete
    if links_rows is not None and expected_components:
        # Check count
        if len(links_rows) == len(expected_components):
            scores["links_row_count_matches_components"] = 1.0
        # Check coverage of all components
        expected_names = {c for c, _ in expected_components}
        got_names = { (r.get("component") or "").strip() for r in links_rows }
        if expected_names == got_names:
            scores["links_components_coverage_complete"] = 1.0

    # links_domains_and_query: search_query should include search_terms and allowed domains
    if links_rows is not None and expected_components and allowed_domains:
        comp_to_terms = {c: t for c, t in expected_components}
        pass_count = 0
        for r in links_rows:
            comp = (r.get("component") or "").strip()
            terms = comp_to_terms.get(comp, "")
            query = (r.get("search_query") or "").strip().lower()
            ok = True
            if terms:
                if terms.lower() not in query:
                    ok = False
            # Must include each allowed domain name (as substring)
            for dom in allowed_domains:
                if dom.lower() not in query:
                    ok = False
                    break
            pass_count += 1 if ok else 0
        if len(links_rows) > 0:
            scores["links_domains_and_query"] = pass_count / len(links_rows)

    # links_found_url_source_domain_valid and source domain allowed
    if links_rows is not None:
        total_found_rows = 0
        valid_found_rows = 0
        for r in links_rows:
            found_val = _is_truthy_str(r.get("found", ""))
            if found_val is True:
                total_found_rows += 1
                url = (r.get("url") or "").strip()
                sd = (r.get("source_domain") or "").strip().lower()
                host = _extract_host(url) if url else None
                scheme_ok = url.lower().startswith("http://") or url.lower().startswith("https://")
                sd_match = (host == sd) if host else False
                # If allowed_domains known, ensure host matches allowed
                allowed_ok = True
                if allowed_domains:
                    allowed_ok = _host_matches_allowed(sd, allowed_domains)
                if url and host and scheme_ok and sd_match and allowed_ok:
                    valid_found_rows += 1
        # links_found_url_source_domain_valid: ratio among found=true rows, or 1.0 if none found (vacuously true)
        if total_found_rows == 0:
            scores["links_found_url_source_domain_valid"] = 1.0
        else:
            scores["links_found_url_source_domain_valid"] = valid_found_rows / max(1, total_found_rows)

    # links_retrieved_at_iso_valid
    if links_rows is not None:
        time_valid_count = 0
        for r in links_rows:
            ts = r.get("retrieved_at_iso")
            dt = _parse_iso(ts) if ts is not None else None
            if dt is not None:
                time_valid_count += 1
        if len(links_rows) > 0:
            scores["links_retrieved_at_iso_valid"] = time_valid_count / len(links_rows)

    # links_queried_domains_match_allowed
    if links_rows is not None and allowed_domains:
        expected_qd = ";".join(allowed_domains)
        good = 0
        for r in links_rows:
            qd = (r.get("queried_domains") or "").strip()
            good += 1 if qd == expected_qd else 0
        if len(links_rows) > 0:
            scores["links_queried_domains_match_allowed"] = good / len(links_rows)

    # found field validity: ensure only true/false appears; integrate into structure? Create implicit gate in found_url_source check else leave.

    # Validate stats.json
    stats_path = workspace / "output" / "stats.json"
    stats = _load_json(stats_path)
    stats_fields_ok = False
    stats_dates_ok = False
    stats_consistency_ok = False
    if isinstance(stats, dict):
        required_keys = {"total_components", "found", "missing", "coverage_pct", "per_domain_counts", "generated_at_iso"}
        if required_keys.issubset(stats.keys()) and isinstance(stats.get("per_domain_counts"), dict):
            stats_fields_ok = True
            # ISO check
            stats_dates_ok = _parse_iso(stats.get("generated_at_iso")) is not None

            if links_rows is not None:
                total, found_cnt, missing_cnt, per_domain = _compute_counts_from_links(links_rows)
                cov = round((found_cnt / total * 100.0) if total > 0 else 0.0, 1)
                consistent = (
                    stats.get("total_components") == total and
                    stats.get("found") == found_cnt and
                    stats.get("missing") == missing_cnt and
                    _safe_float_equal(float(stats.get("coverage_pct")), cov) and
                    {k: int(v) for k, v in stats.get("per_domain_counts", {}).items()} == per_domain
                )
                stats_consistency_ok = bool(consistent)

    if stats_fields_ok and stats_dates_ok:
        scores["stats_json_structure"] = 1.0
    if stats_consistency_ok:
        scores["stats_consistent_with_links"] = 1.0

    # Validate daily_summary.md
    summary_path = workspace / "output" / "daily_summary.md"
    summary_text = _read_text(summary_path)
    if summary_text is not None:
        # Sections existence
        sections_ok = all(
            _extract_section(summary_text, title).strip() != ""
            for title in ["Overview", "Counts", "Per-domain breakdown", "Component coverage details"]
        )
        if sections_ok:
            scores["daily_summary_sections_present"] = 1.0

        # Overview content: include project_name and retrieval timestamp
        overview = _extract_section(summary_text, "Overview")
        overview_ok = False
        if isinstance(project_name, str) and project_name in overview:
            # Look for ISO-like timestamp
            has_iso = bool(re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", overview))
            overview_ok = has_iso
        if overview_ok:
            scores["daily_summary_overview_content"] = 1.0

        # Counts consistent: ensure presence of total, found, missing, coverage numbers
        counts_ok = False
        if isinstance(stats, dict):
            total_str = str(stats.get("total_components"))
            found_str = str(stats.get("found"))
            missing_str = str(stats.get("missing"))
            cov_val = stats.get("coverage_pct")
            cov_str = f"{cov_val:.1f}" if isinstance(cov_val, (int, float)) else str(cov_val)
            counts_section = _extract_section(summary_text, "Counts")
            if all(x in counts_section for x in [total_str, found_str, missing_str]) and (cov_str in counts_section):
                counts_ok = True
        if counts_ok:
            scores["daily_summary_counts_consistent"] = 1.0

        # Per-domain breakdown consistent
        per_domain_ok = False
        if isinstance(stats, dict) and isinstance(stats.get("per_domain_counts"), dict):
            pdb_section = _extract_section(summary_text, "Per-domain breakdown")
            domain_checks = 0
            domain_hits = 0
            for dom, cnt in stats.get("per_domain_counts", {}).items():
                domain_checks += 1
                # Look for a line containing both domain and count
                found_line = False
                for ln in pdb_section.splitlines():
                    if dom in ln and str(cnt) in ln:
                        found_line = True
                        break
                if found_line:
                    domain_hits += 1
            # If there are no domains, consider it okay (empty breakdown)
            per_domain_ok = (domain_checks == 0) or (domain_hits == domain_checks)
        if per_domain_ok:
            scores["daily_summary_per_domain_consistent"] = 1.0

        # Missing components list: must include components where found=false
        missing_ok = False
        if links_rows is not None:
            missing_components = [ (r.get("component") or "").strip() for r in links_rows if _is_truthy_str(r.get("found", "")) is False ]
            msec = _extract_section(summary_text, "Component coverage details")
            if len(missing_components) == 0:
                # If none missing, section can be empty or state none; consider ok
                missing_ok = True
            else:
                # All missing components must be present by name
                all_present = all((mc in msec) for mc in missing_components if mc)
                missing_ok = all_present
        if missing_ok:
            scores["daily_summary_missing_components_list"] = 1.0

    # logs/last_run.log
    log_path = workspace / "logs" / "last_run.log"
    log_text = _read_text(log_path)
    if log_text is not None:
        # Check presence of start time, end time, and status OK/ERROR
        # Look for at least one line containing 'status' and OK/ERROR
        status_match = re.search(r"status[^A-Za-z0-9]+(OK|ERROR)", log_text, flags=re.IGNORECASE)
        # Look for ISO timestamps patterns
        has_start = re.search(r"start[^A-Za-z0-9]+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", log_text, flags=re.IGNORECASE)
        has_end = re.search(r"end[^A-Za-z0-9]+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", log_text, flags=re.IGNORECASE)
        if status_match and has_start and has_end:
            scores["log_last_run_entry_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()