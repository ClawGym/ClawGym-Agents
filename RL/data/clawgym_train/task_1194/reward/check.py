import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        try:
            with path.open("r", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                return reader.fieldnames, rows
        except Exception:
            return None, None


def parse_specs(yaml_text: str) -> Optional[Dict]:
    """
    Minimal YAML extractor tailored to the provided specs.yaml structure.
    Returns a dict with keys: filters, scoring.weights, ranking, email.
    """
    if yaml_text is None:
        return None

    text = yaml_text

    def extract_inline_list(key: str) -> Optional[List[str]]:
        m = re.search(rf"{re.escape(key)}\s*:\s*\[([^\]]*)\]", text)
        if not m:
            return None
        inner = m.group(1).strip()
        if not inner:
            return []
        parts = [p.strip() for p in inner.split(",")]
        cleaned = []
        for p in parts:
            # strip quotes if present
            p = p.strip()
            if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
                p = p[1:-1]
            cleaned.append(p)
        return cleaned

    def extract_number(key: str) -> Optional[float]:
        m = re.search(rf"{re.escape(key)}\s*:\s*([-+]?\d+(?:\.\d+)?)\b", text)
        if not m:
            return None
        try:
            return float(m.group(1))
        except Exception:
            return None

    def extract_int(key: str) -> Optional[int]:
        m = re.search(rf"{re.escape(key)}\s*:\s*([-+]?\d+)\b", text)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    def extract_bool(key: str) -> Optional[bool]:
        m = re.search(rf"{re.escape(key)}\s*:\s*(true|false)\b", text, flags=re.IGNORECASE)
        if not m:
            return None
        return m.group(1).lower() == "true"

    def extract_quoted_string(key: str) -> Optional[str]:
        m = re.search(rf"{re.escape(key)}\s*:\s*['\"]([^'\"]+)['\"]", text)
        if not m:
            return None
        return m.group(1)

    specs = {
        "filters": {
            "allowed_socket": extract_inline_list("allowed_socket"),
            "min_cores": extract_number("min_cores"),
            "max_tdp_w": extract_number("max_tdp_w"),
            "require_ecc": extract_bool("require_ecc"),
            "max_price_usd": extract_number("max_price_usd"),
        },
        "scoring": {
            "weights": {
                "cores_base": extract_number("cores_base"),
                "boost": extract_number("boost"),
                "l3": extract_number("l3"),
                "tdp_penalty": extract_number("tdp_penalty"),
                "process_penalty": extract_number("process_penalty"),
            }
        },
        "ranking": {
            "primary": extract_quoted_string("primary"),
            "tie_breakers": extract_inline_list("tie_breakers"),
        },
        "email": {
            "to": extract_quoted_string("to"),
            "top_n": extract_int("top_n"),
        },
    }

    # Validate that required elements were parsed
    required_paths = [
        ("filters", "allowed_socket"),
        ("filters", "min_cores"),
        ("filters", "max_tdp_w"),
        ("filters", "require_ecc"),
        ("filters", "max_price_usd"),
        ("scoring", "weights", "cores_base"),
        ("scoring", "weights", "boost"),
        ("scoring", "weights", "l3"),
        ("scoring", "weights", "tdp_penalty"),
        ("scoring", "weights", "process_penalty"),
        ("ranking", "primary"),
        ("ranking", "tie_breakers"),
        ("email", "to"),
        ("email", "top_n"),
    ]

    def get_nested(dct, keys):
        cur = dct
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return None
            cur = cur[k]
        return cur

    for path in required_paths:
        if get_nested(specs, path) is None:
            return None

    return specs


def parse_bool_str(val: str) -> Optional[bool]:
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in {"true", "yes", "y", "1"}:
        return True
    if s in {"false", "no", "n", "0"}:
        return False
    return None


def parse_float(val: str) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def parse_int(val: str) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        try:
            f = float(val)
            return int(f)
        except Exception:
            return None


def compute_perf_and_value(row: Dict[str, str], weights: Dict[str, float]) -> Optional[Tuple[float, float]]:
    # Required numeric fields for computation
    required_fields = [
        "cores",
        "base_clock_GHz",
        "boost_clock_GHz",
        "TDP_W",
        "L3_cache_MB",
        "process_nm",
        "price_USD",
    ]
    nums = {}
    for k in required_fields:
        v = row.get(k)
        fv = parse_float(v)
        if fv is None:
            return None
        nums[k] = fv
    perf = (
        nums["cores"] * nums["base_clock_GHz"] * weights["cores_base"]
        + nums["boost_clock_GHz"] * weights["boost"]
        + nums["L3_cache_MB"] * weights["l3"]
        - nums["TDP_W"] * weights["tdp_penalty"]
        - nums["process_nm"] * weights["process_penalty"]
    )
    if nums["price_USD"] == 0:
        return None
    value = perf / nums["price_USD"]
    return perf, value


def compare_floats(expected: float, actual: float, rel_tol: float = 1e-3, abs_tol: float = 1e-2) -> bool:
    if actual is None:
        return False
    if abs(expected - actual) <= max(abs_tol, rel_tol * max(abs(expected), abs(actual))):
        return True
    return False


def compute_expected_from_inputs(workspace: Path, specs: Dict) -> Optional[Dict]:
    """
    Compute expected filtered rows and ranking from input CSV and specs.
    Returns dict with:
      - basename
      - total_rows
      - passing_rows: list of dict rows (original string values)
      - augmented: list of dicts with added keys 'perf_score', 'value_score'
      - expected_order_part_numbers: list of part_numbers in expected order
      - top_n: int
      - email_to: str
    """
    inbox_csv = workspace / "inbox" / "cpu_quotes_2026-04-10.csv"
    if not inbox_csv.exists():
        return None
    fieldnames, rows = safe_read_csv_dicts(inbox_csv)
    if fieldnames is None or rows is None:
        return None

    filters = specs["filters"]
    weights = specs["scoring"]["weights"]
    ranking = specs["ranking"]
    email = specs["email"]

    passing = []
    augmented = []
    for r in rows:
        # Filter checks
        socket_ok = r.get("socket") in (filters["allowed_socket"] or [])
        cores_val = parse_float(r.get("cores"))
        base_val = parse_float(r.get("base_clock_GHz"))
        boost_val = parse_float(r.get("boost_clock_GHz"))
        tdp_val = parse_float(r.get("TDP_W"))
        l3_val = parse_float(r.get("L3_cache_MB"))
        price_val = parse_float(r.get("price_USD"))
        stock_val = parse_float(r.get("stock"))  # may be used in tie-break
        process_val = parse_float(r.get("process_nm"))
        if None in (cores_val, base_val, boost_val, tdp_val, l3_val, price_val, process_val):
            continue
        if not socket_ok:
            continue
        if cores_val < float(filters["min_cores"]):
            continue
        if tdp_val > float(filters["max_tdp_w"]):
            continue
        if price_val > float(filters["max_price_usd"]):
            continue
        ecc_ok = parse_bool_str(r.get("ECC_support"))
        # If ECC is required but unparseable, exclude
        if filters["require_ecc"] and ecc_ok is not True:
            continue
        perf_value = compute_perf_and_value(r, weights)
        if perf_value is None:
            continue
        perf, value = perf_value
        passing.append(r)
        aug = dict(r)
        aug["_perf_score"] = perf
        aug["_value_score"] = value
        # Keep parsed for sorting
        aug["_parsed_stock"] = stock_val
        aug["_parsed_tdp"] = tdp_val
        augmented.append(aug)

    # Ranking: primary value_score_desc then tie_breakers
    # Map tie breaker keys to fields and orders
    field_map = {
        "stock": "_parsed_stock",
        "tdp": "_parsed_tdp",
    }
    tie_breakers = ranking.get("tie_breakers") or []

    def sort_key(item):
        keys = [(-item["_value_score"],)]
        # Build tuple components according to tie_breakers
        for tb in tie_breakers:
            tb = tb.strip()
            m = re.match(r"^([A-Za-z0-9_]+)_(asc|desc)$", tb)
            if not m:
                continue
            field_key, order = m.group(1), m.group(2)
            mapped = field_map.get(field_key, field_key)
            val = item.get(mapped)
            # Default to 0 if missing for stability
            if val is None:
                val = 0
            if order == "asc":
                keys.append((val,))
            else:
                keys.append((-val,))
        return tuple(v for tup in keys for v in tup)

    augmented_sorted = sorted(augmented, key=sort_key)

    expected_order_part_numbers = [a["part_number"] for a in augmented_sorted]
    return {
        "basename": "cpu_quotes_2026-04-10",
        "total_rows": len(rows),
        "passing_rows": passing,
        "augmented": augmented_sorted,
        "expected_order_part_numbers": expected_order_part_numbers,
        "top_n": int(email["top_n"]),
        "email_to": email["to"],
        "weights": weights,
    }


def read_output_report(workspace: Path, basename: str) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]], Path]:
    path = workspace / "output" / "reports" / f"{basename}_filtered_ranked.csv"
    header, rows = safe_read_csv_dicts(path)
    return header, rows, path


def read_output_email(workspace: Path, basename: str) -> Tuple[Optional[str], Path]:
    path = workspace / "output" / "emails" / f"{basename}_summary.txt"
    text = safe_read_text(path)
    return text, path


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "reports_csv_exists": 0.0,
        "reports_columns_order_and_append": 0.0,
        "reports_filtering_count": 0.0,
        "reports_scores_correct": 0.0,
        "reports_ranking_and_rank_values": 0.0,
        "email_exists": 0.0,
        "email_recipient_and_subject": 0.0,
        "email_summary_counts": 0.0,
        "email_top_n_list": 0.0,
    }

    # Load specs
    specs_path = workspace / "input" / "specs.yaml"
    specs_text = safe_read_text(specs_path)
    specs = parse_specs(specs_text) if specs_text is not None else None
    if specs is None:
        # Cannot proceed; return zeros
        return scores

    expected = compute_expected_from_inputs(workspace, specs)
    if expected is None:
        return scores

    basename = expected["basename"]
    header, out_rows, out_path = read_output_report(workspace, basename)
    if header is None or out_rows is None:
        scores["reports_csv_exists"] = 0.0
    else:
        scores["reports_csv_exists"] = 1.0

        # Check columns: all original columns in order and appended perf_score, value_score, rank at end
        original_cols = [
            "part_number",
            "vendor",
            "socket",
            "cores",
            "base_clock_GHz",
            "boost_clock_GHz",
            "TDP_W",
            "L3_cache_MB",
            "price_USD",
            "stock",
            "ECC_support",
            "process_nm",
            "PCIe_version",
            "launch_year",
        ]
        expected_cols = original_cols + ["perf_score", "value_score", "rank"]
        columns_ok = header == expected_cols
        scores["reports_columns_order_and_append"] = 1.0 if columns_ok else 0.0

        # Filtering count check
        expected_count = len(expected["passing_rows"])
        actual_count = len(out_rows)
        scores["reports_filtering_count"] = 1.0 if actual_count == expected_count else 0.0

        # Scores correctness: compare perf_score and value_score within tolerance for all rows
        # Map output rows by part_number for comparison
        out_by_part = {r.get("part_number"): r for r in out_rows}
        all_scores_ok = True
        for aug in expected["augmented"]:
            pn = aug["part_number"]
            out_r = out_by_part.get(pn)
            if out_r is None:
                all_scores_ok = False
                break
            # Parse perf and value from output
            perf_out = parse_float(out_r.get("perf_score"))
            value_out = parse_float(out_r.get("value_score"))
            if not compare_floats(aug["_perf_score"], perf_out, rel_tol=1e-3, abs_tol=1e-1):
                all_scores_ok = False
                break
            if not compare_floats(aug["_value_score"], value_out, rel_tol=1e-3, abs_tol=1e-3):
                all_scores_ok = False
                break
        scores["reports_scores_correct"] = 1.0 if all_scores_ok and actual_count == expected_count else 0.0

        # Ranking and rank values check: order of rows matches expected order, and rank field is sequential 1..N
        order_ok = True
        rank_ok = True
        # Check order
        expected_order = expected["expected_order_part_numbers"]
        actual_order = [r.get("part_number") for r in out_rows]
        order_ok = actual_order == expected_order
        # Check rank sequence matches row position starting at 1
        for idx, r in enumerate(out_rows, start=1):
            rank_val = parse_int(r.get("rank"))
            if rank_val != idx:
                rank_ok = False
                break
        scores["reports_ranking_and_rank_values"] = 1.0 if (order_ok and rank_ok and actual_count == expected_count) else 0.0

    # Email checks
    email_text, email_path = read_output_email(workspace, basename)
    if email_text is None:
        scores["email_exists"] = 0.0
    else:
        scores["email_exists"] = 1.0
        text = email_text

        # Recipient and subject
        recipient_ok = expected["email_to"] in text
        # Subject line: must include "CPU Shortlist" and basename; accept either en dash or hyphen, with or without "Subject:" prefix
        subject_ok = False
        lines = [ln.strip() for ln in text.splitlines()]
        for ln in lines:
            if ("cpu shortlist" in ln.lower()) and (basename in ln):
                subject_ok = True
                break
        # Combine
        scores["email_recipient_and_subject"] = (1.0 if (recipient_ok and subject_ok) else 0.0)

        # Summary counts: find a line that contains total and passing counts with keywords
        total_rows = expected["total_rows"]
        passing_count = len(expected["passing_rows"])
        summary_ok = False
        summary_keywords = {"process", "processed", "sku", "skus", "met", "pass", "passes", "passed"}
        for ln in lines:
            low = ln.lower()
            if any(k in low for k in summary_keywords):
                # check both numbers appear in the same line
                if str(total_rows) in ln and str(passing_count) in ln:
                    summary_ok = True
                    break
        scores["email_summary_counts"] = 1.0 if summary_ok else 0.0

        # Top-N bullets: parse bullet lines and validate top N items and details
        # Accept bullets starting with -, *, or •
        bullet_indices = []
        for i, ln in enumerate(lines):
            if re.match(r"^\s*[\-\*\u2022]\s+", ln):
                bullet_indices.append(i)
        top_n = expected["top_n"]
        bullets_ok_score = 0.0
        if len(bullet_indices) >= top_n:
            # Extract bullet texts for top_n bullets
            bullet_texts = [lines[i] for i in bullet_indices[:top_n]]
            expected_top_parts = expected["expected_order_part_numbers"][:top_n]
            expected_map = {aug["part_number"]: aug for aug in expected["augmented"]}
            per_item_results = []
            for idx, bt in enumerate(bullet_texts):
                pn = expected_top_parts[idx]
                aug = expected_map.get(pn)
                if aug is None:
                    per_item_results.append(False)
                    continue
                # Check it mentions part_number and vendor
                vendor = aug["vendor"]
                has_pn = pn in bt
                has_vendor = vendor in bt
                # Check presence of required fields values: cores, base_clock_GHz, TDP_W, price_USD
                # We'll check for their exact numeric string representations as in the input (without units).
                cores_s = str(aug.get("cores"))
                base_s = str(aug.get("base_clock_GHz"))
                tdp_s = str(aug.get("TDP_W"))
                price_s = str(aug.get("price_USD"))
                has_cores = re.search(rf"\b{re.escape(cores_s)}\b", bt) is not None
                has_base = re.search(rf"\b{re.escape(base_s)}\b", bt) is not None
                has_tdp = re.search(rf"\b{re.escape(tdp_s)}\b", bt) is not None
                has_price = re.search(rf"{re.escape(price_s)}", bt) is not None
                # Justification: mention ECC or TDP or value
                justification = re.search(r"(ecc|tdp|value)", bt, flags=re.IGNORECASE) is not None

                item_ok = has_pn and has_vendor and has_cores and has_base and has_tdp and has_price and justification
                per_item_results.append(item_ok)
            # All top_n bullets must be valid
            bullets_ok_score = sum(1.0 for b in per_item_results if b) / float(top_n)
        else:
            bullets_ok_score = 0.0

        # Require order of bullets to match expected ranking by checking part_numbers in order
        order_ok = False
        if len(bullet_indices) >= top_n:
            bt_parts = []
            for i in bullet_indices[:top_n]:
                ln = lines[i]
                bt_parts.append(ln)
            order_ok = True
            for idx, pn in enumerate(expected["expected_order_part_numbers"][:top_n]):
                if pn not in bt_parts[idx]:
                    order_ok = False
                    break

        # Combine bullets item validity and correct order: require both
        scores["email_top_n_list"] = 1.0 if (bullets_ok_score == 1.0 and order_ok) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()