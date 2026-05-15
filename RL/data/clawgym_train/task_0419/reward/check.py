import json
import csv
import sys
import subprocess
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def _extract_between(s: str, start: str, end: str) -> str:
    try:
        part = s.split(start, 1)[1]
        return part.split(end, 1)[0]
    except Exception:
        return ""


def _parse_expected_events_from_html(html: str) -> List[Dict]:
    parts = html.split('<div class="event"')
    results = []
    for i in range(1, len(parts)):
        block = '<div class="event"' + parts[i]
        did = _extract_between(block, 'data-id="', '"').strip()
        title = _extract_between(block, '<h3 class="title">', '</h3>').strip()
        date_iso = _extract_between(block, '<time datetime="', '"').strip()
        city = _extract_between(block, '<span class="city">', '</span>').strip()
        state = _extract_between(block, '<span class="state">', '</span>').strip()
        topics_section = _extract_between(block, '<ul class="topics">', '</ul>')
        topics = []
        if topics_section:
            segs = topics_section.split('<li>')
            for seg in segs[1:]:
                itm = seg.split('</li>')[0].strip()
                topics.append(itm)
        host = _extract_between(block, '<span class="host">', '</span>').strip()
        results.append({
            "id": did,
            "title": title,
            "date_iso": date_iso,
            "city": city,
            "state": state,
            "topics": topics,
            "host": host
        })
    results.sort(key=lambda r: r.get("date_iso", ""))
    return results


def _is_sorted_by_date_iso(records: List[Dict]) -> bool:
    dates = [r.get("date_iso", "") for r in records]
    return dates == sorted(dates)


def _run_script(workspace: Path, script_rel_path: str, timeout_sec: int = 20) -> Tuple[bool, int, str, str]:
    script_path = workspace / script_rel_path
    if not script_path.exists():
        return False, -1, "", "script not found"
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            text=True,
            encoding="utf-8",
        )
        return True, proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return True, -1, "", f"timeout: {e}"
    except Exception as e:
        return True, -1, "", f"error: {e}"


def _count_sentences(text: str) -> int:
    sentences = re.split(r'[.!?]+', text)
    count = 0
    for s in sentences:
        if s.strip():
            count += 1
    return count


def _contains_cities_list_line(text: str, cities: List[str]) -> bool:
    lines = text.splitlines()
    cities_lower = [c.lower() for c in cities]
    for line in lines:
        lower = line.lower()
        if all(c in lower for c in cities_lower):
            if line.count(",") >= max(1, len(cities) - 1):
                return True
    return False


def _detect_disallowed_imports(script_text: str) -> bool:
    # Return True if only stdlib is likely used. Heuristic: disallow common third-party imports.
    disallowed = [
        r'^\s*import\s+bs4\b',
        r'^\s*from\s+bs4\s+import\b',
        r'^\s*import\s+lxml\b',
        r'^\s*from\s+lxml\s+import\b',
        r'^\s*import\s+pandas\b',
        r'^\s*from\s+pandas\s+import\b',
        r'^\s*import\s+requests\b',
        r'^\s*from\s+requests\s+import\b',
        r'^\s*import\s+beautifulsoup4\b',
    ]
    for pat in disallowed:
        if re.search(pat, script_text, flags=re.MULTILINE):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "script_runs_no_args": 0.0,
        "json_exists": 0.0,
        "json_parseable_array": 0.0,
        "json_schema_fields_types": 0.0,
        "json_sorted_by_date": 0.0,
        "json_matches_input_expected": 0.0,
        "csv_exists": 0.0,
        "csv_has_required_columns": 0.0,
        "csv_rows_match_json_and_sorted": 0.0,
        "email_exists": 0.0,
        "email_address_and_sentence_count": 0.0,
        "email_run_instructions_and_outputs_listed": 0.0,
        "email_counts_and_cities": 0.0,
        "input_not_modified": 0.0,
        "refactor_function_structure": 0.0,
        "stdlib_only_imports": 0.0,
    }

    script_rel = "refactored/collect_events_refactored.py"
    json_path = workspace / "output" / "events.json"
    csv_path = workspace / "output" / "events.csv"
    email_path = workspace / "output" / "email_to_club.txt"
    input_html_path = workspace / "input" / "events.html"

    script_file = workspace / script_rel
    if script_file.exists() and script_file.is_file():
        scores["script_exists"] = 1.0

    before_input_content = _safe_read_text(input_html_path)

    ran, returncode, _stdout, _stderr = _run_script(workspace, script_rel)
    if ran and returncode == 0:
        scores["script_runs_no_args"] = 1.0

    after_input_content = _safe_read_text(input_html_path)
    if scores["script_runs_no_args"] == 1.0 and before_input_content is not None and after_input_content is not None and before_input_content == after_input_content:
        scores["input_not_modified"] = 1.0

    if json_path.exists():
        scores["json_exists"] = 1.0
    json_obj = _safe_load_json(json_path) if json_path.exists() else None
    if isinstance(json_obj, list):
        scores["json_parseable_array"] = 1.0

        schema_ok = True
        for item in json_obj:
            if not isinstance(item, dict):
                schema_ok = False
                break
            required = ["id", "title", "date_iso", "city", "state", "topics", "host"]
            for k in required:
                if k not in item:
                    schema_ok = False
                    break
            if not schema_ok:
                break
            if not isinstance(item.get("id"), str):
                schema_ok = False
                break
            if not isinstance(item.get("title"), str):
                schema_ok = False
                break
            if not isinstance(item.get("date_iso"), str):
                schema_ok = False
                break
            if not isinstance(item.get("city"), str):
                schema_ok = False
                break
            if not isinstance(item.get("state"), str):
                schema_ok = False
                break
            if not isinstance(item.get("host"), str):
                schema_ok = False
                break
            topics_val = item.get("topics")
            if not isinstance(topics_val, list) or not all(isinstance(t, str) for t in topics_val):
                schema_ok = False
                break
        if schema_ok:
            scores["json_schema_fields_types"] = 1.0

        try:
            if _is_sorted_by_date_iso(json_obj):
                scores["json_sorted_by_date"] = 1.0
        except Exception:
            pass

        input_html_text = _safe_read_text(input_html_path)
        if input_html_text is not None:
            expected = _parse_expected_events_from_html(input_html_text)
            try:
                expected_by_id = {e["id"]: e for e in expected}
                json_by_id = {e.get("id", ""): e for e in json_obj}
                if "" in json_by_id:
                    raise ValueError("missing id in JSON")
                ids_match = set(expected_by_id.keys()) == set(json_by_id.keys())
                fields_match = ids_match
                if ids_match:
                    for i in expected_by_id.keys():
                        exp = expected_by_id[i]
                        got = json_by_id[i]
                        for k in ["id", "title", "date_iso", "city", "state", "topics", "host"]:
                            if got.get(k) != exp.get(k):
                                fields_match = False
                                break
                        if not fields_match:
                            break
                order_match = [e["id"] for e in json_obj] == [e["id"] for e in expected]
                if ids_match and fields_match and order_match:
                    scores["json_matches_input_expected"] = 1.0
            except Exception:
                pass

    if csv_path.exists():
        scores["csv_exists"] = 1.0
        header, rows = _safe_read_csv(csv_path)
        if header is not None and rows is not None:
            required_cols = {"id", "title", "date_iso", "city", "state", "topics", "host"}
            if set(header) >= required_cols:
                scores["csv_has_required_columns"] = 1.0

            if isinstance(json_obj, list):
                try:
                    json_by_id = {e.get("id", ""): e for e in json_obj if isinstance(e, dict) and "id" in e}
                    if "" in json_by_id:
                        raise ValueError("invalid id in json")
                    counts_ok = len(rows) == len(json_obj)
                    rows_by_id = {}
                    dup_id = False
                    for r in rows:
                        rid = r.get("id", "")
                        if rid in rows_by_id:
                            dup_id = True
                            break
                        rows_by_id[rid] = r
                    if counts_ok and not dup_id and set(rows_by_id.keys()) == set(json_by_id.keys()):
                        fields_ok = True
                        for rid, r in rows_by_id.items():
                            j = json_by_id[rid]
                            if r.get("title", "") != j.get("title", ""):
                                fields_ok = False
                                break
                            if r.get("date_iso", "") != j.get("date_iso", ""):
                                fields_ok = False
                                break
                            if r.get("city", "") != j.get("city", ""):
                                fields_ok = False
                                break
                            if r.get("state", "") != j.get("state", ""):
                                fields_ok = False
                                break
                            if r.get("host", "") != j.get("host", ""):
                                fields_ok = False
                                break
                            expected_topics = ";".join(j.get("topics", []))
                            if r.get("topics", "") != expected_topics:
                                fields_ok = False
                                break
                        csv_dates = [r.get("date_iso", "") for r in rows]
                        sorted_ok = csv_dates == sorted(csv_dates)
                        if fields_ok and sorted_ok:
                            scores["csv_rows_match_json_and_sorted"] = 1.0
                except Exception:
                    pass

    if email_path.exists():
        scores["email_exists"] = 1.0
        email_text = _safe_read_text(email_path) or ""
        if "debate night tech team" in email_text.lower():
            sc = _count_sentences(email_text)
            if 3 <= sc <= 6:
                scores["email_address_and_sentence_count"] = 1.0
        run_ok = ("python" in email_text.lower() and "collect_events_refactored.py".lower() in email_text.lower())
        outputs_ok = ("output/events.json" in email_text and "output/events.csv" in email_text)
        if run_ok and outputs_ok:
            scores["email_run_instructions_and_outputs_listed"] = 1.0
        json_obj_local = _safe_load_json(json_path) if json_path.exists() else None
        if isinstance(json_obj_local, list):
            num_events = len(json_obj_local)
            cities = []
            for e in json_obj_local:
                if isinstance(e, dict):
                    c = e.get("city", "")
                    if c and c not in cities:
                        cities.append(c)
            number_present = re.search(rf"\b{num_events}\b", email_text) is not None
            cities_ok = _contains_cities_list_line(email_text, cities) if cities else False
            if number_present and cities_ok:
                scores["email_counts_and_cities"] = 1.0

    if script_file.exists():
        script_text = _safe_read_text(script_file) or ""
        def_count = len(re.findall(r'^\s*def\s+\w+\s*\(', script_text, flags=re.MULTILINE))
        if def_count >= 3:
            scores["refactor_function_structure"] = 1.0
        if _detect_disallowed_imports(script_text):
            scores["stdlib_only_imports"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()