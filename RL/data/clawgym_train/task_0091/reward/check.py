import sys
import json
import csv
import re
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _compute_sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _is_iso8601_like(value: str) -> bool:
    if not isinstance(value, str):
        return False
    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        r"(?:\.\d+)?"
        r"(?:Z|[+\-]\d{2}:\d{2})?$"
    )
    return pattern.match(value) is not None


def _parse_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        lines = []
        with path.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                lines.append(obj)
        return lines
    except Exception:
        return None


def _parse_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None


def _parse_filters_yaml(path: Path) -> Optional[Dict[str, Any]]:
    txt = _read_text(path)
    if txt is None:
        return None
    year_min = None
    keywords = []
    in_keywords = False
    current = None
    try:
        for raw_line in txt.splitlines():
            line = raw_line.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            stripped = line.lstrip()
            if not in_keywords:
                m_year = re.match(r"^year_min:\s*([0-9]+)\s*$", stripped)
                if m_year:
                    try:
                        year_min = int(m_year.group(1))
                    except Exception:
                        return None
                    continue
                if re.match(r"^keywords:\s*$", stripped):
                    in_keywords = True
                    current = None
                    continue
            else:
                m_item_with_term = re.match(r"^-\s*term:\s*(.+?)\s*$", stripped)
                m_item_start = re.match(r"^-\s*$", stripped)
                m_term = re.match(r"^term:\s*(.+?)\s*$", stripped)
                m_weight = re.match(r"^weight:\s*([0-9]+(?:\.[0-9]+)?)\s*$", stripped)
                if m_item_with_term:
                    if current is not None and "term" in current and "weight" in current:
                        keywords.append({"term": current["term"], "weight": current["weight"]})
                    current = {"term": m_item_with_term.group(1).strip()}
                    continue
                if m_item_start:
                    if current is not None and "term" in current and "weight" in current:
                        keywords.append({"term": current["term"], "weight": current["weight"]})
                    current = {}
                    continue
                if m_term and current is not None:
                    current["term"] = m_term.group(1).strip()
                    continue
                if m_weight and current is not None:
                    try:
                        current["weight"] = float(m_weight.group(1))
                    except Exception:
                        return None
                    continue
        if in_keywords and current is not None and "term" in current and "weight" in current:
            keywords.append({"term": current["term"], "weight": current["weight"]})
    except Exception:
        return None

    if year_min is None:
        return None
    if not isinstance(keywords, list) or not all(isinstance(k, dict) and "term" in k and "weight" in k for k in keywords):
        return None
    return {"year_min": year_min, "keywords": keywords}


def _extract_manifest_fields(manifest: dict) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    url_keys = ["url", "download_url", "resolved_url"]
    ts_keys = ["timestamp", "downloaded_at", "download_time", "retrieved_at"]
    sha_keys = ["sha256", "sha256sum", "digest"]

    url = None
    ts = None
    sha = None
    for k in url_keys:
        if k in manifest and isinstance(manifest[k], str):
            url = manifest[k]
            break
    for k in ts_keys:
        if k in manifest and isinstance(manifest[k], str):
            ts = manifest[k]
            break
    for k in sha_keys:
        if k in manifest and isinstance(manifest[k], str):
            sha = manifest[k]
            break
    return url, ts, sha


def _keyword_patterns(keywords: List[Dict[str, Any]]) -> Dict[str, re.Pattern]:
    patterns = {}
    for k in keywords:
        term = k["term"]
        pat = re.compile(rf"\b{re.escape(term)}\b", flags=re.IGNORECASE)
        patterns[term] = pat
    return patterns


def _count_occurrences(text: str, pattern: re.Pattern) -> int:
    return len(pattern.findall(text))


def _compute_filtered_scored(records: List[dict], year_min: int, keywords: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    patterns = _keyword_patterns(keywords)
    weight_map = {k["term"]: float(k["weight"]) for k in keywords}
    results = []
    for rec in records:
        try:
            year = int(rec.get("year"))
        except Exception:
            continue
        if year < year_min:
            continue
        title = rec.get("title", "")
        abstract = rec.get("abstract", "")
        combined = f"{title} {abstract}".strip()
        if not isinstance(combined, str):
            continue
        total_score = 0.0
        matched_terms = []
        for term, pat in patterns.items():
            cnt = _count_occurrences(combined, pat)
            if cnt > 0:
                matched_terms.append(term)
                total_score += weight_map[term] * cnt
        if matched_terms:
            results.append({
                "rfc_number": int(rec.get("rfc_number")),
                "title": title,
                "year": year,
                "current_status": rec.get("current_status", ""),
                "score": total_score,
                "matched_terms": sorted(set(matched_terms)),
            })
    results.sort(key=lambda x: (-x["score"], -x["year"], x["rfc_number"]))
    return results


def _validate_rfcs_jsonl_structure(records: List[dict]) -> bool:
    required_fields = {
        "rfc_number": int,
        "title": str,
        "authors": list,
        "year": int,
        "current_status": str,
        "abstract": str,
    }
    for rec in records:
        for k, typ in required_fields.items():
            if k not in rec:
                return False
            v = rec[k]
            if typ is int:
                try:
                    int(v)
                except Exception:
                    return False
            elif typ is str:
                if not isinstance(v, str):
                    return False
            elif typ is list:
                if not isinstance(v, list):
                    return False
                for a in v:
                    if not isinstance(a, str):
                        return False
    return True


def _check_top_rfcs_csv(csv_path: Path, expected: List[Dict[str, Any]], rfcs_by_number: Dict[int, Dict[str, Any]]) -> Dict[str, float]:
    checks = {
        "top_rfcs_csv_columns_correct": 0.0,
        "top_rfcs_csv_max_50_rows": 0.0,
        "top_rfcs_csv_row_count_expected": 0.0,
        "ranking_scores_and_order_correct": 0.0,
    }
    parsed = _parse_csv(csv_path)
    if parsed is None:
        return checks
    header, rows = parsed
    expected_header = ["rfc_number", "title", "year", "current_status", "score", "matched_keywords"]
    if header == expected_header:
        checks["top_rfcs_csv_columns_correct"] = 1.0

    if len(rows) <= 50:
        checks["top_rfcs_csv_max_50_rows"] = 1.0

    expected_count = min(50, len(expected))
    if len(rows) == expected_count:
        checks["top_rfcs_csv_row_count_expected"] = 1.0

    def parse_row(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
        try:
            rn = int(str(row.get("rfc_number", "")).strip())
            title = row.get("title", "")
            year = int(str(row.get("year", "")).strip())
            status = row.get("current_status", "")
            score = float(str(row.get("score", "")).strip())
            mk_raw = row.get("matched_keywords", "")
            mk_list = [p.strip() for p in mk_raw.split(";") if p.strip()] if isinstance(mk_raw, str) else []
            mk_set = set(mk_list)
            return {
                "rfc_number": rn,
                "title": title,
                "year": year,
                "current_status": status,
                "score": score,
                "matched_keywords_set": mk_set,
                "matched_keywords_list": mk_list,
            }
        except Exception:
            return None

    rows_parsed = []
    for row in rows:
        pr = parse_row(row)
        if pr is None:
            return checks
        rows_parsed.append(pr)

    expected_top_n = expected[:expected_count]
    if len(rows_parsed) != expected_count:
        return checks

    all_ok = True
    for idx, row in enumerate(rows_parsed):
        exp = expected_top_n[idx]
        if row["rfc_number"] != int(exp["rfc_number"]):
            all_ok = False
            break
        base = rfcs_by_number.get(row["rfc_number"])
        if base is None:
            all_ok = False
            break
        if row["title"] != base.get("title", ""):
            all_ok = False
            break
        if row["year"] != int(base.get("year", 0)):
            all_ok = False
            break
        if row["current_status"] != base.get("current_status", ""):
            all_ok = False
            break
        if abs(row["score"] - float(exp["score"])) > 1e-6:
            all_ok = False
            break
        if set(row["matched_keywords_set"]) != set(exp["matched_terms"]):
            all_ok = False
            break

    if all_ok:
        checks["ranking_scores_and_order_correct"] = 1.0

    return checks


def _check_summary_md(summary_path: Path, manifest_sha: Optional[str], total_count: Optional[int],
                      filtered_count: Optional[int], top5_terms: Optional[List[str]]) -> Dict[str, float]:
    checks = {
        "summary_contains_sha256": 0.0,
        "summary_total_count_correct": 0.0,
        "summary_filtered_count_correct": 0.0,
        "summary_top5_keywords_present": 0.0,
        "summary_repro_section_and_command": 0.0,
    }
    text = _read_text(summary_path)
    if text is None:
        return checks

    if manifest_sha and manifest_sha in text:
        checks["summary_contains_sha256"] = 1.0

    repro_cmd_present = False
    for line in text.splitlines():
        if "scripts/" in line and "input/filters.yaml" in line:
            repro_cmd_present = True
            break
    if repro_cmd_present:
        checks["summary_repro_section_and_command"] = 1.0

    if total_count is not None:
        m = re.search(r"total\s+rfcs\s+parsed[^0-9]*([0-9,]+)", text, flags=re.IGNORECASE)
        if m:
            try:
                num = int(m.group(1).replace(",", ""))
                if num == total_count:
                    checks["summary_total_count_correct"] = 1.0
            except Exception:
                pass

    if filtered_count is not None:
        m2 = re.search(r"filtered\s+in[^0-9]*([0-9,]+)", text, flags=re.IGNORECASE)
        if not m2:
            m2 = re.search(r"number\s+filtered[^0-9]*([0-9,]+)", text, flags=re.IGNORECASE)
        if not m2:
            m2 = re.search(r"filtered[^0-9]*([0-9,]+)", text, flags=re.IGNORECASE)
        if m2:
            try:
                num2 = int(m2.group(1).replace(",", ""))
                if num2 == filtered_count:
                    checks["summary_filtered_count_correct"] = 1.0
            except Exception:
                pass

    if top5_terms:
        present = 0
        for term in top5_terms:
            if re.search(rf"\b{re.escape(term)}\b", text):
                present += 1
        if present == len(top5_terms):
            checks["summary_top5_keywords_present"] = 1.0

    return checks


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "rfc_xml_present_and_wellformed": 0.0,
        "manifest_present": 0.0,
        "manifest_url_official_and_filename": 0.0,
        "manifest_sha256_matches_file": 0.0,
        "manifest_timestamp_iso8601": 0.0,
        "rfcs_jsonl_present": 0.0,
        "rfcs_jsonl_structure_valid": 0.0,
        "rfcs_jsonl_nonempty": 0.0,
        "top_rfcs_csv_present": 0.0,
        "top_rfcs_csv_columns_correct": 0.0,
        "top_rfcs_csv_max_50_rows": 0.0,
        "top_rfcs_csv_row_count_expected": 0.0,
        "ranking_scores_and_order_correct": 0.0,
        "summary_md_present": 0.0,
        "summary_contains_sha256": 0.0,
        "summary_total_count_correct": 0.0,
        "summary_filtered_count_correct": 0.0,
        "summary_top5_keywords_present": 0.0,
        "summary_repro_section_and_command": 0.0,
        "scripts_directory_and_script_present": 0.0,
    }

    xml_path = workspace / "webcache" / "rfc-index.xml"
    manifest_path = workspace / "webcache" / "manifest.json"
    jsonl_path = workspace / "data" / "rfcs.jsonl"
    csv_path = workspace / "reports" / "top_rfcs.csv"
    summary_path = workspace / "reports" / "summary.md"
    scripts_dir = workspace / "scripts"
    filters_yaml_path = workspace / "input" / "filters.yaml"

    if xml_path.exists() and xml_path.is_file():
        try:
            content = xml_path.read_bytes()
            if len(content) > 0 and content.lstrip().startswith(b"<"):
                scores["rfc_xml_present_and_wellformed"] = 1.0
        except Exception:
            pass

    manifest = None
    if manifest_path.exists() and manifest_path.is_file():
        scores["manifest_present"] = 1.0
        manifest = _read_json(manifest_path)
    url_val = None
    ts_val = None
    sha_val = None
    if manifest:
        url_val, ts_val, sha_val = _extract_manifest_fields(manifest)
        if isinstance(url_val, str):
            url_ok = ("rfc-editor.org" in url_val) and url_val.rstrip().endswith("rfc-index.xml")
            if url_ok:
                scores["manifest_url_official_and_filename"] = 1.0
        if isinstance(ts_val, str) and _is_iso8601_like(ts_val):
            scores["manifest_timestamp_iso8601"] = 1.0
        xml_sha = _compute_sha256_file(xml_path) if xml_path.exists() else None
        if isinstance(sha_val, str) and xml_sha and sha_val.lower() == xml_sha.lower():
            scores["manifest_sha256_matches_file"] = 1.0

    records = None
    if jsonl_path.exists() and jsonl_path.is_file():
        scores["rfcs_jsonl_present"] = 1.0
        records = _parse_jsonl(jsonl_path)
        if records is not None and isinstance(records, list):
            if len(records) > 0:
                scores["rfcs_jsonl_nonempty"] = 1.0
            if _validate_rfcs_jsonl_structure(records):
                scores["rfcs_jsonl_structure_valid"] = 1.0

    if scripts_dir.exists() and scripts_dir.is_dir():
        has_script = False
        try:
            for p in scripts_dir.glob("*"):
                if p.is_file() and (p.suffix in [".sh", ".py", ".bash", ".zsh"] or p.name.startswith("run_")):
                    has_script = True
                    break
        except Exception:
            has_script = False
        if has_script:
            scores["scripts_directory_and_script_present"] = 1.0

    if csv_path.exists() and csv_path.is_file():
        scores["top_rfcs_csv_present"] = 1.0

    filters = _parse_filters_yaml(filters_yaml_path) if filters_yaml_path.exists() else None

    expected_filtered_scored: List[Dict[str, Any]] = []
    rfcs_by_number: Dict[int, Dict[str, Any]] = {}
    total_count: Optional[int] = None
    filtered_count: Optional[int] = None
    top5_terms: Optional[List[str]] = None

    if records is not None and isinstance(records, list) and filters is not None:
        rfcs_by_number = {}
        for rec in records:
            try:
                rn = int(rec.get("rfc_number"))
                rfcs_by_number[rn] = rec
            except Exception:
                continue
        expected_filtered_scored = _compute_filtered_scored(records, int(filters["year_min"]), list(filters["keywords"]))
        total_count = len(records)
        filtered_count = len(expected_filtered_scored)
        patterns = _keyword_patterns(filters["keywords"])
        totals: Dict[str, int] = {k["term"]: 0 for k in filters["keywords"]}
        for item in expected_filtered_scored:
            rn = item["rfc_number"]
            rec = rfcs_by_number.get(rn)
            if not rec:
                continue
            text = f"{rec.get('title','')} {rec.get('abstract','')}"
            for term, pat in patterns.items():
                totals[term] += _count_occurrences(text, pat)
        sorted_terms = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
        top5_terms = [t for t, c in sorted_terms[:5]]

        if scores["top_rfcs_csv_present"] == 1.0:
            csv_checks = _check_top_rfcs_csv(csv_path, expected_filtered_scored, rfcs_by_number)
            scores.update(csv_checks)

    if summary_path.exists() and summary_path.is_file():
        scores["summary_md_present"] = 1.0
        summary_checks = _check_summary_md(summary_path, sha_val, total_count, filtered_count, top5_terms)
        scores.update(summary_checks)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()