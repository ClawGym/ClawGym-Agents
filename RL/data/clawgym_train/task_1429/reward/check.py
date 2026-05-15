import json
import sys
import re
from pathlib import Path
import csv

def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _safe_parse_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def _safe_parse_jsonl(path: Path):
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    return None
        return items
    except Exception:
        return None

def _parse_year(text: str):
    if text is None:
        return None
    m = re.search(r"(\d+)", str(text))
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def _float_or_none(val):
    try:
        return float(val)
    except Exception:
        return None

def _recompute_expected_anomalies(workspace: Path):
    # Returns dict keyed by citation_id (as string) with expected anomaly records
    input_csv = workspace / "input" / "citations.csv"
    cfg_path = workspace / "config" / "tradition.json"
    rows = _safe_parse_csv_dicts(input_csv)
    cfg = _safe_load_json(cfg_path)
    if rows is None or cfg is None:
        return None

    try:
        aliases = cfg["tradition"]["aliases"]
        earliest = cfg["tradition"]["earliest_years"]
        weight_raw = cfg["weights"]["anachronism"]
    except Exception:
        return None

    weight = _float_or_none(weight_raw)
    if weight is None:
        # Cannot compute expected severities without a numeric weight
        return None

    expected = {}
    for row in rows:
        cid = str(row.get("citation_id", "")).strip()
        term_raw = row.get("tradition_term", "")
        term = aliases.get(term_raw, term_raw)
        claimed_str = row.get("claimed_date", "")
        source = row.get("source", "")
        title = row.get("title", "")

        claimed_year = _parse_year(claimed_str)
        if claimed_year is None:
            continue

        if term not in earliest:
            continue

        try:
            earliest_year = int(earliest[term])
        except Exception:
            continue

        if claimed_year < earliest_year:
            diff_years = earliest_year - claimed_year
            delta_centuries = diff_years / 100.0
            severity = round(delta_centuries * weight, 4)
            record = {
                "citation_id": cid,
                "source": source,
                "title": title,
                "tradition_term": term,
                "claimed_date": claimed_str,
                "claimed_year": claimed_year,
                "earliest_year": earliest_year,
                "issue_type": "anachronism",
                "severity_score": severity,
                "reason": f"{term} attested by {earliest_year}, claimed {claimed_year}"
            }
            expected[cid] = record
    return expected

def _parse_csv_header_and_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            rdr = csv.reader(f)
            rows = list(rdr)
    except Exception:
        return None, None
    if not rows:
        return None, None
    header = rows[0]
    data_rows = rows[1:]
    return header, data_rows

def _extract_floats(text: str):
    floats = []
    for m in re.finditer(r"(?<!\d)(\d+\.\d+)", text):
        try:
            floats.append(float(m.group(1)))
        except Exception:
            continue
    return floats

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "anomalies_raw_exists_and_parseable": 0.0,
        "anomalies_raw_expected_count_and_fields": 0.0,
        "anomalies_raw_values_correct": 0.0,
        "review_log_includes_error_excerpt": 0.0,
        "review_log_explains_fix": 0.0,
        "review_log_includes_success_summary": 0.0,
        "ranked_csv_exists_and_header": 0.0,
        "ranked_csv_rows_correct_order_and_ranks": 0.0,
        "ranked_csv_values_match_raw": 0.0,
        "email_includes_traditio_and_path": 0.0,
        "email_summarizes_top_anomalies": 0.0,
        "email_includes_severities_for_top_anomalies": 0.0,
    }

    # Paths
    anomalies_raw_path = workspace / "output" / "anomalies_raw.jsonl"
    review_log_path = workspace / "output" / "review_log.txt"
    ranked_csv_path = workspace / "output" / "anomalies_ranked.csv"
    email_path = workspace / "output" / "email_to_editor.md"

    # Load artifacts
    anomalies_raw = _safe_parse_jsonl(anomalies_raw_path)
    if anomalies_raw is not None:
        scores["anomalies_raw_exists_and_parseable"] = 1.0

    expected_anomalies = _recompute_expected_anomalies(workspace)
    # Check anomalies_raw against expected
    if anomalies_raw is not None and expected_anomalies is not None:
        # Count check and required fields
        required_fields = {
            "citation_id", "source", "title", "tradition_term", "claimed_date",
            "claimed_year", "earliest_year", "issue_type", "severity_score", "reason"
        }
        all_fields_ok = True
        for rec in anomalies_raw:
            if not isinstance(rec, dict):
                all_fields_ok = False
                break
            if not required_fields.issubset(set(rec.keys())):
                all_fields_ok = False
                break
            # Basic types
            if rec.get("issue_type") != "anachronism":
                all_fields_ok = False
                break
            if _float_or_none(rec.get("severity_score")) is None:
                all_fields_ok = False
                break
            if not isinstance(rec.get("reason"), str):
                all_fields_ok = False
                break

        count_ok = (len(anomalies_raw) == len(expected_anomalies))
        if count_ok and all_fields_ok:
            scores["anomalies_raw_expected_count_and_fields"] = 1.0

        # Value correctness check
        values_ok = True
        # Compare by citation_id
        raw_by_id = {str(r.get("citation_id")): r for r in anomalies_raw if "citation_id" in r}
        if set(raw_by_id.keys()) != set(expected_anomalies.keys()):
            values_ok = False
        else:
            for cid, exp in expected_anomalies.items():
                got = raw_by_id.get(cid)
                if got is None:
                    values_ok = False
                    break
                # Check canonical term, years, severity, reason
                if got.get("tradition_term") != exp.get("tradition_term"):
                    values_ok = False
                    break
                if got.get("claimed_date") != exp.get("claimed_date"):
                    values_ok = False
                    break
                if int(got.get("claimed_year")) != int(exp.get("claimed_year")):
                    values_ok = False
                    break
                if int(got.get("earliest_year")) != int(exp.get("earliest_year")):
                    values_ok = False
                    break
                sev_got = _float_or_none(got.get("severity_score"))
                sev_exp = _float_or_none(exp.get("severity_score"))
                if sev_got is None or sev_exp is None or abs(sev_got - sev_exp) > 1e-9:
                    values_ok = False
                    break
                if got.get("reason") != exp.get("reason"):
                    values_ok = False
                    break
        if values_ok:
            scores["anomalies_raw_values_correct"] = 1.0

    # Review log checks
    review_text = _safe_read_text(review_log_path)
    if review_text:
        # error excerpt presence (flexible)
        if re.search(r"typeerror", review_text, flags=re.IGNORECASE) or \
           re.search(r"traceback", review_text, flags=re.IGNORECASE) or \
           "can't multiply sequence by non-int" in review_text.lower():
            scores["review_log_includes_error_excerpt"] = 1.0

        # explains fix: mentions file and change
        mentions_file = ("config/tradition.json" in review_text) or ("scripts/inspect_citations.py" in review_text)
        mentions_fix = any(k in review_text.lower() for k in ["type", "float", "string", "weights", "anachronism", "cast", "convert", "changed", "fix"])
        if mentions_file and mentions_fix:
            scores["review_log_explains_fix"] = 1.0

        # successful run summary with correct count and path
        expected_count = len(expected_anomalies) if expected_anomalies is not None else None
        if expected_count is not None:
            # Look for "Wrote N anomalies to output/anomalies_raw.jsonl"
            m = re.search(r"Wrote\s+(\d+)\s+anomalies\s+to\s+output/anomalies_raw\.jsonl", review_text)
            if m:
                n = int(m.group(1))
                if n == expected_count:
                    scores["review_log_includes_success_summary"] = 1.0

    # Ranked CSV checks
    header, ranked_rows = _parse_csv_header_and_rows(ranked_csv_path)
    expected_header = ["rank", "citation_id", "source", "tradition_term", "claimed_date", "earliest_year", "issue_type", "severity_score", "reason"]
    if header is not None and header == expected_header:
        scores["ranked_csv_exists_and_header"] = 1.0

    # Determine expected ranking from expected anomalies
    if ranked_rows is not None and expected_anomalies is not None:
        # Build ranked expected: filter severity >= 0.5 and sort desc by severity
        exp_list = list(expected_anomalies.values())
        exp_filtered = [r for r in exp_list if _float_or_none(r.get("severity_score")) is not None and float(r["severity_score"]) >= 0.5]
        exp_sorted = sorted(exp_filtered, key=lambda r: (-float(r["severity_score"])))
        # Check rows count and order/rank
        try:
            parsed_rows = []
            for row in ranked_rows:
                # Map to dict by header
                if len(row) != len(expected_header):
                    parsed_rows = None
                    break
                parsed_rows.append(dict(zip(header, row)))
        except Exception:
            parsed_rows = None

        if parsed_rows is not None:
            order_ok = True
            values_match = True
            if len(parsed_rows) != len(exp_sorted):
                order_ok = False
                values_match = False
            else:
                for idx, (got, exp) in enumerate(zip(parsed_rows, exp_sorted)):
                    # Check rank and id/order
                    try:
                        if int(got["rank"]) != (idx + 1):
                            order_ok = False
                        if str(got["citation_id"]) != str(exp["citation_id"]):
                            order_ok = False
                        # Compare key fields
                        if got["source"] != exp["source"]:
                            values_match = False
                        if got["tradition_term"] != exp["tradition_term"]:
                            values_match = False
                        if got["claimed_date"] != exp["claimed_date"]:
                            values_match = False
                        if int(got["earliest_year"]) != int(exp["earliest_year"]):
                            values_match = False
                        if got["issue_type"] != exp["issue_type"]:
                            values_match = False
                        sev_got = _float_or_none(got["severity_score"])
                        sev_exp = _float_or_none(exp["severity_score"])
                        if sev_got is None or sev_exp is None or abs(sev_got - sev_exp) > 1e-9:
                            values_match = False
                        if got["reason"] != exp["reason"]:
                            values_match = False
                    except Exception:
                        order_ok = False
                        values_match = False
                        break
            if order_ok:
                scores["ranked_csv_rows_correct_order_and_ranks"] = 1.0
            if values_match:
                # Also compare against raw anomalies if available to ensure cross-file consistency
                if anomalies_raw is not None:
                    raw_by_id = {str(r.get("citation_id")): r for r in anomalies_raw if "citation_id" in r}
                    cross_ok = True
                    for row in parsed_rows:
                        cid = str(row["citation_id"])
                        raw = raw_by_id.get(cid)
                        if raw is None:
                            cross_ok = False
                            break
                        # Compare the same columns
                        try:
                            if row["source"] != raw.get("source"):
                                cross_ok = False
                                break
                            if row["tradition_term"] != raw.get("tradition_term"):
                                cross_ok = False
                                break
                            if row["claimed_date"] != raw.get("claimed_date"):
                                cross_ok = False
                                break
                            if int(row["earliest_year"]) != int(raw.get("earliest_year")):
                                cross_ok = False
                                break
                            if row["issue_type"] != raw.get("issue_type"):
                                cross_ok = False
                                break
                            sev_row = _float_or_none(row["severity_score"])
                            sev_raw = _float_or_none(raw.get("severity_score"))
                            if sev_row is None or sev_raw is None or abs(sev_row - sev_raw) > 1e-9:
                                cross_ok = False
                                break
                            if row["reason"] != raw.get("reason"):
                                cross_ok = False
                                break
                        except Exception:
                            cross_ok = False
                            break
                    if cross_ok:
                        scores["ranked_csv_values_match_raw"] = 1.0
                else:
                    # If raw not available but values match expected, still give credit
                    scores["ranked_csv_values_match_raw"] = 1.0

    # Email checks
    email_text = _safe_read_text(email_path)
    if email_text:
        has_traditio = re.search(r"\bTraditio\b", email_text, flags=re.IGNORECASE) is not None
        has_path = "output/anomalies_ranked.csv" in email_text
        if has_traditio and has_path:
            scores["email_includes_traditio_and_path"] = 1.0

        # Summarizes top three from ranked CSV
        if header is not None and ranked_rows is not None and header == expected_header:
            # Prepare top K anomalies from ranked CSV
            parsed_ranked = []
            try:
                for row in ranked_rows[:3]:
                    if len(row) != len(expected_header):
                        parsed_ranked = None
                        break
                    parsed_ranked.append(dict(zip(header, row)))
            except Exception:
                parsed_ranked = None
            if parsed_ranked is not None:
                K = len(parsed_ranked)
                # Check that for each, term, claimed_date, earliest_year appear in email
                all_token_mentions = True
                for rec in parsed_ranked:
                    term = rec.get("tradition_term", "")
                    claimed_date = rec.get("claimed_date", "")
                    earliest_year = str(rec.get("earliest_year", ""))
                    # We'll verify presence of these tokens
                    if term and term in email_text and claimed_date and claimed_date in email_text and earliest_year and earliest_year in email_text:
                        continue
                    else:
                        all_token_mentions = False
                        break
                # Also look for a courteous request for review by checking 'review' occurrence
                has_review_request = re.search(r"\breview\b", email_text, flags=re.IGNORECASE) is not None
                if all_token_mentions and has_review_request:
                    scores["email_summarizes_top_anomalies"] = 1.0

                # Severities for top anomalies: check approximate presence of floats
                floats_in_email = _extract_floats(email_text)
                severities_match = True
                for rec in parsed_ranked:
                    sev = _float_or_none(rec.get("severity_score"))
                    if sev is None:
                        continue
                    # Find any float within tolerance
                    found = any(abs(sev - x) <= 0.02 for x in floats_in_email)
                    if not found:
                        severities_match = False
                        break
                # Vacuous true if no ranked entries
                if severities_match:
                    scores["email_includes_severities_for_top_anomalies"] = 1.0

    return scores

def main() -> None:
    # CLI: python generated_validation.py /path/to/workspace
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()