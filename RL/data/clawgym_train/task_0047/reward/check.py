import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _write_json(obj: dict) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"


def _parse_yaml_simple(path: Path) -> Optional[dict]:
    """
    Minimal YAML parser for the known structure in input/categories.yaml.
    Returns dict with keys: categories (list of keys), currency_symbols (list), section_markers (list).
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    result = {"categories": [], "currency_symbols": [], "section_markers": []}
    current_section = None
    current_category = None
    in_keywords = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Top-level sections
        if stripped.startswith("categories:"):
            current_section = "categories"
            i += 1
            continue
        if stripped.startswith("currency_symbols:"):
            current_section = "currency_symbols"
            i += 1
            continue
        if stripped.startswith("section_markers:"):
            current_section = "section_markers"
            i += 1
            continue

        if current_section == "categories":
            # Look for "  <key>:" lines
            m = re.match(r"\s{2}([a-zA-Z0-9_]+):\s*$", line)
            if m:
                current_category = m.group(1)
                if current_category not in result["categories"]:
                    result["categories"].append(current_category)
                in_keywords = False
                i += 1
                continue
            # Track keywords, though we don't need to extract them
            if re.match(r"\s{4}keywords:\s*$", line):
                in_keywords = True
                i += 1
                continue
            if in_keywords:
                # entries like "      - keyword"
                if re.match(r"\s{6}-\s+.+", line):
                    i += 1
                    continue
                else:
                    in_keywords = False
                    # fall-through to other processing
        elif current_section in ("currency_symbols", "section_markers"):
            m = re.match(r"\s*-\s+(.+?)\s*$", line)
            if m:
                val = m.group(1)
                result[current_section].append(val)
                i += 1
                continue
        i += 1

    return result


def _slugify(text: str) -> str:
    # Lowercase, replace non-alphanumeric with underscore, collapse underscores, strip
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    return s


def _safe_float(val: str) -> Optional[float]:
    try:
        if val is None:
            return None
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        entries = []
        with path.open("r", encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                s = line.strip()
                if not s:
                    continue
                obj = json.loads(s)
                if not isinstance(obj, dict):
                    return None
                entries.append(obj)
        return entries
    except Exception:
        return None


def _group_summary(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str], Dict[str, float]]:
    groups: Dict[Tuple[str, str], List[float]] = {}
    for r in rows:
        j = r.get("jurisdiction", "")
        c = r.get("category", "")
        av = _safe_float(r.get("amount_value", ""))
        if j == "" or c == "" or av is None:
            continue
        groups.setdefault((j, c), []).append(av)
    result: Dict[Tuple[str, str], Dict[str, float]] = {}
    for key, vals in groups.items():
        vals_sorted = sorted(vals)
        count = len(vals_sorted)
        minv = vals_sorted[0]
        maxv = vals_sorted[-1]
        # median
        if count == 0:
            med = 0.0
        elif count % 2 == 1:
            med = vals_sorted[count // 2]
        else:
            med = (vals_sorted[count // 2 - 1] + vals_sorted[count // 2]) / 2.0
        result[key] = {
            "count": float(count),
            "min_amount": float(minv),
            "median_amount": float(med),
            "max_amount": float(maxv),
        }
    return result


def _parse_summary_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    return _read_csv_dicts(path)


def _http_url(s: str) -> bool:
    try:
        u = urlparse(s)
        return u.scheme in ("http", "https") and bool(u.netloc)
    except Exception:
        return False


def _domain_official(url: str) -> bool:
    try:
        u = urlparse(url)
        host = (u.netloc or "").lower()
        # Official heuristics
        if ".gov" in host:
            return True
        # Known city/state government domains often used
        if any(x in host for x in ["nyc.gov", "cityofchicago.org", "chicago.gov", "illinois.gov", "ny.gov", "state.ny.us"]):
            return True
        return False
    except Exception:
        return False


def _tolerance_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _extract_table_lines(md_text: str) -> List[str]:
    # Return lines that look like Markdown table rows (contain at least two pipes and not just separator like |---|)
    lines = []
    for line in md_text.splitlines():
        if "|" in line and line.count("|") >= 2:
            # skip separators
            sep = line.strip().replace(" ", "")
            if re.fullmatch(r"\|?:?-+:?\|?:?-+:?\|?.*", sep):
                # likely a separator line; keep out
                continue
            lines.append(line)
    return lines


def _normalize_amount_patterns(amount: float) -> List[re.Pattern]:
    # Create regex patterns to match amounts like 1,234.00, $1,234, 1234, $1234
    parts = []
    # integer representation
    int_amt = int(round(amount))
    int_str = f"{int_amt}"
    # with commas
    int_with_commas = "{:,}".format(int_amt)
    patterns = [
        rf"\$?\s*{re.escape(int_str)}(\.00)?",
        rf"\$?\s*{re.escape(int_with_commas)}(\.00)?",
        rf"\$\s*{re.escape(int_str)}(\.00)?",
        rf"\$\s*{re.escape(int_with_commas)}(\.00)?",
    ]
    compiled = [re.compile(p) for p in patterns]
    return compiled


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "raw_downloads_per_jurisdiction": 0.0,
        "parsed_texts_per_jurisdiction": 0.0,
        "structured_csv_valid_schema": 0.0,
        "structured_rows_valid": 0.0,
        "jurisdictions_present_in_structured": 0.0,
        "summary_csv_correctness": 0.0,
        "logs_search_log_per_jurisdiction": 0.0,
        "logs_official_domain_preference": 0.0,
        "structured_source_urls_in_logs": 0.0,
        "report_jurisdictions_and_sources": 0.0,
        "report_top5_matches": 0.0,
    }

    # Load inputs
    juris_path = workspace / "input" / "jurisdictions.csv"
    yaml_path = workspace / "input" / "categories.yaml"
    juris_rows = _read_csv_dicts(juris_path)
    yaml_data = _parse_yaml_simple(yaml_path)

    if not juris_rows or not isinstance(juris_rows, list):
        # With no jurisdictions, many checks can't proceed; keep zeros.
        return scores

    jurisdictions = []
    slugs = {}
    for r in juris_rows:
        name = r.get("jurisdiction", "") or ""
        if name.strip() == "":
            continue
        jurisdictions.append(name)
        slugs[name] = _slugify(name)

    # Check raw downloads presence
    raw_hits = 0
    for j in jurisdictions:
        slug = slugs[j]
        raw_dir = workspace / "data" / "raw" / slug
        found = False
        if raw_dir.exists() and raw_dir.is_dir():
            for p in raw_dir.rglob("*"):
                if p.is_file() and p.suffix.lower() in (".pdf", ".html", ".htm"):
                    found = True
                    break
        if found:
            raw_hits += 1
    if jurisdictions:
        scores["raw_downloads_per_jurisdiction"] = raw_hits / len(jurisdictions)

    # Check parsed texts
    parsed_hits = 0
    for j in jurisdictions:
        slug = slugs[j]
        parsed_file = workspace / "data" / "parsed" / f"{slug}.txt"
        txt = _read_text(parsed_file)
        if txt is not None and len(txt.strip()) > 0:
            parsed_hits += 1
    if jurisdictions:
        scores["parsed_texts_per_jurisdiction"] = parsed_hits / len(jurisdictions)

    # Structured CSV schema and rows validation
    structured_path = workspace / "data" / "structured" / "violations.csv"
    structured_rows = _read_csv_dicts(structured_path)
    expected_cols = [
        "jurisdiction",
        "source_url",
        "rule_ref",
        "category",
        "description",
        "amount_value",
        "amount_text",
        "currency",
        "captured_sentence",
    ]
    if structured_rows is not None and isinstance(structured_rows, list) and len(structured_rows) >= 0:
        # Validate schema
        try:
            with structured_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
        except Exception:
            header = []
        if set(header) == set(expected_cols) and len(header) == len(expected_cols):
            scores["structured_csv_valid_schema"] = 1.0
        else:
            scores["structured_csv_valid_schema"] = 0.0

        # Validate rows
        total = len(structured_rows)
        valid = 0
        currency_ok_values = set()
        if yaml_data and isinstance(yaml_data.get("currency_symbols"), list):
            for sym in yaml_data["currency_symbols"]:
                currency_ok_values.add(sym.upper())
        # Also accept literal USD as per example
        currency_ok_values.update({"USD", "$"})
        category_keys = set(yaml_data["categories"]) if yaml_data and isinstance(yaml_data.get("categories"), list) else set()

        rows_per_jurisdiction: Dict[str, int] = {}
        source_urls: List[Tuple[str, str]] = []  # (jurisdiction, source_url)
        for r in structured_rows:
            ok = True
            j = r.get("jurisdiction", "")
            c = r.get("category", "")
            source = r.get("source_url", "")
            rule_ref = r.get("rule_ref", "")
            desc = r.get("description", "")
            amount_value = r.get("amount_value", "")
            amount_text = r.get("amount_text", "")
            currency = r.get("currency", "")
            captured = r.get("captured_sentence", "")

            # jurisdiction in list
            if j not in jurisdictions:
                ok = False
            # category in yaml
            if not category_keys or c not in category_keys:
                ok = False
            # source_url valid http(s)
            if not _http_url(source):
                ok = False
            # rule_ref can be empty; ensure it's a string
            if rule_ref is None:
                ok = False
            # description non-empty
            if not isinstance(desc, str) or len(desc.strip()) == 0:
                ok = False
            # amount_value numeric positive
            av = _safe_float(amount_value)
            if av is None or av <= 0:
                ok = False
            # amount_text must contain a digit and ideally a currency indicator
            if not isinstance(amount_text, str) or not re.search(r"\d", amount_text):
                ok = False
            # currency acceptable
            curr_upper = (currency or "").upper()
            if curr_upper not in currency_ok_values:
                ok = False
            # captured_sentence includes amount_text
            if not isinstance(captured, str) or amount_text not in captured:
                ok = False

            if ok:
                valid += 1
            # count per jurisdiction
            rows_per_jurisdiction[j] = rows_per_jurisdiction.get(j, 0) + 1
            # source url map
            if _http_url(source):
                source_urls.append((j, source))

        scores["structured_rows_valid"] = (valid / total) if total > 0 else 0.0

        # jurisdictions present in structured
        present_hits = 0
        for j in jurisdictions:
            if rows_per_jurisdiction.get(j, 0) > 0:
                present_hits += 1
        if jurisdictions:
            scores["jurisdictions_present_in_structured"] = present_hits / len(jurisdictions)
    else:
        scores["structured_csv_valid_schema"] = 0.0
        scores["structured_rows_valid"] = 0.0
        scores["jurisdictions_present_in_structured"] = 0.0
        structured_rows = None

    # Summary CSV correctness
    if structured_rows is not None and len(structured_rows) > 0:
        computed = _group_summary(structured_rows)
        summary_path = workspace / "data" / "summary" / "violations_summary.csv"
        summary_rows = _parse_summary_csv(summary_path)
        if summary_rows is None:
            scores["summary_csv_correctness"] = 0.0
        else:
            # Build dict from summary file
            file_groups: Dict[Tuple[str, str], Dict[str, float]] = {}
            malformed = False
            for r in summary_rows:
                j = r.get("jurisdiction", "")
                c = r.get("category", "")
                cnt = _safe_float(r.get("count", ""))
                minv = _safe_float(r.get("min_amount", ""))
                medv = _safe_float(r.get("median_amount", ""))
                maxv = _safe_float(r.get("max_amount", ""))
                if j == "" or c == "" or None in (cnt, minv, medv, maxv):
                    malformed = True
                    break
                file_groups[(j, c)] = {
                    "count": cnt,
                    "min_amount": minv,
                    "median_amount": medv,
                    "max_amount": maxv,
                }
            if malformed:
                scores["summary_csv_correctness"] = 0.0
            else:
                # Compare both sets
                all_keys = set(computed.keys()) | set(file_groups.keys())
                if len(all_keys) == 0:
                    # No groups at all; treat as mismatch
                    scores["summary_csv_correctness"] = 0.0
                else:
                    matches = 0
                    for key in all_keys:
                        cv = computed.get(key)
                        fv = file_groups.get(key)
                        if cv is None or fv is None:
                            continue
                        ok = True
                        # count must match exactly as integer
                        if not _tolerance_equal(cv["count"], fv["count"]):
                            ok = False
                        if not _tolerance_equal(cv["min_amount"], fv["min_amount"]):
                            ok = False
                        if not _tolerance_equal(cv["median_amount"], fv["median_amount"]):
                            ok = False
                        if not _tolerance_equal(cv["max_amount"], fv["max_amount"]):
                            ok = False
                        if ok:
                            matches += 1
                    scores["summary_csv_correctness"] = matches / len(all_keys)
    else:
        scores["summary_csv_correctness"] = 0.0

    # Logs validation
    logs_path = workspace / "logs" / "search_log.jsonl"
    logs = _load_jsonl(logs_path)
    per_jurisdiction_valid = 0
    official_domain_hits = 0
    structured_rows_list = structured_rows if structured_rows is not None else []
    # Map jurisdiction -> set of candidate URLs from logs, chosen URLs, downloaded paths
    juris_log_candidates: Dict[str, set] = {j: set() for j in jurisdictions}
    juris_log_chosen: Dict[str, List[str]] = {j: [] for j in jurisdictions}
    juris_log_paths: Dict[str, List[Path]] = {j: [] for j in jurisdictions}
    if logs is not None:
        # Preprocess logs
        # Validate each jurisdiction has at least one valid log entry
        for j in jurisdictions:
            j_logs = [e for e in logs if isinstance(e, dict) and e.get("jurisdiction") == j]
            valid_any = False
            official_any = False
            for e in j_logs:
                timestamp = e.get("timestamp")
                query = e.get("query")
                engine = e.get("engine")
                candidate_urls = e.get("candidate_urls")
                chosen_url = e.get("chosen_url")
                status = e.get("status")
                downloaded_path = e.get("downloaded_path")
                # Basic field presence
                if not isinstance(timestamp, str) or not timestamp.strip():
                    continue
                if not isinstance(query, str) or not query.strip():
                    continue
                if not isinstance(engine, str) or not engine.strip():
                    continue
                if not isinstance(candidate_urls, list):
                    continue
                if not isinstance(chosen_url, str) or not chosen_url.strip() or not _http_url(chosen_url):
                    continue
                # chosen_url should be among candidates (strict)
                if chosen_url not in candidate_urls:
                    continue
                # downloaded_path exists
                if not isinstance(downloaded_path, str) or not downloaded_path.strip():
                    continue
                dp = Path(downloaded_path)
                # Make dp absolute relative to workspace if not absolute
                if not dp.is_absolute():
                    dp = (workspace / dp).resolve()
                if not dp.exists() or not dp.is_file():
                    continue
                # If passes all, it's a valid log for this jurisdiction
                valid_any = True
                # Official domain preference
                if _domain_official(chosen_url):
                    official_any = True
                juris_log_candidates[j].update([u for u in candidate_urls if isinstance(u, str)])
                juris_log_chosen[j].append(chosen_url)
                juris_log_paths[j].append(dp)
            if valid_any:
                per_jurisdiction_valid += 1
            if official_any:
                official_domain_hits += 1
        if jurisdictions:
            scores["logs_search_log_per_jurisdiction"] = per_jurisdiction_valid / len(jurisdictions)
            scores["logs_official_domain_preference"] = official_domain_hits / len(jurisdictions)
    else:
        scores["logs_search_log_per_jurisdiction"] = 0.0
        scores["logs_official_domain_preference"] = 0.0

    # Cross-file consistency: structured source_url should exist in logs for that jurisdiction
    if structured_rows_list and logs is not None:
        total = 0
        ok = 0
        for r in structured_rows_list:
            j = r.get("jurisdiction", "")
            src = r.get("source_url", "")
            if j not in jurisdictions or not _http_url(src):
                continue
            total += 1
            candidates = juris_log_candidates.get(j, set())
            chosens = set(juris_log_chosen.get(j, []))
            if src in candidates or src in chosens:
                ok += 1
        scores["structured_source_urls_in_logs"] = (ok / total) if total > 0 else 0.0
    else:
        scores["structured_source_urls_in_logs"] = 0.0

    # Report checks
    report_path = workspace / "reports" / "summary.md"
    report_text = _read_text(report_path)
    if report_text is None:
        scores["report_jurisdictions_and_sources"] = 0.0
        scores["report_top5_matches"] = 0.0
    else:
        # Jurisdictions and sources listed
        j_hits = 0
        for j in jurisdictions:
            # Jurisdiction name present
            name_present = j in report_text
            # Any chosen URL present
            urls = juris_log_chosen.get(j, [])
            url_present = False
            for u in urls:
                if u and u in report_text:
                    url_present = True
                    break
            if name_present and url_present:
                j_hits += 1
        if jurisdictions:
            scores["report_jurisdictions_and_sources"] = j_hits / len(jurisdictions)
        else:
            scores["report_jurisdictions_and_sources"] = 0.0

        # Top 5 highest fines table consistency
        top_match_score = 0.0
        if structured_rows_list:
            # Compute top 5 by amount_value descending
            enriched = []
            for r in structured_rows_list:
                av = _safe_float(r.get("amount_value", ""))
                if av is None:
                    continue
                enriched.append((av, r.get("jurisdiction", ""), r.get("category", "")))
            enriched.sort(key=lambda x: (-x[0], x[1], x[2]))
            top5 = enriched[:5]
            # Parse table-like lines
            table_lines = _extract_table_lines(report_text)
            # Ensure at least 5 data-like lines
            if len(table_lines) >= 5:
                matches = 0
                for amount, jur, cat in top5:
                    # search for a line that contains jur and cat and amount pattern
                    pats = _normalize_amount_patterns(amount)
                    found = False
                    for line in table_lines:
                        if jur in line and cat in line:
                            for pat in pats:
                                if pat.search(line):
                                    found = True
                                    break
                        if found:
                            break
                    if found:
                        matches += 1
                top_match_score = matches / max(1, len(top5))
            else:
                top_match_score = 0.0
        else:
            top_match_score = 0.0
        scores["report_top5_matches"] = top_match_score

    # Clip to [0.0, 1.0]
    for k, v in list(scores.items()):
        try:
            if not isinstance(v, float) or math.isnan(v) or v < 0.0:
                scores[k] = 0.0
            elif v > 1.0:
                scores[k] = 1.0
        except Exception:
            scores[k] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(_write_json(result))


if __name__ == "__main__":
    main()