import json
import csv
import sys
import math
import re
from pathlib import Path
from html.parser import HTMLParser


class EventsHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_event_li = False
        self.current = None
        self.events = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "li":
            attrs_dict = dict(attrs)
            cls = attrs_dict.get("class", "")
            if "event" in cls.split():
                # Prepare to capture this event
                self.in_event_li = True
                self.current = {
                    "name": "",
                    "category": attrs_dict.get("data-category", "") or "",
                    "city": attrs_dict.get("data-city", "") or "",
                    "month": attrs_dict.get("data-month", "") or "",
                }

    def handle_data(self, data):
        if self.in_event_li and self.current is not None:
            self.current["name"] += data

    def handle_endtag(self, tag):
        if tag.lower() == "li" and self.in_event_li and self.current is not None:
            # Finalize current event
            self.current["name"] = self.current["name"].strip()
            self.events.append(self.current)
            self.in_event_li = False
            self.current = None


def read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_html_events(path: Path):
    text = read_text(path)
    if text is None:
        return None
    parser = EventsHTMLParser()
    try:
        parser.feed(text)
        return parser.events
    except Exception:
        return None


def read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def load_jsonl_ratings(path: Path):
    ratings = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                name = obj.get("name")
                if isinstance(name, str):
                    ratings[name] = {
                        "avg_rating": obj.get("avg_rating"),
                        "review_count": obj.get("review_count"),
                    }
                else:
                    return None
        return ratings
    except Exception:
        return None


def compute_buzz(avg_rating_str, review_count_str):
    # Attempt to match the script's behavior
    avg_rating = (avg_rating_str or "").strip()
    review_count = (review_count_str or "").strip()
    if not avg_rating or not review_count:
        return {"avg_str": "", "rev_str": "", "buzz_str": "", "warn_type": "missing"}
    try:
        avg_val = float(avg_rating)
        rev_val = int(float(review_count))
        buzz_val = avg_val * (1.0 + math.log1p(max(rev_val, 0)))
        return {
            "avg_str": f"{avg_val:.3f}",
            "rev_str": str(rev_val),
            "buzz_str": f"{buzz_val:.6f}",
            "warn_type": None,
        }
    except Exception:
        return {"avg_str": "", "rev_str": "", "buzz_str": "", "warn_type": "invalid"}


def parse_logs(log_path: Path):
    result = {
        "errors": [],
        "warnings_lines": [],
        "warn_missing_names": [],
        "warn_invalid_names": [],
        "processed_rows": None,
        "warnings_total_reported": None,
        "wrote_path": None,
        "raw_text": "",
    }
    text = read_text(log_path)
    if text is None:
        return result
    result["raw_text"] = text
    lines = text.splitlines()
    for line in lines:
        if line.startswith("ERROR"):
            result["errors"].append(line)
        if line.startswith("WARN "):
            result["warnings_lines"].append(line)
            if "missing_rating:" in line:
                # Format: WARN missing_rating: Name
                parts = line.split("missing_rating:", 1)
                if len(parts) == 2:
                    name = parts[1].strip()
                    result["warn_missing_names"].append(name)
            elif "invalid_rating:" in line:
                parts = line.split("invalid_rating:", 1)
                if len(parts) == 2:
                    name = parts[1].strip()
                    result["warn_invalid_names"].append(name)
        if line.startswith("Processed "):
            # Processed N rows
            m = re.match(r"Processed\s+(\d+)\s+rows", line)
            if m:
                try:
                    result["processed_rows"] = int(m.group(1))
                except Exception:
                    pass
        if line.startswith("Warnings:"):
            m = re.match(r"Warnings:\s+(\d+)", line)
            if m:
                try:
                    result["warnings_total_reported"] = int(m.group(1))
                except Exception:
                    pass
        if line.startswith("Wrote:"):
            m = re.match(r"Wrote:\s+(.+)", line)
            if m:
                result["wrote_path"] = m.group(1).strip()
    return result


def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def extract_names_from_text(text: str, candidate_names):
    found = set()
    for n in candidate_names:
        if n in text:
            found.add(n)
    return found


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Paths
    html_path = workspace / "input" / "festivals.html"
    ratings_path = workspace / "input" / "ratings.jsonl"
    extracted_csv = workspace / "output" / "events_extracted.csv"
    joined_csv = workspace / "tmp" / "events_with_ratings.csv"
    score_script = workspace / "scripts" / "score_events.py"
    scored_csv = workspace / "output" / "event_scores.csv"
    logs_path = workspace / "logs" / "score_run.txt"
    top_json = workspace / "output" / "top_by_category.json"
    summary_txt = workspace / "output" / "run_summary.txt"

    # Expected from HTML
    expected_events = parse_html_events(html_path) or []
    expected_set = {(e["name"], e["category"], e["city"], e["month"]) for e in expected_events}
    expected_names = [e["name"] for e in expected_events]
    expected_name_set = set(expected_names)

    # Load ratings
    ratings_map = load_jsonl_ratings(ratings_path) or {}

    # Helper to compute expected joined rows map by name
    def expected_join_for_name(name):
        # Find event details from HTML parsed
        ev = next((e for e in expected_events if e["name"] == name), None)
        if ev is None:
            return None
        rat = ratings_map.get(name)
        if rat is None:
            return {
                "name": ev["name"],
                "category": ev["category"],
                "city": ev["city"],
                "month": ev["month"],
                "avg_rating": "",
                "review_count": "",
            }
        else:
            avg = rat.get("avg_rating")
            rc = rat.get("review_count")
            # Keep as strings to compare with CSV (can be numeric strings)
            avg_str = "" if avg is None else str(avg)
            rc_str = "" if rc is None else str(rc)
            return {
                "name": ev["name"],
                "category": ev["category"],
                "city": ev["city"],
                "month": ev["month"],
                "avg_rating": avg_str,
                "review_count": rc_str,
            }

    # Read produced CSVs
    extr_header, extr_rows = read_csv_dicts(extracted_csv)
    join_header, join_rows = read_csv_dicts(joined_csv)
    score_header, score_rows = read_csv_dicts(scored_csv)
    logs = parse_logs(logs_path)
    top_data = load_json(top_json)
    summary_text = read_text(summary_txt) or ""

    scores = {
        # Step 1: Extraction
        "extracted_csv_exists": 1.0 if extracted_csv.exists() else 0.0,
        "extracted_csv_header_correct": 0.0,
        "extracted_events_match_html": 0.0,
        # Step 2: Join
        "joined_csv_exists": 1.0 if joined_csv.exists() else 0.0,
        "joined_csv_header_correct": 0.0,
        "joined_ratings_match_jsonl": 0.0,
        "joined_blank_for_missing_ratings": 0.0,
        "joined_fields_match_events": 0.0,
        # Step 3: Scoring and logs
        "score_output_csv_exists": 1.0 if scored_csv.exists() else 0.0,
        "score_csv_header_correct": 0.0,
        "score_buzz_scores_correct": 0.0,
        "logs_file_exists": 1.0 if logs_path.exists() else 0.0,
        "logs_no_error": 0.0,
        "logs_warnings_count_correct": 0.0,
        "logs_warn_names_correct": 0.0,
        "logs_processed_and_output_correct": 0.0,
        # Step 4: Top by category JSON
        "top_json_exists": 1.0 if top_json.exists() else 0.0,
        "top_json_structure_correct": 0.0,
        "top_by_category_correct": 0.0,
        # Step 5: Run summary
        "run_summary_exists": 1.0 if summary_txt.exists() else 0.0,
        "run_summary_warn_total_matches_logs": 0.0,
        "run_summary_missing_names_match_logs": 0.0,
    }

    # Step 1 checks
    required_extract_header = ["name", "category", "city", "month"]
    if extr_header is not None and extr_rows is not None:
        if extr_header == required_extract_header:
            scores["extracted_csv_header_correct"] = 1.0
        # Content check: same set of rows as HTML, exactly once per event
        try:
            extracted_set = set()
            ok_rows = True
            for r in extr_rows:
                tup = (r.get("name", "").strip(), r.get("category", "").strip(), r.get("city", "").strip(), r.get("month", "").strip())
                extracted_set.add(tup)
                if not all(isinstance(x, str) and x for x in tup):
                    ok_rows = False
            if ok_rows and extracted_set == expected_set and len(extr_rows) == len(expected_events):
                scores["extracted_events_match_html"] = 1.0
        except Exception:
            pass

    # Step 2 checks
    required_join_header = ["name", "category", "city", "month", "avg_rating", "review_count"]
    if join_header is not None and join_rows is not None:
        if join_header == required_join_header:
            scores["joined_csv_header_correct"] = 1.0
        # Fields match events from HTML
        try:
            join_names = [r.get("name", "").strip() for r in join_rows]
            if set(join_names) == expected_name_set and len(join_rows) == len(expected_events):
                fields_match = True
                ratings_match = True
                blanks_ok = True
                for r in join_rows:
                    nm = (r.get("name") or "").strip()
                    cat = (r.get("category") or "").strip()
                    city = (r.get("city") or "").strip()
                    month = (r.get("month") or "").strip()
                    ev = next((e for e in expected_events if e["name"] == nm), None)
                    if ev is None or ev["category"] != cat or ev["city"] != city or ev["month"] != month:
                        fields_match = False
                    exp_join = expected_join_for_name(nm)
                    if exp_join is None:
                        ratings_match = False
                        continue
                    # Compare ratings presence and values (cast to floats/ints when present)
                    ar = (r.get("avg_rating") or "").strip()
                    rc = (r.get("review_count") or "").strip()
                    if exp_join["avg_rating"] == "" or exp_join["review_count"] == "":
                        # Should both be blank
                        if ar != "" or rc != "":
                            blanks_ok = False
                    else:
                        # Compare numerically
                        try:
                            ar_val = float(ar)
                            exp_ar_val = float(exp_join["avg_rating"])
                            rc_val = int(float(rc))
                            exp_rc_val = int(float(exp_join["review_count"]))
                            if abs(ar_val - exp_ar_val) > 1e-9 or rc_val != exp_rc_val:
                                ratings_match = False
                        except Exception:
                            ratings_match = False
                if fields_match:
                    scores["joined_fields_match_events"] = 1.0
                if ratings_match:
                    scores["joined_ratings_match_jsonl"] = 1.0
                if blanks_ok:
                    scores["joined_blank_for_missing_ratings"] = 1.0
        except Exception:
            pass

    # Step 3 checks: event_scores.csv correctness and logs
    required_score_header = ["name", "category", "city", "month", "avg_rating", "review_count", "buzz_score"]
    if score_header is not None and score_rows is not None:
        if score_header == required_score_header:
            scores["score_csv_header_correct"] = 1.0
        # Compare outputs against joined input using the script's rules
        try:
            if join_rows is not None and len(score_rows) == len(join_rows):
                # Build map by name for both
                join_map = { (r.get("name") or "").strip(): r for r in join_rows }
                score_ok = True
                for s in score_rows:
                    nm = (s.get("name") or "").strip()
                    cat = (s.get("category") or "").strip()
                    city = (s.get("city") or "").strip()
                    month = (s.get("month") or "").strip()
                    ar_out = (s.get("avg_rating") or "").strip()
                    rc_out = (s.get("review_count") or "").strip()
                    bz_out = (s.get("buzz_score") or "").strip()
                    j = join_map.get(nm)
                    if j is None:
                        score_ok = False
                        break
                    # Fields should carry over
                    if (cat != (j.get("category") or "").strip()) or (city != (j.get("city") or "").strip()) or (month != (j.get("month") or "").strip()):
                        score_ok = False
                        break
                    comp = compute_buzz(j.get("avg_rating"), j.get("review_count"))
                    if ar_out != comp["avg_str"] or rc_out != comp["rev_str"] or bz_out != comp["buzz_str"]:
                        score_ok = False
                        break
                if score_ok:
                    scores["score_buzz_scores_correct"] = 1.0
        except Exception:
            pass

    # Logs checks
    if logs_path.exists():
        # No error lines
        if len(logs["errors"]) == 0:
            scores["logs_no_error"] = 1.0
        # Processed rows and wrote path
        proc_ok = False
        if join_rows is not None and logs["processed_rows"] == len(join_rows):
            proc_ok = True
        wrote_ok = (logs["wrote_path"] == "output/event_scores.csv")
        if proc_ok and wrote_ok:
            scores["logs_processed_and_output_correct"] = 1.0
        # Warnings count
        warnings_total_actual = len(logs["warnings_lines"])
        if logs["warnings_total_reported"] == warnings_total_actual and score_rows is not None:
            scores["logs_warnings_count_correct"] = 1.0
        # Warn names correctness based on joined input
        if join_rows is not None:
            expected_missing = []
            expected_invalid = []
            for r in join_rows:
                nm = (r.get("name") or "").strip()
                comp = compute_buzz(r.get("avg_rating"), r.get("review_count"))
                if comp["warn_type"] == "missing":
                    expected_missing.append(nm)
                elif comp["warn_type"] == "invalid":
                    expected_invalid.append(nm)
            if set(expected_missing) == set(logs["warn_missing_names"]) and set(expected_invalid) == set(logs["warn_invalid_names"]):
                scores["logs_warn_names_correct"] = 1.0

    # Step 4: Top by category JSON checks
    if top_data is not None and isinstance(top_data, dict):
        # Structure: keys should equal categories in scored CSV
        try:
            if score_rows is not None:
                categories = sorted(set((r.get("category") or "").strip() for r in score_rows))
                json_keys = sorted(top_data.keys())
                if categories == json_keys:
                    scores["top_json_structure_correct"] = 1.0
                # Build expected top by category from scored_csv
                # Only consider rows with non-empty buzz_score
                scored_by_cat = {}
                for r in score_rows:
                    cat = (r.get("category") or "").strip()
                    name = (r.get("name") or "").strip()
                    bz = (r.get("buzz_score") or "").strip()
                    if bz:
                        try:
                            val = float(bz)
                        except Exception:
                            continue
                        scored_by_cat.setdefault(cat, []).append((name, val))
                expected_tops = {}
                for cat in categories:
                    items = scored_by_cat.get(cat, [])
                    items.sort(key=lambda x: (-x[1], x[0]))
                    expected_tops[cat] = items[:2]
                # Validate JSON values for each category
                overall_ok = True
                for cat in categories:
                    val = top_data.get(cat)
                    if not isinstance(val, list):
                        overall_ok = False
                        break
                    extracted = []
                    for elt in val:
                        if isinstance(elt, dict) and "name" in elt and "buzz_score" in elt and isinstance(elt["name"], str):
                            try:
                                score_val = float(elt["buzz_score"])
                            except Exception:
                                overall_ok = False
                                break
                            extracted.append((elt["name"], score_val))
                        elif isinstance(elt, (list, tuple)) and len(elt) == 2 and isinstance(elt[0], str):
                            try:
                                score_val = float(elt[1])
                            except Exception:
                                overall_ok = False
                                break
                            extracted.append((elt[0], score_val))
                        else:
                            overall_ok = False
                            break
                    if not overall_ok:
                        break
                    # Compare to expected with tolerance
                    exp = expected_tops.get(cat, [])
                    if len(extracted) != len(exp):
                        overall_ok = False
                        break
                    for (n1, v1), (n2, v2) in zip(extracted, exp):
                        if n1 != n2 or abs(v1 - v2) > 1e-6:
                            overall_ok = False
                            break
                    if not overall_ok:
                        break
                if overall_ok:
                    scores["top_by_category_correct"] = 1.0
        except Exception:
            pass

    # Step 5: Run summary checks
    if summary_text:
        try:
            # From logs: total WARN lines and missing names
            warn_total_logs = len(logs["warnings_lines"]) if logs_path.exists() else None
            missing_names_logs = set(logs["warn_missing_names"]) if logs_path.exists() else set()
            # Check that the total WARN number appears in the summary
            if warn_total_logs is not None:
                if str(warn_total_logs) in summary_text:
                    scores["run_summary_warn_total_matches_logs"] = 1.0
            # Check that listed names equal missing names from logs and no others from events are present
            # Extract any known event names present in summary
            present_names_in_summary = extract_names_from_text(summary_text, expected_name_set)
            if present_names_in_summary == missing_names_logs:
                scores["run_summary_missing_names_match_logs"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()