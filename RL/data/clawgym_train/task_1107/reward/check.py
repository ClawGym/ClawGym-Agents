import json
import csv
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[Dict]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _parse_date_ymd(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def _to_int(s: str) -> Optional[int]:
    try:
        s = s.strip()
        if s == "":
            return None
        # Only allow integer-like values
        if re.fullmatch(r"[+-]?\d+", s):
            return int(s)
        return None
    except Exception:
        return None


def _to_float(s: str) -> Optional[float]:
    try:
        s = s.strip().replace(",", "")
        if s.startswith("$"):
            s = s[1:]
        return float(s)
    except Exception:
        return None


def _nearby_lines(lines: List[str], idx: int, radius: int = 2) -> List[str]:
    start = max(0, idx - radius)
    end = min(len(lines), idx + radius + 1)
    return lines[start:end]


def _clean_and_join_sales(titles_path: Path, sales_path: Path) -> Tuple[Optional[List[Dict]], Dict[str, int], List[Tuple[str, str]]]:
    """
    Returns:
      - cleaned_joined_rows: list of dicts with keys: order_id, date, title_id, store, channel, units(int), revenue_usd(float),
        title_name, genre, audience
      - error_counts: dict mapping error category to count
      - dropped_details: list of tuples (order_id, reason)
    """
    titles = _read_csv_dicts(titles_path)
    sales = _read_csv_dicts(sales_path)
    if titles is None or sales is None:
        return None, {}, []

    title_lookup = {}
    for t in titles:
        if "title_id" in t:
            title_lookup[t["title_id"]] = t

    cleaned = []
    error_counts = {"invalid date": 0, "non-numeric units": 0, "unknown title_id": 0}
    dropped_details = []

    for r in sales:
        order_id = r.get("order_id", "")
        date_str = r.get("date", "")
        title_id = r.get("title_id", "")
        units_str = r.get("units", "")
        revenue_str = r.get("revenue_usd", "")

        # date
        dt = _parse_date_ymd(date_str)
        if dt is None:
            error_counts["invalid date"] += 1
            dropped_details.append((order_id, "invalid date"))
            continue

        # units
        units = _to_int(units_str)
        if units is None:
            error_counts["non-numeric units"] += 1
            dropped_details.append((order_id, "non-numeric units"))
            continue

        # title_id in titles
        if title_id not in title_lookup:
            error_counts["unknown title_id"] += 1
            dropped_details.append((order_id, "unknown title_id"))
            continue

        revenue = _to_float(revenue_str)
        if revenue is None:
            # If revenue parsing fails (not specified to drop), treat as 0.0 deterministically
            revenue = 0.0

        trow = title_lookup[title_id]
        out = dict(r)
        out["units"] = units
        out["revenue_usd"] = revenue
        out["title_name"] = trow.get("title_name", "")
        out["genre"] = trow.get("genre", "")
        out["audience"] = trow.get("audience", "")
        cleaned.append(out)

    return cleaned, error_counts, dropped_details


def _aggregate_top_titles(cleaned_joined: List[Dict]) -> List[Dict]:
    by_title = {}
    for r in cleaned_joined:
        tid = r["title_id"]
        if tid not in by_title:
            by_title[tid] = {
                "title_id": tid,
                "title_name": r.get("title_name", ""),
                "genre": r.get("genre", ""),
                "total_units": 0,
                "total_revenue_usd": 0.0,
            }
        by_title[tid]["total_units"] += int(r.get("units", 0))
        by_title[tid]["total_revenue_usd"] += float(r.get("revenue_usd", 0.0))
    rows = list(by_title.values())
    rows.sort(
        key=lambda x: (-x["total_units"], -x["total_revenue_usd"], x["title_name"])
    )
    # add rank
    ranked = []
    for i, row in enumerate(rows[:5], start=1):
        ranked.append({
            "rank": i,
            "title_id": row["title_id"],
            "title_name": row["title_name"],
            "genre": row["genre"],
            "total_units": row["total_units"],
            "total_revenue_usd": row["total_revenue_usd"],
        })
    return ranked


def _best_selling_genre(cleaned_joined: List[Dict]) -> Optional[str]:
    by_genre = {}
    for r in cleaned_joined:
        g = r.get("genre", "")
        by_genre.setdefault(g, 0)
        by_genre[g] += int(r.get("units", 0))
    if not by_genre:
        return None
    best = sorted(by_genre.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return best[0]


def _age_to_band(age: Optional[int]) -> Optional[str]:
    if age is None:
        return None
    try:
        a = int(age)
    except Exception:
        return None
    if a < 18:
        return None
    if 18 <= a <= 24:
        return "18-24"
    if 25 <= a <= 34:
        return "25-34"
    if 35 <= a <= 44:
        return "35-44"
    if 45 <= a <= 54:
        return "45-54"
    return "55+"


def _top_segments(readers: List[Dict], fantasy_title_ids: List[str]) -> List[Dict]:
    # Filter readers who purchased any title in best-selling genre (Fantasy in our computed case)
    filtered = []
    for r in readers:
        purchased = r.get("purchased_title_ids", [])
        if not isinstance(purchased, list):
            continue
        if any(tid in fantasy_title_ids for tid in purchased):
            filtered.append(r)
    # Compute unique reader counts by (age_band, region)
    counts = {}
    for r in filtered:
        age = r.get("age", None)
        try:
            age_val = int(age)
        except Exception:
            age_val = None
        band = _age_to_band(age_val)
        region = r.get("region", "")
        if band is None or not region:
            continue
        key = (band, region)
        counts.setdefault(key, set()).add(r.get("reader_id", ""))

    unique_counts = {k: len(v) for k, v in counts.items()}

    band_order = {"18-24": 0, "25-34": 1, "35-44": 2, "45-54": 3, "55+": 4}
    items = [({"age_band": k[0], "region": k[1]}, v) for k, v in unique_counts.items()]
    items.sort(key=lambda kv: (-kv[1], band_order.get(kv[0]["age_band"], 99), kv[0]["region"]))
    out = []
    for i, (kdict, v) in enumerate(items[:3], start=1):
        out.append({
            "rank": i,
            "age_band": kdict["age_band"],
            "region": kdict["region"],
            "unique_readers": v
        })
    return out


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        # Inventory checks
        "inventory_file_exists": 0.0,
        "inventory_mentions_sales_csv": 0.0,
        "inventory_mentions_titles_csv": 0.0,
        "inventory_mentions_readers_jsonl": 0.0,
        "inventory_sales_includes_byte_size": 0.0,
        "inventory_titles_includes_byte_size": 0.0,
        "inventory_readers_includes_byte_size": 0.0,
        "inventory_sales_includes_row_count": 0.0,
        "inventory_titles_includes_row_count": 0.0,
        "inventory_readers_includes_line_count": 0.0,
        "inventory_includes_command_output": 0.0,
        "inventory_notes_discrepancies_section": 0.0,
        # Data quality log
        "data_quality_log_exists": 0.0,
        "data_quality_log_includes_o007_non_numeric_units": 0.0,
        "data_quality_log_includes_o009_invalid_date": 0.0,
        "data_quality_log_includes_o010_unknown_title_id": 0.0,
        "data_quality_log_summary_counts_correct": 0.0,
        # Aggregates: top titles
        "top_titles_file_exists": 0.0,
        "top_titles_header_correct": 0.0,
        "top_titles_row_count_top5": 0.0,
        "top_titles_content_correct": 0.0,
        # Aggregates: top segments
        "top_segments_file_exists": 0.0,
        "top_segments_header_correct": 0.0,
        "top_segments_row_count_top3": 0.0,
        "top_segments_content_correct": 0.0,
        # Report
        "report_file_exists": 0.0,
        "report_mentions_best_selling_genre": 0.0,
        "report_mentions_top_segment": 0.0,
        "report_has_four_sessions": 0.0,
        "report_rationale_cites_two_numeric_stats": 0.0,
        "report_references_data_quality_log": 0.0,
    }

    # Paths
    inventory_path = workspace / "output" / "inventory.md"
    data_quality_log_path = workspace / "output" / "audit" / "data_quality.log"
    top_titles_path = workspace / "output" / "aggregates" / "top_titles.csv"
    top_segments_path = workspace / "output" / "aggregates" / "top_segments.csv"
    report_path = workspace / "output" / "report" / "engagement_plan.md"

    input_sales = workspace / "input" / "sales_q1_2024.csv"
    input_titles = workspace / "input" / "titles.csv"
    input_readers = workspace / "input" / "readers.jsonl"

    # Inventory checks
    inv_text = _read_text(inventory_path)
    if inv_text is not None:
        scores["inventory_file_exists"] = 1.0
        inv_lines = inv_text.splitlines()
        inv_lower = inv_text.lower()

        # Mention files
        if "input/sales_q1_2024.csv" in inv_text:
            scores["inventory_mentions_sales_csv"] = 1.0
        if "input/titles.csv" in inv_text:
            scores["inventory_mentions_titles_csv"] = 1.0
        if "input/readers.jsonl" in inv_text:
            scores["inventory_mentions_readers_jsonl"] = 1.0

        def check_nearby_token(filename: str, token_regex: str) -> bool:
            ok = False
            try:
                for idx, line in enumerate(inv_lines):
                    if filename in line:
                        for neigh in _nearby_lines(inv_lines, idx, 2):
                            if re.search(token_regex, neigh, flags=re.IGNORECASE):
                                ok = True
                                break
                        if ok:
                            break
            except Exception:
                ok = False
            return ok

        # Byte sizes: look for number followed by 'byte' near file mention
        if check_nearby_token("input/sales_q1_2024.csv", r"\b\d+\s*bytes?\b"):
            scores["inventory_sales_includes_byte_size"] = 1.0
        if check_nearby_token("input/titles.csv", r"\b\d+\s*bytes?\b"):
            scores["inventory_titles_includes_byte_size"] = 1.0
        if check_nearby_token("input/readers.jsonl", r"\b\d+\s*bytes?\b"):
            scores["inventory_readers_includes_byte_size"] = 1.0

        # Record counts: CSV => rows, JSONL => lines
        if check_nearby_token("input/sales_q1_2024.csv", r"\b\d+\s*rows?\b"):
            scores["inventory_sales_includes_row_count"] = 1.0
        if check_nearby_token("input/titles.csv", r"\b\d+\s*rows?\b"):
            scores["inventory_titles_includes_row_count"] = 1.0
        if check_nearby_token("input/readers.jsonl", r"\b\d+\s*lines?\b"):
            scores["inventory_readers_includes_line_count"] = 1.0

        # Command output presence
        # Either contains a typical command invocation or a typical wc output line with digits + filename
        has_cmd = False
        if re.search(r"\bwc\s+-l\b", inv_text):
            has_cmd = True
        elif re.search(r"^\s*\d+\s+input/.*$", inv_text, flags=re.MULTILINE):
            has_cmd = True
        elif re.search(r"\bgrep\b|\bawk\b|\bsed\b|\bfind\b|\bls\s+-l\b", inv_text):
            has_cmd = True
        if has_cmd:
            scores["inventory_includes_command_output"] = 1.0

        # Discrepancies mention
        if "discrepanc" in inv_lower:
            scores["inventory_notes_discrepancies_section"] = 1.0

    # Compute expected cleaned/joined for later checks (if inputs available)
    cleaned_joined: Optional[List[Dict]] = None
    expected_error_counts: Dict[str, int] = {}
    dropped_details: List[Tuple[str, str]] = []

    if input_titles.exists() and input_sales.exists():
        cleaned_joined, expected_error_counts, dropped_details = _clean_and_join_sales(input_titles, input_sales)

    # Data quality log checks
    dq_text = _read_text(data_quality_log_path)
    if dq_text is not None:
        scores["data_quality_log_exists"] = 1.0
        dq_lower = dq_text.lower()

        # Expect dropped rows: O007 non-numeric units, O009 invalid date, O010 unknown title_id
        if "o007" in dq_lower and ("non" in dq_lower and "unit" in dq_lower):
            scores["data_quality_log_includes_o007_non_numeric_units"] = 1.0
        if "o009" in dq_lower and ("invalid" in dq_lower and "date" in dq_lower):
            scores["data_quality_log_includes_o009_invalid_date"] = 1.0
        # Accept either "unknown title_id" or "title_id not present"
        if "o010" in dq_lower and (("unknown" in dq_lower and "title_id" in dq_lower) or ("not present" in dq_lower and "title_id" in dq_lower)):
            scores["data_quality_log_includes_o010_unknown_title_id"] = 1.0

        # Summary counts: look for lines like 'invalid date: N', 'non-numeric units: M', 'unknown title_id: K'
        def find_count(label: str) -> Optional[int]:
            # search case-insensitive for 'label: number'
            pattern = re.compile(re.escape(label) + r"\s*:\s*(\d+)", flags=re.IGNORECASE)
            m = pattern.search(dq_text)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
            return None

        invalid_date_c = find_count("invalid date")
        non_numeric_c = find_count("non-numeric units")
        unknown_title_c = find_count("unknown title_id")

        # If we were able to compute expected errors, enforce exact counts; otherwise just check all three present.
        have_expected = expected_error_counts and ("invalid date" in expected_error_counts)
        if have_expected:
            ok = (
                invalid_date_c == expected_error_counts.get("invalid date", -1) and
                non_numeric_c == expected_error_counts.get("non-numeric units", -1) and
                unknown_title_c == expected_error_counts.get("unknown title_id", -1)
            )
            if ok:
                scores["data_quality_log_summary_counts_correct"] = 1.0
        else:
            # Fallback: presence of all three counts
            if all(c is not None for c in [invalid_date_c, non_numeric_c, unknown_title_c]):
                scores["data_quality_log_summary_counts_correct"] = 1.0

    # Aggregates: top_titles.csv
    top_titles_rows = _read_csv_dicts(top_titles_path)
    if top_titles_rows is not None:
        scores["top_titles_file_exists"] = 1.0
        # Header correctness
        try:
            with top_titles_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline().strip()
            expected_header = "rank,title_id,title_name,genre,total_units,total_revenue_usd"
            if header_line == expected_header:
                scores["top_titles_header_correct"] = 1.0
        except Exception:
            pass

        # Row count top 5
        if len(top_titles_rows) == 5:
            scores["top_titles_row_count_top5"] = 1.0

        # Content correctness: compare with expected computed from cleaned_joined
        if cleaned_joined is not None:
            expected_top = _aggregate_top_titles(cleaned_joined)
            def normalize_float(s):
                if isinstance(s, (int, float)):
                    return float(s)
                return _to_float(str(s))

            ok_content = True
            if len(top_titles_rows) != len(expected_top):
                ok_content = False
            else:
                for i, row in enumerate(top_titles_rows):
                    exp = expected_top[i]
                    # compare rank, title_id, title_name, genre, total_units, total_revenue_usd
                    try:
                        rank_ok = str(row.get("rank", "")).strip() == str(exp["rank"])
                        tid_ok = str(row.get("title_id", "")).strip() == exp["title_id"]
                        tname_ok = str(row.get("title_name", "")).strip() == exp["title_name"]
                        genre_ok = str(row.get("genre", "")).strip() == exp["genre"]
                        units_ok = _to_int(str(row.get("total_units", "")).strip()) == int(exp["total_units"])
                        rev = normalize_float(row.get("total_revenue_usd", ""))
                        rev_ok = (rev is not None) and (abs(rev - float(exp["total_revenue_usd"])) <= 0.01)
                        if not (rank_ok and tid_ok and tname_ok and genre_ok and units_ok and rev_ok):
                            ok_content = False
                            break
                    except Exception:
                        ok_content = False
                        break
            if ok_content:
                scores["top_titles_content_correct"] = 1.0

    # Aggregates: top_segments.csv
    top_segments_rows = _read_csv_dicts(top_segments_path)
    if top_segments_rows is not None:
        scores["top_segments_file_exists"] = 1.0
        try:
            with top_segments_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline().strip()
            expected_header = "rank,age_band,region,unique_readers"
            if header_line == expected_header:
                scores["top_segments_header_correct"] = 1.0
        except Exception:
            pass

        if len(top_segments_rows) == 3:
            scores["top_segments_row_count_top3"] = 1.0

        # Content correctness: compute expected based on best-selling genre from cleaned data and readers.jsonl
        readers = _read_jsonl(input_readers)
        if cleaned_joined is not None and readers is not None:
            best_genre = _best_selling_genre(cleaned_joined)
            # Identify title_ids of best-selling genre
            if best_genre is not None:
                best_title_ids = sorted({r["title_id"] for r in cleaned_joined if r.get("genre", "") == best_genre})
                expected_segments = _top_segments(readers, best_title_ids)
                ok_content = True
                if len(top_segments_rows) != len(expected_segments):
                    ok_content = False
                else:
                    band_order = {"18-24": 0, "25-34": 1, "35-44": 2, "45-54": 3, "55+": 4}
                    for i, row in enumerate(top_segments_rows):
                        exp = expected_segments[i]
                        try:
                            rank_ok = str(row.get("rank", "")).strip() == str(exp["rank"])
                            band_ok = str(row.get("age_band", "")).strip() == exp["age_band"]
                            region_ok = str(row.get("region", "")).strip() == exp["region"]
                            uniq_ok = _to_int(str(row.get("unique_readers", "")).strip()) == int(exp["unique_readers"])
                            # also ensure ordering tie-breakers implicitly through exact order match
                            if not (rank_ok and band_ok and region_ok and uniq_ok):
                                ok_content = False
                                break
                        except Exception:
                            ok_content = False
                            break
                if ok_content:
                    scores["top_segments_content_correct"] = 1.0

    # Report checks
    rep_text = _read_text(report_path)
    if rep_text is not None:
        scores["report_file_exists"] = 1.0
        rep_lower = rep_text.lower()

        # Compute expected best-selling genre and top segment from inputs to check mentions
        best_genre = None
        top_segment = None
        if cleaned_joined is not None:
            best_genre = _best_selling_genre(cleaned_joined)
        readers = _read_jsonl(input_readers)
        if cleaned_joined is not None and readers is not None and best_genre is not None:
            best_title_ids = sorted({r["title_id"] for r in cleaned_joined if r.get("genre", "") == best_genre})
            expected_segments = _top_segments(readers, best_title_ids)
            if expected_segments:
                top_segment = expected_segments[0]

        # Mentions best-selling genre
        if best_genre and best_genre.lower() in rep_lower:
            scores["report_mentions_best_selling_genre"] = 1.0

        # Mentions top segment (age_band and region)
        if top_segment:
            band = top_segment["age_band"]
            region = top_segment["region"]
            if (band in rep_text) and (region in rep_text):
                scores["report_mentions_top_segment"] = 1.0

        # Four sessions (heuristic): count lines that look like "Session/Email" or bullet/numbered with sentence.
        lines = rep_text.splitlines()
        session_like = 0
        for ln in lines:
            ln_stripped = ln.strip()
            if not ln_stripped:
                continue
            is_bullet = ln_stripped.startswith(("-", "*"))
            is_numbered = bool(re.match(r"^\d+[\.\)]\s+", ln_stripped))
            mentions_session = ("session" in ln_stripped.lower() or "email" in ln_stripped.lower())
            has_sentence = "." in ln_stripped
            if (is_bullet or is_numbered or mentions_session) and has_sentence:
                session_like += 1
        if session_like >= 4:
            scores["report_has_four_sessions"] = 1.0

        # Rationale cites at least two numeric stats from aggregates:
        # Build a set of expected numeric stats from our aggregates
        expected_numbers = set()
        if cleaned_joined is not None:
            # From top titles totals
            for agg in _aggregate_top_titles(cleaned_joined):
                expected_numbers.add(int(agg["total_units"]))
                # add rounded revenue
                expected_numbers.add(round(float(agg["total_revenue_usd"]), 2))
            # Best genre total units
            genre_totals = {}
            for r in cleaned_joined:
                g = r.get("genre", "")
                genre_totals[g] = genre_totals.get(g, 0) + int(r.get("units", 0))
            for v in genre_totals.values():
                expected_numbers.add(int(v))
        if readers is not None and cleaned_joined is not None:
            best_genre = _best_selling_genre(cleaned_joined)
            if best_genre:
                bs_ids = sorted({r["title_id"] for r in cleaned_joined if r.get("genre", "") == best_genre})
                segs = _top_segments(readers, bs_ids)
                for s in segs:
                    expected_numbers.add(int(s["unique_readers"]))

        # Extract numbers present in report (integers and decimals)
        found_nums = []
        for m in re.findall(r"\b\d+(?:\.\d+)?\b", rep_text):
            try:
                if "." in m:
                    found_nums.append(round(float(m), 2))
                else:
                    found_nums.append(int(m))
            except Exception:
                continue

        matches = 0
        for n in found_nums:
            if n in expected_numbers:
                matches += 1
            if matches >= 2:
                break
        if matches >= 2:
            scores["report_rationale_cites_two_numeric_stats"] = 1.0

        # References data_quality.log
        if "data quality notes" in rep_lower and "output/audit/data_quality.log" in rep_lower:
            scores["report_references_data_quality_log"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()