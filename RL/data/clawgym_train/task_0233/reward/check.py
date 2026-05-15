import json
import re
import sys
import csv
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlparse


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_simple_yaml(path: Path) -> Optional[dict]:
    """
    Minimal YAML loader for simple key: value and key: [list] structures used in the task inputs.
    Supports:
    - key: "value" or key: value (string)
    - key:
        - "item1"
        - item2
    Does not support nested dicts beyond top-level lists of strings.
    """
    text = _read_text(path)
    if text is None:
        return None
    data: Dict[str, object] = {}
    current_list_key: Optional[str] = None

    def _strip_quotes(val: str) -> str:
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            return val[1:-1]
        return val

    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("-") and current_list_key:
            item = line.lstrip()[1:].strip()
            item = _strip_quotes(item)
            if isinstance(data.get(current_list_key), list):
                data[current_list_key].append(item)
            else:
                data[current_list_key] = [item]
            continue
        m = re.match(r'^([A-Za-z0-9_]+)\s*:\s*(.*)$', line)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            if value == "" or value == "|":  # start of list or multiline not supported
                current_list_key = key
                data[key] = []
            else:
                current_list_key = None
                value = _strip_quotes(value)
                # Attempt to parse int for numeric fields
                if re.fullmatch(r'\d+', value):
                    data[key] = int(value)
                else:
                    data[key] = value
        else:
            # Unhandled line; break parsing safely
            continue
    return data


def _read_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _parse_csv_dict(path: Path) -> Optional[Tuple[List[str], List[dict]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = []
            for row in reader:
                rows.append(row)
        return headers, rows
    except Exception:
        return None


def _find_date_dirs(base: Path) -> List[Path]:
    if not base.exists():
        return []
    dirs = []
    for p in base.iterdir():
        if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name):
            dirs.append(p)
    return sorted(dirs, key=lambda d: d.name)


def _latest_date_dir(base: Path) -> Optional[Path]:
    dirs = _find_date_dirs(base)
    return dirs[-1] if dirs else None


def _domain_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return None


def _is_domain_allowed(url: str, allowed: List[str]) -> bool:
    d = _domain_from_url(url)
    if not d:
        return False
    for a in allowed:
        a = a.lower().strip()
        if d == a or d.endswith("." + a):
            return True
    return False


def _parse_time_hhmm(s: str) -> Optional[Tuple[int, int]]:
    m = re.fullmatch(r"(\d{2}):(\d{2})", s.strip())
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return hh, mm
    return None


def _parse_date_guess(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%d.%m.%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    # Try to extract ISO-like date in string
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
        except Exception:
            pass
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "raw_search_jsonl_exists_and_valid": 0.0,
        "raw_search_min_unique_urls": 0.0,
        "raw_search_domains_allowed": 0.0,
        "filtered_listings_csv_exists_and_columns": 0.0,
        "filtered_listings_rank_ordering": 0.0,
        "filtered_listings_filter_criteria": 0.0,
        "letters_count_matches_top_n": 0.0,
        "letters_placeholder_replacement": 0.0,
        "letters_salutation_company_unknown": 0.0,
        "schedule_cron_entry_valid": 0.0,
        "run_script_exists": 0.0,
        "logs_file_exists_and_counts": 0.0,
    }

    # Load inputs
    job_filters = _load_simple_yaml(workspace / "input" / "job_filters.yaml")
    profile = _load_simple_yaml(workspace / "input" / "profile.yaml")
    cover_template_text = _read_text(workspace / "input" / "cover_letter_template.md")

    allowed_domains: List[str] = []
    include_keywords: List[str] = []
    exclude_keywords: List[str] = []
    location_keywords: List[str] = []
    top_n_letters: int = 0
    daily_run_time_local: Optional[str] = None

    if isinstance(job_filters, dict):
        allowed_domains = list(job_filters.get("allowed_domains") or [])
        include_keywords = list(job_filters.get("include_keywords") or [])
        exclude_keywords = list(job_filters.get("exclude_keywords") or [])
        location_keywords = list(job_filters.get("location_keywords") or [])
        top_n_letters = int(job_filters.get("top_n_letters") or 0)
        daily_run_time_local = job_filters.get("daily_run_time_local")

    # 1) Raw search JSONL checks
    raw_base = workspace / "output" / "raw_search"
    raw_date_dir = _latest_date_dir(raw_base)
    raw_jsonl_path = None
    raw_items: List[dict] = []
    if raw_date_dir:
        candidate = raw_date_dir / "search_results.jsonl"
        if candidate.exists():
            raw_jsonl_path = candidate
            parsed = _read_jsonl(candidate)
            if isinstance(parsed, list) and parsed:
                # Validate fields per line
                required_keys = {"query", "source_domain", "title", "snippet", "url", "retrieval_timestamp"}
                valid = True
                for obj in parsed:
                    if set(obj.keys()) >= required_keys:
                        # Type checks
                        if not all(isinstance(obj[k], str) for k in required_keys):
                            valid = False
                            break
                    else:
                        valid = False
                        break
                if valid:
                    scores["raw_search_jsonl_exists_and_valid"] = 1.0
                    raw_items = parsed

    # 2) Raw search unique URL count and domain restriction
    if raw_items:
        urls = [it.get("url", "") for it in raw_items if isinstance(it.get("url"), str)]
        unique_urls = list(dict.fromkeys(urls))
        if len(unique_urls) >= 20:
            scores["raw_search_min_unique_urls"] = 1.0
        if allowed_domains:
            domains_ok = True
            for it in raw_items:
                src_domain = str(it.get("source_domain", "")).lower().strip()
                url = it.get("url", "")
                # Check source_domain is allowed and URL domain is allowed
                src_allowed = any(src_domain == d.lower() for d in allowed_domains)
                url_allowed = _is_domain_allowed(url, allowed_domains)
                if not (src_allowed and url_allowed):
                    domains_ok = False
                    break
            if domains_ok:
                scores["raw_search_domains_allowed"] = 1.0

    # 3) Filtered listings CSV existence and columns
    listings_base = workspace / "output" / "listings"
    listings_date_dir = _latest_date_dir(listings_base)
    filtered_csv_path = None
    filtered_headers: List[str] = []
    filtered_rows: List[dict] = []
    expected_cols = [
        "rank",
        "job_title",
        "company",
        "source_domain",
        "url",
        "matched_keywords",
        "location_hint",
        "posted_date_hint",
        "retrieval_timestamp",
    ]
    if listings_date_dir:
        candidate = listings_date_dir / "filtered_listings.csv"
        parsed = _parse_csv_dict(candidate) if candidate.exists() else None
        if parsed:
            filtered_csv_path = candidate
            filtered_headers, filtered_rows = parsed
            if filtered_headers == expected_cols:
                scores["filtered_listings_csv_exists_and_columns"] = 1.0

    # 4) Rank ordering check
    if filtered_rows:
        try:
            ranks = [int(row.get("rank", "0")) for row in filtered_rows]
            sequential = ranks == list(range(1, len(ranks) + 1))
            # Sort by matched keyword count (descending)
            def count_matches(s: str) -> int:
                s = (s or "").strip()
                if not s:
                    return 0
                parts = [p.strip() for p in s.split(";") if p.strip()]
                return len(parts)

            counts = [count_matches(row.get("matched_keywords", "")) for row in filtered_rows]
            # Check non-increasing
            non_increasing = all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1))
            # Secondary check by posted_date_hint if parseable
            date_order_ok = True
            parsed_dates = [_parse_date_guess(row.get("posted_date_hint", "")) for row in filtered_rows]
            # If both adjacent dates exist, they should be non-increasing (newest first)
            for i in range(len(parsed_dates) - 1):
                d1 = parsed_dates[i]
                d2 = parsed_dates[i + 1]
                if d1 and d2:
                    if d1 < d2:
                        date_order_ok = False
                        break
            if sequential and non_increasing and date_order_ok:
                scores["filtered_listings_rank_ordering"] = 1.0
        except Exception:
            pass

    # 5) Filter criteria check: include at least one include keyword, at least one location keyword, no exclude
    if filtered_rows and (include_keywords or location_keywords):
        try:
            all_ok = True
            for row in filtered_rows:
                matched = [p.strip() for p in (row.get("matched_keywords", "") or "").split(";") if p.strip()]
                loc_hint = row.get("location_hint", "") or ""
                # Include: at least one of include_keywords present in matched
                include_ok = any(ik in matched for ik in include_keywords) if include_keywords else True
                # Location: location_keywords must appear in location_hint
                location_ok = any(lk.lower() in loc_hint.lower() for lk in location_keywords) if location_keywords else True
                # Exclude: none of exclude keywords appear in matched or location hint
                exclude_ok = not any(ek in matched or (ek.lower() in loc_hint.lower()) for ek in exclude_keywords)
                # Domains allowed:
                src_domain = str(row.get("source_domain", "")).lower().strip()
                domain_ok = any(src_domain == d.lower() for d in allowed_domains) if allowed_domains else True
                if not (include_ok and location_ok and exclude_ok and domain_ok):
                    all_ok = False
                    break
            if all_ok:
                scores["filtered_listings_filter_criteria"] = 1.0
        except Exception:
            pass

    # 6) Letters count and placeholders replacement
    letters_base = workspace / "output" / "letters"
    letters_date_dir = _latest_date_dir(letters_base)
    letters_files: List[Path] = []
    rank_to_letter: Dict[int, Path] = {}
    if letters_date_dir:
        for p in letters_date_dir.iterdir():
            if p.is_file():
                m = re.fullmatch(r"cover_letter_(\d+)\.md", p.name)
                if m:
                    r = int(m.group(1))
                    letters_files.append(p)
                    rank_to_letter[r] = p
        letters_files = sorted(letters_files, key=lambda x: x.name)

    # letters_count_matches_top_n
    if filtered_rows:
        num_filtered = len(filtered_rows)
        expected_letters = min(top_n_letters if top_n_letters else 0, num_filtered)
        actual_letters = len(letters_files)
        if expected_letters == actual_letters and expected_letters > 0:
            scores["letters_count_matches_top_n"] = 1.0

    # letters_placeholder_replacement: check values present and placeholders not left
    if letters_files and profile:
        placeholders = [
            "{{job_title}}",
            "{{company}}",
            "{{url}}",
            "{{source_domain}}",
            "{{candidate_name}}",
            "{{phone}}",
            "{{email}}",
            "{{city}}",
            "{{availability}}",
            "{{languages}}",
            "{{skills}}",
            "{{permit}}",
        ]
        name = profile.get("name") or profile.get("candidate_name")
        phone = profile.get("phone")
        email = profile.get("email")
        city = profile.get("city")
        availability = profile.get("availability")
        languages = profile.get("languages")
        skills = profile.get("skills")
        permit = profile.get("permit")
        basic_ok = True
        for p in letters_files:
            t = _read_text(p) or ""
            # No template placeholders remaining
            if any(ph in t for ph in placeholders):
                basic_ok = False
                break
            # Basic personal info present
            expected_fragments = [str(name or ""), str(phone or ""), str(email or ""), str(city or ""), str(availability or ""), str(permit or "")]
            if any(not frag or frag not in t for frag in expected_fragments):
                basic_ok = False
                break
            # Languages and skills - ensure at least one appears
            lang_ok = True
            if isinstance(languages, list) and languages:
                lang_ok = any(str(l) in t for l in languages)
            skill_ok = True
            if isinstance(skills, list) and skills:
                skill_ok = any(str(s) in t for s in skills)
            if not (lang_ok and skill_ok):
                basic_ok = False
                break
        if basic_ok:
            scores["letters_placeholder_replacement"] = 1.0

    # letters_salutation_company_unknown
    if filtered_rows and rank_to_letter:
        salutation_ok = True
        for row in filtered_rows:
            r = int(row.get("rank", "0"))
            company = (row.get("company") or "").strip()
            letter_path = rank_to_letter.get(r)
            if not letter_path:
                continue
            text = _read_text(letter_path) or ""
            if company and company.lower() != "unknown":
                # Expect "Dear {company} Hiring Team"
                expected = f"Dear {company} Hiring Team"
                if expected not in text:
                    salutation_ok = False
                    break
            else:
                # Expect "Dear Hiring Manager"
                if "Dear Hiring Manager" not in text:
                    salutation_ok = False
                    break
        if salutation_ok:
            scores["letters_salutation_company_unknown"] = 1.0

    # 7) Schedule cron entry validation
    cron_path = workspace / "output" / "schedule" / "cron_entry.txt"
    cron_text = _read_text(cron_path)
    if cron_text and daily_run_time_local:
        # Check timezone comment and scripts/run_job.sh reference
        has_tz_comment = "Europe/Stockholm" in cron_text
        references_script = "scripts/run_job.sh" in cron_text
        tm = _parse_time_hhmm(daily_run_time_local)
        time_ok = False
        if tm:
            hh, mm = tm
            # Cron minute hour
            cron_time_match = re.search(rf'^\s*{mm}\s+{hh}\s+\*\s+\*\s+\*\s+', cron_text, re.MULTILINE)
            time_ok = cron_time_match is not None
        if has_tz_comment and references_script and time_ok:
            scores["schedule_cron_entry_valid"] = 1.0

    # 8) run script exists
    run_script = workspace / "scripts" / "run_job.sh"
    run_script_text = _read_text(run_script)
    if run_script_text:
        # Check it's a shell script with shebang and mentions output/logs
        has_shebang = run_script_text.strip().startswith("#!") or run_script_text.splitlines()[0].strip().startswith("#!")
        mentions_logs = "output/logs" in run_script_text
        if has_shebang and mentions_logs:
            scores["run_script_exists"] = 1.0

    # 9) logs file exists and counts present
    logs_dir = workspace / "output" / "logs"
    log_files = []
    if logs_dir.exists():
        for p in logs_dir.iterdir():
            if p.is_file() and re.fullmatch(r"run_\d{8}_\d{6}\.log", p.name):
                log_files.append(p)
    log_files = sorted(log_files, key=lambda p: p.name)
    if log_files:
        latest_log = _read_text(log_files[-1]) or ""
        # Extract counts: total URLs fetched, filtered count, and letters generated.
        # We'll search for integers in lines mentioning these terms.
        def _extract_count(text: str, key_words: List[str]) -> Optional[int]:
            for line in text.splitlines():
                if all(kw.lower() in line.lower() for kw in key_words):
                    nums = re.findall(r"\d+", line)
                    if nums:
                        try:
                            return int(nums[-1])
                        except Exception:
                            continue
            return None

        total_urls = _extract_count(latest_log, ["total", "url"])
        filtered_count = _extract_count(latest_log, ["filtered"])
        letters_generated = _extract_count(latest_log, ["letter"])
        if total_urls is not None and filtered_count is not None and letters_generated is not None:
            scores["logs_file_exists_and_counts"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()