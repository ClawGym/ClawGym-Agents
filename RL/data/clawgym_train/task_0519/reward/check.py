import json
import csv
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except Exception as e:
        return None, str(e)


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames, None
    except Exception as e:
        return None, None, str(e)


def _split_body_and_references(text: str) -> Tuple[str, str]:
    lines = text.splitlines()
    ref_start = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("references"):
            ref_start = i
            break
    if ref_start is None:
        bracket_line_indices = [i for i, line in enumerate(lines) if re.match(r'^\s*\[\d+\]', line)]
        if bracket_line_indices:
            threshold = max(0, len(lines) - 10)
            candidates = [i for i in bracket_line_indices if i >= threshold]
            if candidates:
                ref_start = candidates[0]
            else:
                last_block_start = None
                i = len(lines) - 1
                while i >= 0 and (re.match(r'^\s*\[\d+\]', lines[i]) or lines[i].strip() == ""):
                    i -= 1
                j = i + 1
                while j < len(lines):
                    if re.match(r'^\s*\[\d+\]', lines[j]):
                        if last_block_start is None:
                            last_block_start = j
                    j += 1
                if last_block_start is not None:
                    ref_start = last_block_start
    if ref_start is None:
        return text, ""
    body = "\n".join(lines[:ref_start]).strip("\n")
    refs = "\n".join(lines[ref_start:]).strip("\n")
    return body, refs


def _extract_citation_ids(text: str) -> List[int]:
    ids = []
    for m in re.findall(r'\[(\d+)\]', text):
        try:
            ids.append(int(m))
        except Exception:
            continue
    return ids


def _extract_hashtags(text: str) -> List[str]:
    return re.findall(r'(?<!\w)#\w+', text)


def _normalize_text(s: str) -> str:
    return re.sub(r'\s+', ' ', s.lower()).strip()


def _validate_sources_schema(data: Any) -> Tuple[bool, Dict[str, Any]]:
    result = {
        "valid": False,
        "ids": set(),
        "issues": [],
        "counts": {
            "total": 0,
            "org_docs": 0,
            "sys_meta": 0,
        },
        "id_list": [],
        "id_to_url": {},
        "id_to_title": {},
        "id_to_org": {},
    }
    if not isinstance(data, list):
        result["issues"].append("sources_json_not_array")
        return False, result
    allowed_doc_types = {"guideline", "consensus", "systematic_review", "meta_analysis", "policy_statement", "other"}
    allowed_evidence = {"high", "moderate", "low"}
    ids = []
    ok = True
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            ok = False
            result["issues"].append(f"item_{idx}_not_object")
            continue
        required_fields = ["id", "title", "organization_or_journal", "year", "doc_type", "url", "topic_keywords", "evidence_level"]
        for f in required_fields:
            if f not in item:
                ok = False
                result["issues"].append(f"item_{idx}_missing_{f}")
        id_val = item.get("id")
        if not isinstance(id_val, int) or id_val < 1:
            ok = False
            result["issues"].append(f"item_{idx}_bad_id")
        else:
            ids.append(id_val)
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            ok = False
            result["issues"].append(f"item_{idx}_bad_title")
        org = item.get("organization_or_journal")
        if not isinstance(org, str) or not org.strip():
            ok = False
            result["issues"].append(f"item_{idx}_bad_org")
        year = item.get("year")
        if year is not None and not isinstance(year, int):
            ok = False
            result["issues"].append(f"item_{idx}_bad_year")
        doc_type = item.get("doc_type")
        if doc_type not in allowed_doc_types:
            ok = False
            result["issues"].append(f"item_{idx}_bad_doc_type")
        url = item.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            ok = False
            result["issues"].append(f"item_{idx}_bad_url")
        tk = item.get("topic_keywords")
        if not isinstance(tk, list) or not (2 <= len(tk) <= 5) or not all(isinstance(k, str) and k.strip() for k in tk):
            ok = False
            result["issues"].append(f"item_{idx}_bad_topic_keywords")
        ev = item.get("evidence_level")
        if ev not in allowed_evidence:
            ok = False
            result["issues"].append(f"item_{idx}_bad_evidence_level")
        result["counts"]["total"] += 1
        if doc_type in {"guideline", "consensus", "policy_statement"}:
            result["counts"]["org_docs"] += 1
        if doc_type in {"systematic_review", "meta_analysis"}:
            result["counts"]["sys_meta"] += 1
        if isinstance(id_val, int) and isinstance(url, str):
            result["id_to_url"][id_val] = url
        if isinstance(id_val, int) and isinstance(title, str):
            result["id_to_title"][id_val] = title
        if isinstance(id_val, int) and isinstance(org, str):
            result["id_to_org"][id_val] = org
    unique_ids = sorted(set(ids))
    result["ids"] = set(unique_ids)
    result["id_list"] = unique_ids
    if unique_ids:
        expected = list(range(1, len(unique_ids) + 1))
        if unique_ids != expected:
            ok = False
            result["issues"].append("ids_not_contiguous_from_1")
    result["valid"] = ok
    return ok, result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "queries_file_present_and_min_5_queries": 0.0,
        "sources_json_valid_schema": 0.0,
        "sources_minimum_counts": 0.0,
        "sources_consecutive_ids_start_at_1": 0.0,
        "linkcheck_script_present": 0.0,
        "linkcheck_csv_structure_and_coverage": 0.0,
        "troubleshooting_log_if_non_200": 0.0,
        "post_file_present": 0.0,
        "post_body_within_char_limit": 0.0,
        "post_has_exactly_three_cited_points": 0.0,
        "post_citations_reference_existing_ids": 0.0,
        "post_hashtags_count_and_required_from_list": 0.0,
        "post_references_block_maps_all_citations": 0.0,
        "validate_script_present": 0.0,
        "validation_report_status_pass": 0.0,
        "validation_output_log_indicates_pass": 0.0,
    }

    # Check queries.txt
    queries_path = workspace / "data" / "queries.txt"
    queries_text = _read_text(queries_path)
    if queries_text is not None:
        lines = [ln.strip() for ln in queries_text.splitlines() if ln.strip()]
        if len(lines) >= 5:
            scores["queries_file_present_and_min_5_queries"] = 1.0

    # Load sources.json
    sources_path = workspace / "data" / "sources.json"
    sources_data, _ = _load_json(sources_path)
    sources_valid = False
    id_info = {
        "ids": set(),
        "id_list": [],
        "id_to_url": {},
        "id_to_title": {},
        "id_to_org": {},
        "counts": {"total": 0, "org_docs": 0, "sys_meta": 0},
    }
    if sources_data is not None and isinstance(sources_data, list):
        valid, info = _validate_sources_schema(sources_data)
        sources_valid = valid
        id_info = info
        if valid:
            scores["sources_json_valid_schema"] = 1.0
            if info["counts"]["total"] >= 5 and info["counts"]["org_docs"] >= 2 and info["counts"]["sys_meta"] >= 1:
                scores["sources_minimum_counts"] = 1.0
            if info["id_list"]:
                expected_ids = list(range(1, len(info["id_list"]) + 1))
                if info["id_list"] == expected_ids:
                    scores["sources_consecutive_ids_start_at_1"] = 1.0

    # Linkcheck script present
    linkcheck_py = workspace / "scripts" / "linkcheck.py"
    linkcheck_sh = workspace / "scripts" / "linkcheck.sh"
    if linkcheck_py.exists() or linkcheck_sh.exists():
        scores["linkcheck_script_present"] = 1.0

    # Linkcheck CSV
    linkcsv_path = workspace / "data" / "linkcheck.csv"
    rows, headers, _ = _load_csv_dicts(linkcsv_path)
    linkcsv_ok = False
    non_200_found = False
    if rows is not None and headers is not None:
        expected_cols = ["id", "url", "http_status", "error"]
        if headers == expected_cols:
            if sources_valid:
                row_ids = set()
                id_to_row = {}
                for r in rows:
                    try:
                        rid = int(str(r.get("id", "")).strip())
                        row_ids.add(rid)
                        id_to_row[rid] = r
                    except Exception:
                        continue
                if row_ids == id_info["ids"] and len(row_ids) == len(rows):
                    mismatch = False
                    for rid in row_ids:
                        r = id_to_row.get(rid, {})
                        url = r.get("url", "")
                        expected_url = id_info["id_to_url"].get(rid, "")
                        if url != expected_url:
                            mismatch = True
                            break
                        status_str = r.get("http_status", "")
                        try:
                            status_int = int(status_str)
                        except Exception:
                            mismatch = True
                            break
                        if status_int != 200:
                            non_200_found = True
                    if not mismatch:
                        linkcsv_ok = True
    if linkcsv_ok:
        scores["linkcheck_csv_structure_and_coverage"] = 1.0

    # Troubleshooting log existence and content requirement if non-200
    troubleshooting_path = workspace / "logs" / "troubleshooting.txt"
    tr_text = _read_text(troubleshooting_path)
    if non_200_found:
        if tr_text is not None and tr_text.strip():
            scores["troubleshooting_log_if_non_200"] = 1.0
    else:
        if tr_text is not None:
            scores["troubleshooting_log_if_non_200"] = 1.0

    # Post draft checks
    post_path = workspace / "content" / "post_draft.md"
    post_text = _read_text(post_path)
    if post_text is not None:
        scores["post_file_present"] = 1.0
        body_text, refs_text = _split_body_and_references(post_text)
        body_char_count = len(body_text)
        if body_char_count <= 1200:
            scores["post_body_within_char_limit"] = 1.0
        point_lines = [ln for ln in body_text.splitlines() if re.search(r'\[\d+\]', ln)]
        if len(point_lines) == 3:
            scores["post_has_exactly_three_cited_points"] = 1.0
        cited_ids = set(_extract_citation_ids(body_text))
        if cited_ids and sources_valid and cited_ids.issubset(id_info["ids"]):
            scores["post_citations_reference_existing_ids"] = 1.0
        allowed_tags_text = _read_text(workspace / "input" / "hashtags.txt")
        allowed_set = set()
        if allowed_tags_text is not None:
            allowed_set = set([ln.strip() for ln in allowed_tags_text.splitlines() if ln.strip().startswith("#")])
        hashtags = _extract_hashtags(body_text)
        if 3 <= len(hashtags) <= 5:
            from_allowed = sum(1 for h in hashtags if h in allowed_set)
            if from_allowed >= 2:
                scores["post_hashtags_count_and_required_from_list"] = 1.0
        if sources_valid and cited_ids:
            refs_ok = True
            refs_lines = refs_text.splitlines()
            id_to_refline_idx = {}
            for i, line in enumerate(refs_lines):
                m = re.match(r'^\s*\[(\d+)\]', line)
                if m:
                    try:
                        idx_val = int(m.group(1))
                        id_to_refline_idx[idx_val] = i
                    except Exception:
                        pass
            for cid in cited_ids:
                title = id_info["id_to_title"].get(cid, "")
                org = id_info["id_to_org"].get(cid, "")
                if cid not in id_to_refline_idx:
                    refs_ok = False
                    break
                line_idx = id_to_refline_idx[cid]
                check_blob = refs_lines[line_idx]
                if line_idx + 1 < len(refs_lines):
                    check_blob += " " + refs_lines[line_idx + 1]
                n_blob = _normalize_text(check_blob)
                if _normalize_text(title) not in n_blob or _normalize_text(org) not in n_blob:
                    refs_ok = False
                    break
            if refs_ok:
                scores["post_references_block_maps_all_citations"] = 1.0

    # Validate script presence
    validate_script_path = workspace / "scripts" / "validate_post.py"
    if validate_script_path.exists():
        scores["validate_script_present"] = 1.0

    # Validation report pass
    report_path = workspace / "validation" / "report.json"
    report_data, _ = _load_json(report_path)
    if isinstance(report_data, dict):
        needed_fields = ["char_count", "char_limit", "refs_found", "refs_matched", "required_hashtags_present", "status", "messages"]
        has_fields = all(k in report_data for k in needed_fields)
        types_ok = (
            isinstance(report_data.get("char_count"), int)
            and isinstance(report_data.get("char_limit"), int)
            and isinstance(report_data.get("refs_found"), int)
            and isinstance(report_data.get("refs_matched"), int)
            and isinstance(report_data.get("required_hashtags_present"), int)
            and isinstance(report_data.get("status"), str)
            and isinstance(report_data.get("messages"), list)
        )
        if has_fields and types_ok:
            cond = (
                report_data["char_count"] <= report_data["char_limit"]
                and report_data["status"].lower() == "pass"
                and report_data["refs_matched"] == report_data["refs_found"]
                and report_data["required_hashtags_present"] >= 2
            )
            if cond:
                scores["validation_report_status_pass"] = 1.0

    # Validation output log indicates pass
    val_log_path = workspace / "logs" / "validation_output.txt"
    val_log_text = _read_text(val_log_path)
    if val_log_text is not None and re.search(r'\bpass\b', val_log_text, flags=re.IGNORECASE):
        scores["validation_output_log_indicates_pass"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()