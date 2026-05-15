import json
import sys
import re
import csv
from pathlib import Path
from urllib.parse import urlparse
from typing import Tuple, List, Dict, Any


def _read_text(path: Path) -> Tuple[bool, str]:
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def _read_json(path: Path) -> Tuple[bool, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _read_jsonl_lines(path: Path) -> Tuple[bool, List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f]
        return True, lines
    except Exception:
        return False, []


def _parse_csv_rows(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return True, rows
    except Exception:
        return False, []


def _is_iso8601_z(s: str) -> bool:
    if not isinstance(s, str) or len(s) < 10:
        return False
    try:
        from datetime import datetime
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:\d{2})$"
        return re.match(pattern, s) is not None


def _slugify_city(city: str) -> str:
    return re.sub(r"\s+", "-", city.strip().lower())


def _validate_event_obj(obj: Any, schema: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "Event is not an object"
    allowed_props = set(schema.get("properties", {}).keys())
    required = set(schema.get("required", []))
    keys = set(obj.keys())
    if not required.issubset(keys):
        missing = sorted(required - keys)
        return False, f"Missing required fields: {', '.join(missing)}"
    if not keys.issubset(allowed_props):
        extra = sorted(keys - allowed_props)
        return False, f"Additional properties not allowed: {', '.join(extra)}"
    if not isinstance(obj.get("id"), str) or not re.match(r"^[A-Za-z0-9_-]+$", obj["id"]):
        return False, "Invalid id format"
    if not isinstance(obj.get("title"), str) or len(obj["title"]) < 3:
        return False, "Invalid title"
    if not isinstance(obj.get("date"), str) or re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", obj["date"]) is None:
        return False, "Invalid date format"
    if not isinstance(obj.get("city"), str) or len(obj["city"]) < 2:
        return False, "Invalid city"
    if not isinstance(obj.get("country"), str) or len(obj["country"]) < 2:
        return False, "Invalid country"
    if not isinstance(obj.get("timezone"), str):
        return False, "Invalid timezone"
    if not isinstance(obj.get("tags"), list) or not all(isinstance(t, str) for t in obj["tags"]):
        return False, "Invalid tags"
    if not isinstance(obj.get("created_at"), str) or not _is_iso8601_z(obj["created_at"]):
        return False, "Invalid created_at datetime"
    if not isinstance(obj.get("organizer"), str) or len(obj["organizer"]) < 2:
        return False, "Invalid organizer"
    if "notes" in obj and not isinstance(obj["notes"], str):
        return False, "Invalid notes type"
    return True, ""


def _classify_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
    except Exception:
        host = ""
    if ".gov" in host:
        return "government"
    if host.endswith(".edu") or ".edu." in host:
        return "education"
    if host.endswith(".org") or ".org." in host:
        return "nonprofit"
    return "other"


def _load_reference_query_terms(workspace: Path, city: str, country: str) -> Tuple[bool, str]:
    ok, rows = _parse_csv_rows(workspace / "input" / "cities_reference.csv")
    if not ok:
        return False, ""
    target_city = (city or "").strip().lower()
    target_country = (country or "").strip().lower()
    for row in rows:
        c = (row.get("city") or "").strip().lower()
        k = (row.get("country") or "").strip().lower()
        if c == target_city and (not target_country or k == target_country):
            return True, (row.get("query_terms") or "")
    for row in rows:
        c = (row.get("city") or "").strip().lower()
        if c == target_city:
            return True, (row.get("query_terms") or "")
    return False, ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "watcher_script_exists": 0.0,
        "watcher_script_references_paths": 0.0,
        "run_tests_exists": 0.0,
        "run_tests_contains_key_steps": 0.0,
        "events_ledger_exists": 0.0,
        "events_ledger_contains_required_ids": 0.0,
        "events_ledger_schema_valid": 0.0,
        "output_json_present_for_new_event": 0.0,
        "filename_city_slug_correct": 0.0,
        "output_json_fields_valid": 0.0,
        "output_results_count_and_uniqueness": 0.0,
        "output_urls_and_domain_types_valid": 0.0,
        "output_query_matches_reference_or_default": 0.0,
        "links_index_csv_present_and_header": 0.0,
        "links_index_row_counts_correct_for_new_event": 0.0,
    }

    watcher_path = workspace / "automation" / "watch_events.py"
    if watcher_path.is_file():
        scores["watcher_script_exists"] = 1.0
        ok_text, text = _read_text(watcher_path)
        if ok_text:
            needed_tokens = ["events.jsonl", "search_results", "links_index.csv"]
            if all(tok in text for tok in needed_tokens):
                scores["watcher_script_references_paths"] = 1.0

    run_tests = workspace / "run_tests.sh"
    if run_tests.is_file():
        scores["run_tests_exists"] = 1.0
        ok_text, text = _read_text(run_tests)
        if ok_text:
            tokens = [
                "input/events_seed.jsonl",
                "workspace/events.jsonl",
                "automation/watch_events.py",
                "input/new_event.json",
                "output/search_results",
                "output/summary/links_index.csv",
            ]
            if all(tok in text for tok in tokens):
                scores["run_tests_contains_key_steps"] = 1.0

    schema_ok, schema_obj = _read_json(workspace / "input" / "events_schema.json")
    if not (schema_ok and isinstance(schema_obj, dict)):
        schema_ok = False
        schema_obj = None

    ledger_path = workspace / "workspace" / "events.jsonl"
    if ledger_path.is_file():
        scores["events_ledger_exists"] = 1.0
        ok_lines, lines = _read_jsonl_lines(ledger_path)
        if ok_lines and lines is not None:
            # Check for required IDs regardless of schema validity
            ids = set()
            for ln in lines:
                try:
                    obj = json.loads(ln)
                    if isinstance(obj, dict) and "id" in obj:
                        ids.add(obj["id"])
                except Exception:
                    continue
            required_ids = {"evt-001", "evt-002", "evt-003"}
            if required_ids.issubset(ids):
                scores["events_ledger_contains_required_ids"] = 1.0

            # Schema validation of all lines (only if schema available)
            if schema_ok and isinstance(schema_obj, dict):
                all_valid = True
                for ln in lines:
                    if not ln.strip():
                        all_valid = False
                        break
                    try:
                        obj = json.loads(ln)
                    except Exception:
                        all_valid = False
                        break
                    valid, _reason = _validate_event_obj(obj, schema_obj)
                    if not valid:
                        all_valid = False
                        break
                if all_valid:
                    scores["events_ledger_schema_valid"] = 1.0

    new_event_ok, new_event = _read_json(workspace / "input" / "new_event.json")
    event_id = None
    city = None
    country = None
    if new_event_ok and isinstance(new_event, dict):
        event_id = new_event.get("id")
        city = new_event.get("city")
        country = new_event.get("country")

    expected_output_path = None
    if event_id and city:
        city_slug = _slugify_city(city)
        expected_output_path = workspace / "output" / "search_results" / f"{event_id}-{city_slug}.json"

    if expected_output_path and expected_output_path.is_file():
        scores["output_json_present_for_new_event"] = 1.0
        ok_json, out_json = _read_json(expected_output_path)
        if ok_json and isinstance(out_json, dict):
            file_city_slug = expected_output_path.stem.split("-", 1)[-1] if "-" in expected_output_path.stem else ""
            out_city = out_json.get("city")
            if isinstance(out_city, str) and _slugify_city(out_city) == file_city_slug:
                scores["filename_city_slug_correct"] = 1.0

            top_ok = True
            if out_json.get("event_id") != event_id:
                top_ok = False
            if out_json.get("city") != city:
                top_ok = False
            if not isinstance(out_json.get("query"), str) or not out_json.get("query"):
                top_ok = False
            if not isinstance(out_json.get("retrieved_at"), str) or not _is_iso8601_z(out_json["retrieved_at"]):
                top_ok = False
            results = out_json.get("results")
            if not isinstance(results, list):
                top_ok = False
                results = []
            if top_ok:
                scores["output_json_fields_valid"] = 1.0

            results_ok = False
            if isinstance(results, list):
                if 3 <= len(results) <= 10:
                    urls = []
                    valid_items = True
                    for r in results:
                        if not isinstance(r, dict):
                            valid_items = False
                            break
                        url = r.get("url")
                        title = r.get("title")
                        dtype = r.get("domain_type")
                        if not isinstance(title, str) or not title.strip():
                            valid_items = False
                            break
                        if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
                            valid_items = False
                            break
                        if not isinstance(dtype, str) or dtype not in ("government", "education", "nonprofit", "other"):
                            valid_items = False
                            break
                        urls.append(url.strip())
                    if valid_items and len(set(urls)) == len(urls):
                        results_ok = True
            if results_ok:
                scores["output_results_count_and_uniqueness"] = 1.0

            dtype_ok = True
            counts = {"government": 0, "education": 0, "nonprofit": 0, "other": 0}
            if isinstance(results, list) and results:
                for r in results:
                    if not isinstance(r, dict):
                        dtype_ok = False
                        break
                    url = r.get("url", "")
                    dtype = r.get("domain_type", "")
                    computed = _classify_domain(url)
                    if dtype != computed:
                        dtype_ok = False
                        break
                    if dtype in counts:
                        counts[dtype] += 1
                if dtype_ok:
                    scores["output_urls_and_domain_types_valid"] = 1.0

            query_str = out_json.get("query", "")
            q_ok = False
            if isinstance(query_str, str) and city and country:
                has_ref, ref_terms = _load_reference_query_terms(workspace, city, country)
                if has_ref and ref_terms:
                    q_ok = ref_terms.lower() in query_str.lower()
                else:
                    required_bits = [
                        "Indigenous land acknowledgement",
                        city,
                        country,
                    ]
                    q_ok = all(bit.lower() in query_str.lower() for bit in required_bits)
            if q_ok:
                scores["output_query_matches_reference_or_default"] = 1.0

            index_csv = workspace / "output" / "summary" / "links_index.csv"
            if index_csv.is_file():
                try:
                    with index_csv.open("r", encoding="utf-8") as f:
                        reader = csv.reader(f)
                        rows = list(reader)
                except Exception:
                    rows = []
                header_ok = False
                if rows and rows[0] == ["event_id", "city", "total_results", "gov_count", "edu_count", "org_count", "other_count"]:
                    header_ok = True
                if header_ok:
                    scores["links_index_csv_present_and_header"] = 1.0
                    json_total = len(results) if isinstance(results, list) else None
                    found_matching_row = False
                    for row in rows[1:]:
                        if len(row) != 7:
                            continue
                        rid, rcity, rtotal, rgov, redu, rorg, rother = row
                        if rid == event_id and rcity == city:
                            try:
                                rtotal_i = int(rtotal)
                                rgov_i = int(rgov)
                                redu_i = int(redu)
                                rorg_i = int(rorg)
                                rother_i = int(rother)
                            except Exception:
                                continue
                            if json_total is not None and rtotal_i != json_total:
                                continue
                            if rgov_i == counts.get("government", -1) and redu_i == counts.get("education", -1) and rorg_i == counts.get("nonprofit", -1) and rother_i == counts.get("other", -1):
                                if (rgov_i + redu_i + rorg_i + rother_i) == rtotal_i:
                                    found_matching_row = True
                                    break
                    if found_matching_row:
                        scores["links_index_row_counts_correct_for_new_event"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()