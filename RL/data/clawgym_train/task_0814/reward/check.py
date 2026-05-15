import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Dict]]:
    try:
        if not path.exists():
            return None
        items = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
        return items
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        if not path.exists():
            return None, None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def _count_jsonl_records(path: Path) -> Optional[int]:
    items = _safe_load_jsonl(path)
    if items is None:
        return None
    return len(items)


def _count_csv_data_rows(path: Path) -> Optional[int]:
    header, rows = _safe_load_csv(path)
    if header is None or rows is None:
        return None
    return len(rows)


def _build_catalog_map(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    mapping = {}
    for r in rows:
        code = r.get("product_code", "")
        mapping[code] = {
            "product_name_en": r.get("product_name_en", ""),
            "pigment_family": r.get("pigment_family", ""),
        }
    return mapping


def _round2(x: float) -> float:
    return round(x + 0.0, 2)


def _fmt2(x: float) -> str:
    return f"{_round2(x):.2f}"


def _compute_overall_stats(trials: List[Dict]) -> Dict[str, float]:
    n = len(trials)
    if n == 0:
        return {
            "total_trials": 0,
            "distinct_products": 0,
            "avg_rating": 0.0,
            "avg_drying": 0.0,
            "avg_flow": 0.0,
        }
    distinct_products = len({t.get("product_code") for t in trials})
    avg_rating = sum(float(t.get("rating", 0)) for t in trials) / n
    avg_drying = sum(float(t.get("drying_time_sec", 0)) for t in trials) / n
    avg_flow = sum(float(t.get("flow_score", 0)) for t in trials) / n
    return {
        "total_trials": n,
        "distinct_products": distinct_products,
        "avg_rating": _round2(avg_rating),
        "avg_drying": _round2(avg_drying),
        "avg_flow": _round2(avg_flow),
    }


def _compute_family_stats(trials: List[Dict], catalog_map: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, float]]:
    by_family: Dict[str, List[Dict]] = {}
    for t in trials:
        code = t.get("product_code")
        cat = catalog_map.get(code)
        if not cat:
            continue
        fam = cat.get("pigment_family", "")
        by_family.setdefault(fam, []).append(t)
    stats: Dict[str, Dict[str, float]] = {}
    for fam, items in by_family.items():
        if not items:
            continue
        count = len(items)
        avg_rating = _round2(sum(float(i.get("rating", 0)) for i in items) / count)
        avg_flow = _round2(sum(float(i.get("flow_score", 0)) for i in items) / count)
        avg_drying = _round2(sum(float(i.get("drying_time_sec", 0)) for i in items) / count)
        stats[fam] = {
            "count_sessions": count,
            "avg_rating": avg_rating,
            "avg_flow_score": avg_flow,
            "avg_drying_time_sec": avg_drying,
        }
    return stats


def _parse_date(d: str) -> Tuple[int, int, int]:
    # Expect YYYY-MM-DD; fallback to tuple that sorts after proper ones
    try:
        parts = d.split("-")
        return int(parts[0]), int(parts[1]), int(parts[2])
    except Exception:
        return (9999, 12, 31)


def _compute_product_ranking(trials: List[Dict], catalog_map: Dict[str, Dict[str, str]]) -> List[Dict]:
    by_code: Dict[str, List[Dict]] = {}
    for t in trials:
        code = t.get("product_code")
        by_code.setdefault(code, []).append(t)
    ranking = []
    for code, items in by_code.items():
        cnt = len(items)
        avg_rating = sum(float(i.get("rating", 0)) for i in items) / cnt if cnt else 0.0
        avg_flow = sum(float(i.get("flow_score", 0)) for i in items) / cnt if cnt else 0.0
        first_date = min(_parse_date(i.get("date", "")) for i in items) if items else (9999, 12, 31)
        label = catalog_map.get(code, {}).get("product_name_en") or code
        ranking.append({
            "product_code": code,
            "label": label,
            "avg_rating": _round2(avg_rating),
            "avg_flow": _round2(avg_flow),
            "first_date": first_date,
        })
    ranking.sort(key=lambda r: (-r["avg_rating"], -r["avg_flow"], r["first_date"]))
    return ranking


def _missing_codes(trials: List[Dict], catalog_map: Dict[str, Dict[str, str]]) -> List[str]:
    codes = {t.get("product_code") for t in trials}
    missing = [c for c in sorted(codes) if c not in catalog_map]
    return missing


def _extract_sections(report_text: str) -> Dict[str, str]:
    # Approximate extraction by finding indices of headings phrases
    headings = [
        "Overview",
        "Key metrics",
        "Top products",
        "Selected quotes",
        "Data checks",
        "Resumen en español",
    ]
    lower = report_text.lower()
    positions = []
    for h in headings:
        idx = lower.find(h.lower())
        if idx != -1:
            positions.append((idx, h))
    positions.sort()
    sections: Dict[str, str] = {}
    for i, (start_idx, h) in enumerate(positions):
        end_idx = positions[i + 1][0] if i + 1 < len(positions) else len(report_text)
        sections[h.lower()] = report_text[start_idx:end_idx]
    return sections


def _contains_number(text: str, val: float) -> bool:
    # Check presence of value in different formats: int, one decimal, two decimals
    # Accept if within typical rounding representations.
    candidates = {f"{val:.2f}"}
    # Also add representation without trailing zeros if applicable
    if float(int(val)) == val:
        # integer
        candidates.add(str(int(val)))
        candidates.add(f"{val:.1f}")
    else:
        # one-decimal variant (e.g., 197.5)
        candidates.add(f"{val:.1f}")
    for c in candidates:
        if c in text:
            return True
    return False


def _sentence_count(text: str) -> int:
    # Simple sentence split by ., !, ?
    # Remove heading line
    body = text
    # Replace newlines with space to avoid splitting issues
    body = re.sub(r"\s+", " ", body)
    # Split and count non-empty trimmed pieces
    parts = re.split(r"[.!?]+", body)
    count = sum(1 for p in parts if p.strip())
    return count


def _parse_csv_float(val: str) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _validate_stats_by_family_csv(path: Path, expected: Dict[str, Dict[str, float]]) -> Tuple[float, float]:
    # Returns (structure_score, values_score)
    header, rows = _safe_load_csv(path)
    if header is None or rows is None:
        return 0.0, 0.0
    # Structure: exact columns
    expected_header = ["pigment_family", "count_sessions", "avg_rating", "avg_flow_score", "avg_drying_time_sec"]
    structure_ok = 1.0 if header == expected_header else 0.0
    # Values: check that expected families are present and values match
    # Build mapping
    rowmap: Dict[str, Dict[str, str]] = {}
    for r in rows:
        fam = r.get("pigment_family", "")
        rowmap[fam] = r
    if not expected:
        return structure_ok, 0.0
    correct = 0
    total = len(expected)
    for fam, vals in expected.items():
        r = rowmap.get(fam)
        if not r:
            continue
        try:
            cnt_ok = int(str(r.get("count_sessions", "")).strip()) == int(vals["count_sessions"])
        except Exception:
            cnt_ok = False
        ar = _parse_csv_float(str(r.get("avg_rating", "")).strip())
        af = _parse_csv_float(str(r.get("avg_flow_score", "")).strip())
        ad = _parse_csv_float(str(r.get("avg_drying_time_sec", "")).strip())
        vals_ok = (
            ar is not None and abs(ar - vals["avg_rating"]) <= 0.005 and
            af is not None and abs(af - vals["avg_flow_score"]) <= 0.005 and
            ad is not None and abs(ad - vals["avg_drying_time_sec"]) <= 0.005
        )
        if cnt_ok and vals_ok:
            correct += 1
    values_score = (correct / total) if total > 0 else 0.0
    return structure_ok, values_score


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_exists": 0.0,
        "translations_json_valid": 0.0,
        "stats_by_family_csv_valid": 0.0,
        "overview_includes_artist_context": 0.0,
        "overview_sentence_count_2_to_3": 0.0,
        "key_metrics_overall_values_in_report": 0.0,
        "key_metrics_family_values_in_report": 0.0,
        "top_products_order_in_report": 0.0,
        "top_products_use_names_when_available": 0.0,
        "selected_quotes_spanish_in_report": 0.0,
        "data_checks_counts_and_missing_in_report": 0.0,
        "translations_records_correct": 0.0,
        "stats_by_family_values_correct": 0.0,
    }

    # Paths
    input_jsonl = workspace / "input" / "trial_notes_es.jsonl"
    input_catalog = workspace / "input" / "product_catalog.csv"
    input_artist = workspace / "input" / "artist_profile.md"
    output_report = workspace / "output" / "report.md"
    output_translations = workspace / "output" / "translations.json"
    output_stats_csv = workspace / "output" / "stats_by_family.csv"

    # Load inputs
    trials = _safe_load_jsonl(input_jsonl)
    catalog_header, catalog_rows = _safe_load_csv(input_catalog)

    # Baseline gates
    if output_report.exists():
        scores["report_exists"] = 1.0

    # If inputs unavailable, many checks cannot proceed; handle gracefully
    if trials is None or catalog_rows is None:
        # Still can validate existence of outputs; return scores as initialized otherwise
        # Validate minimal JSON structure if present
        if output_translations.exists():
            try:
                data = json.loads(output_translations.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    scores["translations_json_valid"] = 1.0
            except Exception:
                pass
        if output_stats_csv.exists():
            # Structural validation only
            header, rows = _safe_load_csv(output_stats_csv)
            if header is not None and rows is not None:
                scores["stats_by_family_csv_valid"] = 1.0 if header == ["pigment_family", "count_sessions", "avg_rating", "avg_flow_score", "avg_drying_time_sec"] else 0.0
        return scores

    # Compute expected values from inputs
    jsonl_count = len(trials)
    csv_row_count = len(catalog_rows)
    catalog_map = _build_catalog_map(catalog_rows)
    overall = _compute_overall_stats(trials)
    families = _compute_family_stats(trials, catalog_map)
    ranking = _compute_product_ranking(trials, catalog_map)
    missing_codes = _missing_codes(trials, catalog_map)

    # Expected for this dataset (derived)
    # Compute expected top 3 labels in order
    top3 = ranking[:3]
    top3_labels = [r["label"] for r in top3]
    # For this dataset, ensure we know which labels are expected; but compute generally
    # Determine expected top-3 tokens for order check
    order_tokens = top3_labels

    # Validate report content
    report_text = _safe_read_text(output_report)
    if report_text:
        sections = _extract_sections(report_text)

        # Overview checks
        overview = sections.get("overview", "")
        # Check artist context: look for artist name/location from artist_profile.md
        artist_text = _safe_read_text(input_artist) or ""
        # Extract some context tokens
        context_tokens = []
        for token in ["Luna", "Álvarez", "Valencia", "Spain", "100% cotton", "300 gsm", "cold press", "Brushes", "Objectives"]:
            if token in artist_text or token in ["Luna", "Álvarez", "Valencia", "Spain", "100% cotton", "300 gsm", "cold press"]:
                context_tokens.append(token)
        # Check any of those tokens appear in overview (case-insensitive)
        includes_context = any(tok.lower() in overview.lower() for tok in context_tokens) if overview else False
        scores["overview_includes_artist_context"] = 1.0 if includes_context else 0.0
        # Sentence count 2-3
        sc = _sentence_count(overview) if overview else 0
        scores["overview_sentence_count_2_to_3"] = 1.0 if sc in (2, 3) else 0.0

        # Key metrics overall values in report (prefer within key metrics section)
        key_metrics = sections.get("key metrics", report_text)
        overall_ok = True
        # numbers: total trials, distinct products, avg rating, avg drying, avg flow
        # We check presence of numeric tokens; for counts we check integers
        overall_ok = overall_ok and _contains_number(key_metrics, float(overall["total_trials"]))
        overall_ok = overall_ok and _contains_number(key_metrics, float(overall["distinct_products"]))
        overall_ok = overall_ok and _contains_number(key_metrics, float(overall["avg_rating"]))
        overall_ok = overall_ok and _contains_number(key_metrics, float(overall["avg_drying"]))
        overall_ok = overall_ok and _contains_number(key_metrics, float(overall["avg_flow"]))
        scores["key_metrics_overall_values_in_report"] = 1.0 if overall_ok else 0.0

        # Key metrics per family values presence
        family_ok = True
        for fam, vals in families.items():
            fam_present = fam.lower() in key_metrics.lower()
            vals_present = (
                _contains_number(key_metrics, float(vals["avg_rating"])) and
                _contains_number(key_metrics, float(vals["avg_flow_score"])) and
                _contains_number(key_metrics, float(vals["avg_drying_time_sec"]))
            )
            family_ok = family_ok and fam_present and vals_present
        scores["key_metrics_family_values_in_report"] = 1.0 if (families and family_ok) else 0.0 if families else 0.0

        # Top products section ordering and naming
        top_section = sections.get("top products", report_text)
        # Ensure labels present and in the expected order
        positions = []
        all_found = True
        for tok in order_tokens:
            idx = top_section.find(tok)
            if idx == -1:
                all_found = False
                positions.append(-1)
            else:
                positions.append(idx)
        order_ok = all_found and positions == sorted(positions)
        scores["top_products_order_in_report"] = 1.0 if order_ok else 0.0

        # Names used for mapped products (use English name when available; otherwise code)
        # For each of the top3 items that are in catalog, check that name is used
        names_ok = True
        for item in top3:
            code = item["product_code"]
            mapped = catalog_map.get(code)
            if mapped:
                name = mapped.get("product_name_en", "")
                if name:
                    if name not in top_section:
                        names_ok = False
            else:
                # Should use code when not available; ensure code appears
                if code not in top_section:
                    names_ok = False
        scores["top_products_use_names_when_available"] = 1.0 if names_ok else 0.0

        # Selected quotes section: include Spanish originals for top 3 highest-rated by date tiebreak
        # Compute expected top-3 by rating (desc), then by earlier date
        trials_sorted_by_rating = sorted(trials, key=lambda t: (-int(t.get("rating", 0)), _parse_date(t.get("date", ""))))
        selected_top3 = trials_sorted_by_rating[:3]
        selected_spanish = [t.get("note_spanish", "") for t in selected_top3]
        quotes_section = sections.get("selected quotes", report_text)
        present_count = sum(1 for s in selected_spanish if s and s in quotes_section)
        scores["selected_quotes_spanish_in_report"] = present_count / 3.0 if selected_spanish else 0.0

        # Data checks section: list files with counts and missing codes
        data_checks_section = sections.get("data checks", report_text)
        if data_checks_section:
            has_jsonl_path = "input/trial_notes_es.jsonl" in data_checks_section
            has_csv_path = "input/product_catalog.csv" in data_checks_section
            has_jsonl_count = _contains_number(data_checks_section, float(jsonl_count))
            has_csv_count = _contains_number(data_checks_section, float(csv_row_count))
            missing_ok = True
            for mc in missing_codes:
                if mc not in data_checks_section:
                    missing_ok = False
                    break
            scores["data_checks_counts_and_missing_in_report"] = 1.0 if (has_jsonl_path and has_csv_path and has_jsonl_count and has_csv_count and missing_ok) else 0.0
        else:
            scores["data_checks_counts_and_missing_in_report"] = 0.0

    # Validate translations.json
    translations_data = None
    if output_translations.exists():
        try:
            translations_data = json.loads(output_translations.read_text(encoding="utf-8"))
            if isinstance(translations_data, list):
                scores["translations_json_valid"] = 1.0
            else:
                translations_data = None
        except Exception:
            translations_data = None

    # Validate translations records for rating >= 4
    if translations_data is not None and isinstance(translations_data, list):
        # Expected subset
        expected = [t for t in trials if int(t.get("rating", 0)) >= 4]
        expected_by_id = {t["trial_id"]: t for t in expected if "trial_id" in t}
        # Build map from file
        by_id = {}
        for item in translations_data:
            tid = item.get("trial_id")
            if tid:
                by_id[tid] = item
        correct = 0
        total = len(expected_by_id)
        for tid, t in expected_by_id.items():
            item = by_id.get(tid)
            if not item:
                continue
            # Check required fields
            has_fields = all(k in item for k in ["trial_id", "product_code", "note_spanish", "note_english"])
            spanish_match = item.get("note_spanish") == t.get("note_spanish")
            code_match = item.get("product_code") == t.get("product_code")
            eng = item.get("note_english")
            eng_nonempty = isinstance(eng, str) and eng.strip() != ""
            eng_diff = eng_nonempty and eng.strip() != item.get("note_spanish", "").strip()
            if has_fields and spanish_match and code_match and eng_nonempty and eng_diff:
                correct += 1
        scores["translations_records_correct"] = (correct / total) if total > 0 else 0.0

    # Validate stats_by_family.csv
    if output_stats_csv.exists():
        structure_score, values_score = _validate_stats_by_family_csv(output_stats_csv, families)
        scores["stats_by_family_csv_valid"] = structure_score
        scores["stats_by_family_values_correct"] = values_score

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()