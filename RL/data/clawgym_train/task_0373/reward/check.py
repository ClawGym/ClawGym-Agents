import json
import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        txt = _read_text(path)
        if txt is None:
            return None, "unreadable"
        return json.loads(txt), None
    except Exception as e:
        return None, f"json_error:{e}"


def _parse_yaml_release_tag(path: Path) -> Optional[str]:
    """
    Small YAML extractor for key: release_tag. Accepts quoted or unquoted values on a single line.
    """
    text = _read_text(path)
    if text is None:
        return None
    for line in text.splitlines():
        m = re.match(r'^\s*release_tag\s*:\s*["\']?([^"\']+?)["\']?\s*$', line)
        if m:
            return m.group(1).strip()
    return None


def _read_csv_rows(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows, None
    except Exception as e:
        return None, f"csv_error:{e}"


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s2 = s.replace("Z", "+00:00")
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _compute_residential_summary(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    res_rows = [r for r in rows if r.get("type") == "Residential"]
    if not res_rows:
        return None
    prices = []
    pps_list = []
    count_active = 0
    count_pending = 0
    for r in res_rows:
        try:
            price = float(str(r.get("price", "")).strip())
            sqft = float(str(r.get("sqft", "")).strip())
        except Exception:
            return None
        if sqft == 0:
            return None
        prices.append(price)
        pps_list.append(price / sqft)
        status = r.get("status", "")
        if status == "Active":
            count_active += 1
        if status == "Pending":
            count_pending += 1
    n = len(res_rows)
    avg_price = round(sum(prices) / n, 2)
    sp = sorted(prices)
    if n % 2 == 1:
        median_price = round(sp[n // 2], 2)
    else:
        median_price = round((sp[n // 2 - 1] + sp[n // 2]) / 2.0, 2)
    avg_pps = round(sum(pps_list) / n, 2)
    return {
        "total_residential": int(n),
        "avg_price": avg_price,
        "median_price": median_price,
        "avg_price_per_sqft": avg_pps,
        "count_active": int(count_active),
        "count_pending": int(count_pending),
    }


def _format_number_patterns(value: Any) -> List[re.Pattern]:
    """
    Build tolerant regex patterns for matching numbers in prose:
    - For ints: allow "1234" or "1,234"
    - For floats: match with exactly two decimals (rounded) with optional thousands commas
    """
    patterns = []
    if isinstance(value, int) or (isinstance(value, float) and float(value).is_integer()):
        iv = int(value)
        plain = f"{iv}"
        with_commas = "{:,}".format(iv)
        patterns.append(re.compile(re.escape(plain)))
        patterns.append(re.compile(re.escape(with_commas)))
    else:
        fv = float(value)
        s = f"{fv:.2f}"
        int_part, frac_part = s.split(".")
        try:
            int_num = int(int_part)
        except Exception:
            int_num = int(float(int_part))
        with_commas = f"{int_num:,}.{frac_part}"
        patterns.append(re.compile(re.escape(s)))
        patterns.append(re.compile(re.escape(with_commas)))
    return patterns


def _extract_section(text: str, header: str) -> Optional[str]:
    """
    Extract section text for '## {header}' until next '## ' or end.
    """
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == f"## {header}":
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].startswith("## "):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "release_dir_exists": 0.0,
        "listings_summary_json_correct": 0.0,
        "mortgage_snapshot_saved": 0.0,
        "mortgage_json_valid_and_consistent": 0.0,
        "brief_sections_order_and_headers": 0.0,
        "brief_summary_values_and_exclusion": 0.0,
        "brief_mortgage_section_content": 0.0,
        "brief_data_sources_listed": 0.0,
    }

    pipeline_yaml = workspace / "pipeline" / "release.yaml"
    listings_csv = workspace / "input" / "listings.csv"
    mortgage_html = workspace / "data" / "raw" / "mortgage_rate.html"
    mortgage_json_path = workspace / "data" / "processed" / "mortgage_rate.json"
    brief_md = workspace / "docs" / "market-brief.md"

    release_tag = _parse_yaml_release_tag(pipeline_yaml)
    if release_tag:
        release_dir = workspace / "build" / "release" / release_tag
        if release_dir.exists() and release_dir.is_dir():
            scores["release_dir_exists"] = 1.0

    expected_summary = None
    rows, err = _read_csv_rows(listings_csv)
    if rows is not None:
        expected_summary = _compute_residential_summary(rows)

    if release_tag:
        summary_json_path = workspace / "build" / "release" / release_tag / "listings_summary.json"
        summary_data, jerr = _load_json(summary_json_path)
        if summary_data is not None and expected_summary is not None:
            expected_keys = {
                "total_residential",
                "avg_price",
                "median_price",
                "avg_price_per_sqft",
                "count_active",
                "count_pending",
            }
            actual_keys = set(summary_data.keys())
            if actual_keys == expected_keys:
                ok = True
                if not isinstance(summary_data["total_residential"], int):
                    ok = False
                if not isinstance(summary_data["count_active"], int):
                    ok = False
                if not isinstance(summary_data["count_pending"], int):
                    ok = False

                def _num_equal(a: Any, b: Any) -> bool:
                    try:
                        return round(float(a), 2) == round(float(b), 2)
                    except Exception:
                        return False

                ok = ok and (summary_data["total_residential"] == expected_summary["total_residential"])
                ok = ok and _num_equal(summary_data["avg_price"], expected_summary["avg_price"])
                ok = ok and _num_equal(summary_data["median_price"], expected_summary["median_price"])
                ok = ok and _num_equal(summary_data["avg_price_per_sqft"], expected_summary["avg_price_per_sqft"])
                ok = ok and (summary_data["count_active"] == expected_summary["count_active"])
                ok = ok and (summary_data["count_pending"] == expected_summary["count_pending"])
                if ok:
                    scores["listings_summary_json_correct"] = 1.0

    html_text = _read_text(mortgage_html)
    if html_text is not None and len(html_text.strip()) > 0:
        scores["mortgage_snapshot_saved"] = 1.0

    mortgage_data, merr = _load_json(mortgage_json_path)
    if mortgage_data is not None and html_text is not None:
        required_fields = [
            "source_domain",
            "source_label",
            "page_snapshot_path",
            "retrieved_at",
            "rate_text",
            "context_snippet",
        ]
        has_fields = all(k in mortgage_data for k in required_fields)
        ok = has_fields
        if ok:
            ok = ok and (mortgage_data.get("source_domain") == "freddiemac.com")
            ok = ok and (mortgage_data.get("source_label") == "Freddie Mac Primary Mortgage Market Survey")
            ok = ok and (mortgage_data.get("page_snapshot_path") == "data/raw/mortgage_rate.html")
            rt = mortgage_data.get("retrieved_at")
            ok = ok and _is_iso8601(rt)
            rate_text = mortgage_data.get("rate_text")
            if not isinstance(rate_text, str) or not rate_text.strip():
                ok = False
            else:
                ok = ok and ("%" in rate_text)
                ok = ok and (rate_text in html_text)
            ctx = mortgage_data.get("context_snippet")
            if not isinstance(ctx, str) or len(ctx) < 100:
                ok = False
            else:
                ctx_lower = ctx.lower()
                ok = ok and ("30-year" in ctx_lower) and ("fixed" in ctx_lower)
                ok = ok and (isinstance(rate_text, str) and rate_text in ctx)
                ok = ok and (ctx in html_text)
        if ok:
            scores["mortgage_json_valid_and_consistent"] = 1.0

    brief_text = _read_text(brief_md)
    if brief_text is not None and release_tag:
        lines = brief_text.splitlines()
        first_line = lines[0].strip() if lines else ""
        ok_head = (first_line == f"# Residential Release: {release_tag}")

        def _find_header_index(h: str) -> int:
            for i, ln in enumerate(lines):
                if ln.strip() == f"## {h}":
                    return i
            return -1

        idx_summary = _find_header_index("Summary")
        idx_mortgage = _find_header_index("Mortgage Rate (Freddie Mac 30-year fixed)")
        idx_sources = _find_header_index("Data Sources")

        ok_order = all(i >= 0 for i in [idx_summary, idx_mortgage, idx_sources]) and (idx_summary < idx_mortgage < idx_sources)
        if ok_head and ok_order:
            scores["brief_sections_order_and_headers"] = 1.0

        summary_section = _extract_section(brief_text, "Summary")
        if summary_section is not None and expected_summary is not None:
            labels = [
                "total_residential",
                "avg_price",
                "median_price",
                "avg_price_per_sqft",
                "count_active",
                "count_pending",
            ]
            labels_ok = all(lbl in summary_section for lbl in labels)
            excl_ok = ("excluded" in summary_section.lower() and "commercial" in summary_section.lower())
            values_ok = True
            for key in labels:
                val = expected_summary[key]
                patterns = _format_number_patterns(val)
                found_any = any(p.search(summary_section) for p in patterns)
                if not found_any:
                    values_ok = False
                    break
            if labels_ok and excl_ok and values_ok:
                scores["brief_summary_values_and_exclusion"] = 1.0

        mortgage_section = _extract_section(brief_text, "Mortgage Rate (Freddie Mac 30-year fixed)")
        if mortgage_section is not None and mortgage_data is not None:
            rate_text = mortgage_data.get("rate_text")
            retrieved_at = mortgage_data.get("retrieved_at")
            snap_path = "data/raw/mortgage_rate.html"
            ok = True
            if not (isinstance(rate_text, str) and rate_text in mortgage_section):
                ok = False
            if not (isinstance(retrieved_at, str) and retrieved_at in mortgage_section):
                ok = False
            if snap_path not in mortgage_section:
                ok = False
            if ok:
                scores["brief_mortgage_section_content"] = 1.0

        sources_section = _extract_section(brief_text, "Data Sources")
        if sources_section is not None:
            if ("input/listings.csv" in sources_section) and ("data/raw/mortgage_rate.html" in sources_section):
                scores["brief_data_sources_listed"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()