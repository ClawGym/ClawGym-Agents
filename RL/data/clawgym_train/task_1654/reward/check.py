import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_json_safe(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl_safe(p: Path) -> Optional[List[dict]]:
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    entries = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
            entries.append(obj)
        except Exception:
            return None
    return entries


def _read_csv_dicts_safe(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            # Validate presence of headers (non-empty)
            if reader.fieldnames is None or any(h is None or h == "" for h in reader.fieldnames):
                return None
            return rows
    except Exception:
        return None


def _parse_simple_yaml_for_config(p: Path) -> Dict[str, Any]:
    """
    Minimal, robust parser to extract specific keys from fetch_config.yaml:
    - allowed_domains: list of strings
    - invalid_test_url: string
    We avoid external deps; this handles simple structures in provided file.
    """
    result = {"allowed_domains": [], "invalid_test_url": None}
    text = _read_text_safe(p)
    if text is None:
        return result
    lines = text.splitlines()
    in_allowed = False
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("allowed_domains:"):
            in_allowed = True
            continue
        if line.startswith("topics:"):
            in_allowed = False
            continue
        if in_allowed and line.startswith("-"):
            domain = line.lstrip("-").strip()
            if domain:
                result["allowed_domains"].append(domain)
            continue
        if line.startswith("invalid_test_url:"):
            # capture after colon or quoted
            m = re.match(r'invalid_test_url:\s*["\']?(.*?)["\']?$', line)
            if m:
                result["invalid_test_url"] = m.group(1).strip()
            else:
                # fallback: split by colon
                parts = line.split(":", 1)
                if len(parts) == 2:
                    result["invalid_test_url"] = parts[1].strip().strip('"').strip("'")
            in_allowed = False
    return result


def _domain_from_url(url: str) -> Optional[str]:
    try:
        # Simple parse
        m = re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://([^/]+)', url)
        if not m:
            return None
        return m.group(1).lower()
    except Exception:
        return None


def _endswith_allowed_domain(domain: Optional[str], allowed: List[str]) -> bool:
    if not domain:
        return False
    d = domain.lower()
    for a in allowed:
        a = a.lower()
        if d == a or d.endswith("." + a):
            return True
    return False


def _is_iso8601_like(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    candidate = s.strip()
    # Replace Z with +00:00 for fromisoformat (Python)
    cand = candidate.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(cand)
        return True
    except Exception:
        # Fallback simple regex check (YYYY-MM-DDTHH:MM:SS(.fff)?(Z|+hh:mm)?)
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$"
        return re.match(pattern, candidate) is not None


def _compute_week_bounds(d: date) -> Tuple[date, date]:
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _tokenize_words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z']+", text.lower())


def _simple_stopwords() -> set:
    return {
        "the","and","a","an","in","on","for","to","of","is","are","was","were","be","been","being",
        "or","as","at","by","with","from","that","this","it","its","we","you","your","our","they",
        "their","them","he","she","his","her","i","me","my","mine","ours","yours","theirs","but",
        "not","out","up","down","over","under","too","very","can","could","should","would","do",
        "did","done","have","has","had","will","just","so","if","when","while","about","into",
        "more","most","less","least","also","than","then","there","here","how","what","why",
        "who","whom","which","because","during","after","before","such","no","yes"
    }


def _count_overlapping(haystack: str, needle: str) -> int:
    if not haystack or not needle:
        return 0
    count = 0
    start = 0
    h = haystack.lower()
    n = needle.lower()
    while True:
        idx = h.find(n, start)
        if idx == -1:
            break
        count += 1
        start = idx + 1
    return count


def _round1(x: float) -> float:
    return float(f"{x:.1f}")


def _parse_date_safe(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _extract_athlete_numbers_by_name(summary_rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    For each athlete, collect string representations of numeric stats across weeks:
    sessions (int), total_duration_min (int), avg_rpe (1 decimal), sparring_sessions (int),
    avg_duration_min (1 decimal).
    Returns dict athlete -> list of unique numeric string tokens acceptable for matching.
    """
    per_athlete: Dict[str, set] = defaultdict(set)
    for row in summary_rows:
        name = row.get("athlete", "")
        if not name:
            continue
        # Add ints as plain and with .0 to allow either representation
        for key in ["sessions", "total_duration_min", "sparring_sessions"]:
            v = row.get(key)
            try:
                iv = int(v)
                per_athlete[name].add(str(iv))
                per_athlete[name].add(f"{iv}.0")
            except Exception:
                pass
        # Add floats with 1 decimal and possible integer forms
        for key in ["avg_rpe", "avg_duration_min"]:
            v = row.get(key)
            try:
                fv = float(v)
                per_athlete[name].add(f"{fv:.1f}")
                per_athlete[name].add(str(int(round(fv))))  # sometimes printed as int
            except Exception:
                pass
    return {k: sorted(list(v)) for k, v in per_athlete.items()}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "web_raw_html_exists": 0.0,
        "web_extracted_text_exists_and_clean": 0.0,
        "web_metadata_fields_and_counts_valid": 0.0,
        "web_domain_allowed_and_consistent": 0.0,
        "fetch_log_two_entries_order_and_fields": 0.0,
        "fetch_log_invalid_attempt_details": 0.0,
        "fetch_log_success_attempt_consistency": 0.0,
        "analytics_weekly_summary_present_and_header": 0.0,
        "analytics_weekly_summary_row_values": 0.0,
        "athlete_updates_per_athlete_presence_and_content": 0.0,
        "staff_update_concise_and_plain_language": 0.0,
    }

    # Paths
    raw_html_p = workspace / "output" / "web" / "raw.html"
    extracted_txt_p = workspace / "output" / "web" / "extracted.txt"
    metadata_json_p = workspace / "output" / "web" / "metadata.json"
    log_jsonl_p = workspace / "output" / "logs" / "fetch_log.jsonl"
    weekly_summary_p = workspace / "output" / "analytics" / "weekly_summary.csv"
    athlete_updates_p = workspace / "output" / "messages" / "athlete_updates.md"
    staff_update_p = workspace / "output" / "messages" / "staff_update.md"

    # Config
    fetch_config_p = workspace / "input" / "fetch_config.yaml"
    cfg = _parse_simple_yaml_for_config(fetch_config_p)
    allowed_domains = cfg.get("allowed_domains", []) or ["cdc.gov", "medlineplus.gov"]
    invalid_test_url = cfg.get("invalid_test_url")

    # Part A checks
    raw_html = _read_text_safe(raw_html_p)
    if raw_html is not None and len(raw_html.strip()) > 0:
        # some basic expectation
        scores["web_raw_html_exists"] = 1.0

    extracted_txt = _read_text_safe(extracted_txt_p)
    if extracted_txt is not None and len(extracted_txt.strip()) > 0:
        # Basic cleanliness: should not contain HTML tags
        if "<" not in extracted_txt and ">" not in extracted_txt:
            scores["web_extracted_text_exists_and_clean"] = 1.0

    metadata = _read_json_safe(metadata_json_p)
    meta_ok = False
    domain_ok = False
    if metadata is not None and isinstance(metadata, dict):
        required_fields = ["source_url", "domain", "char_count", "word_count", "top_20_words", "keyword_counts"]
        if all(k in metadata for k in required_fields):
            # char_count/word_count
            char_count_ok = False
            word_count_ok = False
            if extracted_txt is not None:
                try:
                    char_count_ok = int(metadata["char_count"]) == len(extracted_txt)
                except Exception:
                    char_count_ok = False
                try:
                    wc = len(extracted_txt.split())
                    word_count_ok = int(metadata["word_count"]) == wc
                except Exception:
                    word_count_ok = False
            # top_20_words validation
            t20_ok = False
            t20 = metadata.get("top_20_words")
            if isinstance(t20, list) and 1 <= len(t20) <= 20:
                words_seen = set()
                non_inc = True
                last_count = None
                counts_reasonable = True
                appears_in_text = True
                if extracted_txt is not None:
                    tokens = _tokenize_words(extracted_txt)
                    stop = _simple_stopwords()
                    counts = Counter([w for w in tokens if w not in stop])
                    for entry in t20:
                        if not isinstance(entry, dict):
                            counts_reasonable = False
                            break
                        w = entry.get("word")
                        c = entry.get("count")
                        if not isinstance(w, str) or not isinstance(c, int) or c <= 0:
                            counts_reasonable = False
                            break
                        if w.lower() in words_seen:
                            counts_reasonable = False
                            break
                        words_seen.add(w.lower())
                        # descending check
                        if last_count is not None and c > last_count:
                            non_inc = False
                        last_count = c
                        # count should not exceed observed count
                        if c > counts.get(w.lower(), 0):
                            counts_reasonable = False
                            break
                        # word should appear at least once
                        if counts.get(w.lower(), 0) == 0:
                            appears_in_text = False
                            break
                t20_ok = non_inc and counts_reasonable and appears_in_text
            # keyword_counts validation
            kw_ok = False
            kw = metadata.get("keyword_counts")
            keywords = ["hydration", "hydrate", "water", "heat", "dehydration"]
            if isinstance(kw, dict) and all(k in kw for k in keywords) and extracted_txt is not None:
                text_lower = extracted_txt.lower()
                within_bounds = True
                for k in keywords:
                    v = kw.get(k)
                    if not isinstance(v, int) or v < 0:
                        within_bounds = False
                        break
                    # lower and compute regex word-boundary count and overlapping substring count
                    regex_count = len(re.findall(rf"\b{k}\b", text_lower, flags=re.IGNORECASE))
                    substr_count = _count_overlapping(text_lower, k.lower())
                    if not (regex_count <= v <= substr_count):
                        within_bounds = False
                        break
                kw_ok = within_bounds
            meta_ok = char_count_ok and word_count_ok and t20_ok and kw_ok

            # domain checks
            source_url = metadata.get("source_url")
            meta_domain = metadata.get("domain")
            parsed_domain = _domain_from_url(source_url) if isinstance(source_url, str) else None
            domain_consistency = isinstance(meta_domain, str) and parsed_domain == meta_domain.lower()
            domain_allowed = _endswith_allowed_domain(parsed_domain, allowed_domains)
            domain_ok = domain_consistency and domain_allowed

    if meta_ok:
        scores["web_metadata_fields_and_counts_valid"] = 1.0
    if domain_ok:
        scores["web_domain_allowed_and_consistent"] = 1.0

    # Part B: fetch log checks
    entries = _read_jsonl_safe(log_jsonl_p)
    log_two_entries_ok = False
    log_invalid_ok = False
    log_success_ok = False
    if isinstance(entries, list) and len(entries) == 2:
        e1, e2 = entries[0], entries[1]
        # fields and order
        def _validate_entry(e: dict) -> bool:
            if not isinstance(e, dict):
                return False
            needed = ["attempt_id", "url_attempted", "timestamp_iso", "status",
                      "http_status_code", "error_type", "error_message", "retriable", "friendly_message"]
            if not all(k in e for k in needed):
                return False
            if not isinstance(e["attempt_id"], int):
                return False
            if not isinstance(e["url_attempted"], str) or not e["url_attempted"].strip():
                return False
            if not isinstance(e["status"], str) or e["status"] not in ("success", "fail"):
                return False
            if not isinstance(e["error_type"], str) or e["error_type"] not in ["dns_error", "timeout", "http_error", "other"]:
                return False
            if not isinstance(e["retriable"], bool):
                return False
            if not isinstance(e["friendly_message"], str) or not (1 <= len(e["friendly_message"]) <= 200):
                return False
            if not isinstance(e["error_message"], str):
                return False
            # timestamp check
            if not _is_iso8601_like(str(e["timestamp_iso"])):
                return False
            # http_status_code must be int or None
            if e["http_status_code"] is not None and not isinstance(e["http_status_code"], int):
                return False
            return True

        base_fields_ok = _validate_entry(e1) and _validate_entry(e2)
        order_ok = e1.get("attempt_id") == 1 and e2.get("attempt_id") == 2
        status_order_ok = e1.get("status") == "fail" and e2.get("status") == "success"
        # success http_status_code in 200..399, fail http_status_code None and error_message non-empty
        success_status_code_ok = isinstance(e2.get("http_status_code"), int) and 200 <= e2.get("http_status_code") < 400
        fail_status_code_ok = e1.get("http_status_code") is None and isinstance(e1.get("error_message"), str) and len(e1.get("error_message")) > 0
        # fail invalid URL equal to config invalid_test_url if available
        invalid_url_match_ok = True
        if isinstance(invalid_test_url, str) and invalid_test_url:
            invalid_url_match_ok = e1.get("url_attempted") == invalid_test_url

        log_two_entries_ok = base_fields_ok and order_ok and status_order_ok
        if log_two_entries_ok:
            scores["fetch_log_two_entries_order_and_fields"] = 1.0

        # Invalid attempt details
        invalid_type_ok = e1.get("error_type") in ["dns_error", "timeout", "http_error", "other"]
        invalid_friendly_ok = isinstance(e1.get("friendly_message"), str) and 1 <= len(e1.get("friendly_message")) <= 200
        log_invalid_ok = fail_status_code_ok and invalid_type_ok and invalid_friendly_ok and invalid_url_match_ok
        if log_invalid_ok:
            scores["fetch_log_invalid_attempt_details"] = 1.0

        # Success attempt consistency
        # url domain must be allowed and align with metadata domain if available
        succ_url = e2.get("url_attempted")
        succ_domain = _domain_from_url(succ_url) if isinstance(succ_url, str) else None
        succ_domain_allowed = _endswith_allowed_domain(succ_domain, allowed_domains)
        # Consistency with metadata: same domain suffix
        meta = metadata if isinstance(metadata, dict) else {}
        meta_src = meta.get("source_url") if isinstance(meta.get("source_url"), str) else None
        meta_domain = _domain_from_url(meta_src) if meta_src else None
        domain_alignment = False
        if succ_domain and meta_domain:
            # domains are considered aligned if exactly equal or share same allowed suffix
            domain_alignment = (succ_domain == meta_domain) or any(
                succ_domain == a or succ_domain.endswith("." + a) for a in allowed_domains
            ) and any(
                meta_domain == a or meta_domain.endswith("." + a) for a in allowed_domains
            )
        success_fields_ok = success_status_code_ok and succ_domain_allowed and domain_alignment
        success_error_fields_ok = e2.get("error_message") == "" and isinstance(e2.get("friendly_message"), str) and 1 <= len(e2.get("friendly_message")) <= 200
        log_success_ok = success_fields_ok and success_error_fields_ok
        if log_success_ok:
            scores["fetch_log_success_attempt_consistency"] = 1.0

    # Part C: weekly summary
    # Load input training logs and compute expected summary
    input_logs_p = workspace / "input" / "training_logs.csv"
    rows = _read_csv_dicts_safe(input_logs_p)
    expected_summary: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    header_ok = False
    if rows is not None:
        # Validate required columns in input
        req_cols = {"date", "athlete", "session_type", "duration_min", "rpe", "notes"}
        if rows:
            if set(rows[0].keys()) >= req_cols:
                header_ok = True
        else:
            # Empty input still has headers; can't compute
            header_ok = True

        # Aggregate
        grouped: Dict[Tuple[str, date, date], List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            ds = r.get("date", "")
            d = _parse_date_safe(ds)
            athlete = r.get("athlete", "").strip()
            if not d or not athlete:
                grouped = {}
                break
            ws, we = _compute_week_bounds(d)
            grouped[(athlete, ws, we)].append(r)

        valid_grouped = len(grouped) > 0
        if valid_grouped:
            for (ath, ws, we), items in grouped.items():
                sessions = len(items)
                total_duration = 0.0
                rpes = []
                spar_count = 0
                durations = []
                for it in items:
                    di = _safe_float(str(it.get("duration_min", "")).strip())
                    ri = _safe_float(str(it.get("rpe", "")).strip())
                    st = str(it.get("session_type", "")).lower()
                    notes = str(it.get("notes", "")).lower()
                    if di is None or ri is None:
                        valid_grouped = False
                        break
                    total_duration += di
                    rpes.append(ri)
                    durations.append(di)
                    if "sparring" in st or "sparring" in notes:
                        spar_count += 1
                if not valid_grouped:
                    break
                avg_rpe = _round1(sum(rpes) / len(rpes)) if rpes else 0.0
                avg_duration = _round1(sum(durations) / len(durations)) if durations else 0.0
                key = (ath, ws.isoformat(), we.isoformat())
                expected_summary[key] = {
                    "athlete": ath,
                    "week_start": ws.isoformat(),
                    "week_end": we.isoformat(),
                    "sessions": int(sessions),
                    "total_duration_min": int(round(total_duration)) if abs(total_duration - round(total_duration)) < 1e-9 else int(total_duration),
                    "avg_rpe": float(avg_rpe),
                    "sparring_sessions": int(spar_count),
                    "avg_duration_min": float(avg_duration),
                }

    # Check weekly_summary.csv
    output_rows = _read_csv_dicts_safe(weekly_summary_p)
    if output_rows is not None and len(output_rows) >= 1:
        # header order check
        expected_header = ["athlete", "week_start", "week_end", "sessions", "total_duration_min", "avg_rpe", "sparring_sessions", "avg_duration_min"]
        try:
            with weekly_summary_p.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
            if header == expected_header:
                scores["analytics_weekly_summary_present_and_header"] = 1.0
        except Exception:
            pass

        # Compare content set-wise
        if expected_summary:
            # Build mapping from output
            parsed_output: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
            all_rows_valid = True
            for r in output_rows:
                key = (r.get("athlete", ""), r.get("week_start", ""), r.get("week_end", ""))
                if not key[0] or not key[1] or not key[2]:
                    all_rows_valid = False
                    break
                # parse and normalize fields
                try:
                    val = {
                        "athlete": r["athlete"],
                        "week_start": r["week_start"],
                        "week_end": r["week_end"],
                        "sessions": int(float(r["sessions"])),
                        "total_duration_min": int(float(r["total_duration_min"])),
                        "avg_rpe": float(r["avg_rpe"]),
                        "sparring_sessions": int(float(r["sparring_sessions"])),
                        "avg_duration_min": float(r["avg_duration_min"]),
                    }
                    # round floats to 1 decimal for comparison tolerance
                    val["avg_rpe"] = float(f'{val["avg_rpe"]:.1f}')
                    val["avg_duration_min"] = float(f'{val["avg_duration_min"]:.1f}')
                except Exception:
                    all_rows_valid = False
                    break
                parsed_output[key] = val
            if all_rows_valid:
                # Ensure sets match
                if set(parsed_output.keys()) == set(expected_summary.keys()):
                    # Compare each row
                    rows_match = True
                    for k, exp in expected_summary.items():
                        got = parsed_output.get(k)
                        if got is None:
                            rows_match = False
                            break
                        for field in ["sessions", "total_duration_min", "avg_rpe", "sparring_sessions", "avg_duration_min"]:
                            if got[field] != exp[field]:
                                rows_match = False
                                break
                        if not rows_match:
                            break
                    if rows_match:
                        scores["analytics_weekly_summary_row_values"] = 1.0

    # Part D: athlete updates
    # Build per-athlete expected numbers from weekly summary output (if valid), else from our expected summary
    athlete_numbers: Dict[str, List[str]] = {}
    if output_rows:
        try:
            # Convert rows into dicts similar to expected_summary and reuse helper
            norm_rows = []
            for r in output_rows:
                norm_rows.append({
                    "athlete": r.get("athlete", ""),
                    "week_start": r.get("week_start", ""),
                    "week_end": r.get("week_end", ""),
                    "sessions": r.get("sessions", ""),
                    "total_duration_min": r.get("total_duration_min", ""),
                    "avg_rpe": r.get("avg_rpe", ""),
                    "sparring_sessions": r.get("sparring_sessions", ""),
                    "avg_duration_min": r.get("avg_duration_min", ""),
                })
            athlete_numbers = _extract_athlete_numbers_by_name(norm_rows)
        except Exception:
            athlete_numbers = {}
    if not athlete_numbers and expected_summary:
        # Fallback using expected_summary
        summary_rows = []
        for v in expected_summary.values():
            summary_rows.append({
                "athlete": v["athlete"],
                "week_start": v["week_start"],
                "week_end": v["week_end"],
                "sessions": v["sessions"],
                "total_duration_min": v["total_duration_min"],
                "avg_rpe": v["avg_rpe"],
                "sparring_sessions": v["sparring_sessions"],
                "avg_duration_min": v["avg_duration_min"],
            })
        athlete_numbers = _extract_athlete_numbers_by_name(summary_rows)

    updates_text = _read_text_safe(athlete_updates_p)
    if updates_text is not None and athlete_numbers:
        all_ok = True
        # split paragraphs by blank lines
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", updates_text) if p.strip()]
        # Create mapping from athlete to the paragraph that mentions them (first occurrence)
        tip_keywords = [
            "hydrate", "drink water", "sip water", "cool down", "cool-down", "cooldown", "shade",
            "rest", "easy pace", "pace", "short breaks", "breaks", "fluids", "sleep",
            "stretch", "warm-up", "warm up", "ice", "electrolyte", "salt", "sunscreen", "water"
        ]
        for athlete_name, nums in athlete_numbers.items():
            # Find a paragraph containing athlete name (case-insensitive)
            para = None
            for p in paragraphs:
                if re.search(rf"\b{re.escape(athlete_name)}\b", p, flags=re.IGNORECASE):
                    para = p
                    break
            if para is None:
                all_ok = False
                break
            # word count <= 120
            words = re.findall(r"\b\w+\b", para)
            if len(words) > 120:
                all_ok = False
                break
            # references at least one computed stat number
            # Check within the paragraph text
            stat_ref_ok = False
            for num in nums:
                # match number as a word or numeric token
                if re.search(rf"(?<!\d){re.escape(num)}(?!\d)", para):
                    stat_ref_ok = True
                    break
            if not stat_ref_ok:
                all_ok = False
                break
            # actionable tip present
            tips_ok = any(k in para.lower() for k in tip_keywords)
            if not tips_ok:
                all_ok = False
                break
        if all_ok:
            scores["athlete_updates_per_athlete_presence_and_content"] = 1.0

    # Staff update checks
    staff_text = _read_text_safe(staff_update_p)
    if staff_text is not None:
        words = re.findall(r"\b\w+\b", staff_text)
        length_ok = len(words) <= 120
        # Must mention each athlete by name
        mentions_ok = all(n in staff_text for n in ["Alex", "Jordan", "Sam"])
        # Avoid jargon: HRV, EOD, suboptimal, compliance
        jargon_bad = any(j.lower() in staff_text.lower() for j in ["hrv", "eod", "suboptimal", "compliance"])
        # Include key points: Jordan cooldown, Sam 15, volume reduction, data completeness
        jordan_ok = re.search(r"cool[- ]?down", staff_text, flags=re.IGNORECASE) is not None
        sam_ok = re.search(r"\b15\b|15%", staff_text) is not None
        volume_ok = re.search(r"reduce|reduction|lower|cut", staff_text, flags=re.IGNORECASE) is not None
        data_ok = re.search(r"data|logs", staff_text, flags=re.IGNORECASE) is not None
        if length_ok and mentions_ok and (not jargon_bad) and jordan_ok and sam_ok and volume_ok and data_ok:
            scores["staff_update_concise_and_plain_language"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()