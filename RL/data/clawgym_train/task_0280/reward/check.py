import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _safe_read_tsv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            return list(reader)
    except Exception:
        return None


def _safe_read_jsonl(path: Path) -> Optional[List[Dict]]:
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _to_int(value) -> Optional[int]:
    try:
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value).strip()
        if s == "":
            return 0
        return int(float(s))
    except Exception:
        return None


def _compute_expected_dataset(workspace: Path) -> Optional[List[Dict]]:
    # Load inputs
    comm_p = workspace / "input" / "community_projects.tsv"
    budget_p = workspace / "input" / "budget_spending.csv"
    findings_p = workspace / "input" / "audit_findings.jsonl"

    community = _safe_read_tsv(comm_p)
    budget = _safe_read_csv(budget_p)
    findings = _safe_read_jsonl(findings_p)

    if community is None or budget is None or findings is None:
        return None

    # Build budget totals
    totals: Dict[str, int] = {}
    for row in budget:
        pid = row.get("project_id", "")
        amt = _to_int(row.get("amount_spent"))
        if pid is None or amt is None:
            return None
        totals[pid] = totals.get(pid, 0) + amt

    # Build findings per project
    sev_weights = {"High": 3, "Moderate": 2, "Low": 1}
    proj_findings: Dict[str, Dict] = {}
    for rec in findings:
        pid = rec.get("project_id")
        sev = rec.get("severity")
        ftype = rec.get("type")
        if pid is None or sev not in sev_weights or ftype is None:
            return None
        d = proj_findings.setdefault(pid, {
            "High": 0,
            "Moderate": 0,
            "Low": 0,
            "type_weights": {}
        })
        d[sev] += 1
        d["type_weights"][ftype] = d["type_weights"].get(ftype, 0) + sev_weights[sev]

    # Assemble projects list
    expected: List[Dict] = []
    for row in community:
        pid = row.get("project_id")
        title = row.get("title")
        nbh = row.get("neighborhood")
        if pid is None or title is None or nbh is None:
            return None

        total_spent = totals.get(pid, 0)
        f = proj_findings.get(pid)
        if f is None:
            fh = 0
            fm = 0
            fl = 0
            weighted = 0
            primary_type = ""
            top_types = ""
        else:
            fh = f.get("High", 0)
            fm = f.get("Moderate", 0)
            fl = f.get("Low", 0)
            weighted = fh * 3 + fm * 2 + fl * 1
            type_weights = f.get("type_weights", {})
            if not type_weights:
                primary_type = ""
                top_types = ""
            else:
                # Determine primary_finding_type by highest weight, tie-breaker alphabetical
                # Determine top two types sorted by weight desc then alphabetically
                items = sorted(type_weights.items(), key=lambda kv: (-kv[1], kv[0]))
                primary_type = items[0][0]
                top_two = items[:2]
                top_types = ";".join([t for t, w in top_two])

        expected.append({
            "project_id": pid,
            "title": title,
            "neighborhood": nbh,
            "total_amount_spent": int(total_spent),
            "findings_high": int(fh),
            "findings_moderate": int(fm),
            "findings_low": int(fl),
            "weighted_risk_score": int(weighted),
            "primary_finding_type": primary_type,
            "top_finding_types": top_types,
        })

    # Sort by weighted desc, total_spent desc, project_id asc
    expected.sort(key=lambda r: (-r["weighted_risk_score"], -r["total_amount_spent"], r["project_id"]))
    # Add rank starting at 1
    for i, r in enumerate(expected, start=1):
        r["rank"] = i

    return expected


def _parse_csv_output(path: Path) -> Optional[Tuple[List[str], List[Dict]]]:
    data = _safe_read_csv(path)
    if data is None:
        return None
    # Extract header order
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        header = None
    if header is None:
        return None

    # Coerce types for known numeric fields
    records: List[Dict] = []
    for row in data:
        rec: Dict = dict(row)
        # Coerce numeric fields safely; if missing, mark failure by setting value None
        for k in ["total_amount_spent", "findings_high", "findings_moderate", "findings_low", "weighted_risk_score", "rank"]:
            if k in rec:
                rec[k] = _to_int(rec[k])
            else:
                rec[k] = None
        records.append(rec)
    return header, records


def _parse_json_output(path: Path) -> Optional[List[Dict]]:
    try:
        txt = _safe_read_text(path)
        if txt is None:
            return None
        arr = json.loads(txt)
        if not isinstance(arr, list):
            return None
        # Coerce numeric fields
        out = []
        for obj in arr:
            if not isinstance(obj, dict):
                return None
            rec = dict(obj)
            for k in ["total_amount_spent", "findings_high", "findings_moderate", "findings_low", "weighted_risk_score", "rank"]:
                if k in rec:
                    rec[k] = _to_int(rec[k])
                else:
                    rec[k] = None
            out.append(rec)
        return out
    except Exception:
        return None


def _datasets_match(expected: List[Dict], actual: List[Dict]) -> bool:
    # Compare by project_id mapping
    exp_map = {r["project_id"]: r for r in expected}
    act_map = {r.get("project_id"): r for r in actual if r.get("project_id") is not None}
    if set(exp_map.keys()) != set(act_map.keys()):
        return False
    fields = ["project_id", "title", "neighborhood", "total_amount_spent",
              "findings_high", "findings_moderate", "findings_low",
              "weighted_risk_score", "primary_finding_type", "top_finding_types", "rank"]
    for pid, e in exp_map.items():
        a = act_map[pid]
        for k in fields:
            if a.get(k) != e.get(k):
                return False
    return True


def _check_csv_order_and_rank(expected: List[Dict], header: List[str], rows: List[Dict]) -> bool:
    # Header exact order
    required_header = ["project_id", "title", "neighborhood", "total_amount_spent",
                       "findings_high", "findings_moderate", "findings_low",
                       "weighted_risk_score", "primary_finding_type", "top_finding_types", "rank"]
    if header != required_header:
        return False
    # Rows length must match expected
    if len(rows) != len(expected):
        return False
    # Check sorted order and rank correctness and exact row equality by position
    for idx, (exp_row, act_row) in enumerate(zip(expected, rows), start=1):
        # Ensure keys exist
        for k in required_header:
            if k not in act_row:
                return False
        # Rank equals idx
        if act_row.get("rank") != idx:
            return False
        # Compare relevant fields exactly
        for k in required_header:
            if k in ["total_amount_spent", "findings_high", "findings_moderate", "findings_low", "weighted_risk_score", "rank"]:
                if act_row.get(k) != exp_row.get(k):
                    return False
            else:
                if str(act_row.get(k, "")) != str(exp_row.get(k, "")):
                    return False
    return True


def _csv_json_consistent(csv_rows: List[Dict], json_rows: List[Dict]) -> bool:
    csv_map = {r.get("project_id"): r for r in csv_rows if r.get("project_id") is not None}
    json_map = {r.get("project_id"): r for r in json_rows if r.get("project_id") is not None}
    if set(csv_map.keys()) != set(json_map.keys()):
        return False
    for pid in csv_map:
        c = csv_map[pid]
        j = json_map[pid]
        # Compare fields
        for k in ["title", "neighborhood", "total_amount_spent", "findings_high", "findings_moderate", "findings_low",
                  "weighted_risk_score", "primary_finding_type", "top_finding_types", "rank"]:
            if c.get(k) != j.get(k):
                return False
    return True


def _word_count(text: str) -> int:
    # Count tokens as words using regex word boundaries
    words = re.findall(r"\b\w+\b", text, flags=re.UNICODE)
    return len(words)


def _find_sentence_bounds(text: str, start: int, end: int) -> Tuple[int, int]:
    # Find previous sentence terminator before 'start' and next terminator after 'end'
    prev = max(text.rfind('.', 0, start), text.rfind('!', 0, start), text.rfind('?', 0, start))
    next_pos_dot = text.find('.', end)
    next_pos_ex = text.find('!', end)
    next_pos_qm = text.find('?', end)
    next_candidates = [p for p in [next_pos_dot, next_pos_ex, next_pos_qm] if p != -1]
    if not next_candidates:
        next_term = len(text)
    else:
        next_term = min(next_candidates) + 1
    sent_start = 0 if prev == -1 else prev + 1
    sent_end = next_term
    return (sent_start, sent_end)


def _check_top_three_sentence(letter: str, expected_top_three: List[Dict]) -> bool:
    # Build expected display strings
    items = []
    for r in expected_top_three:
        items.append(f'{r["title"]} ({r["neighborhood"]} — {r["primary_finding_type"]})')
    pattern = re.escape(items[0]) + r"\s*;\s*" + re.escape(items[1]) + r"\s*;\s*" + re.escape(items[2])
    m = re.search(pattern, letter, flags=re.S)
    if not m:
        return False
    # Verify that the match resides within a single sentence (no . ! ? inside the matched span)
    span_start, span_end = m.span()
    if any(ch in letter[span_start:span_end] for ch in [".", "!", "?"]):
        return False
    # Optionally ensure that the matched span is within one sentence by checking bounds
    s_start, s_end = _find_sentence_bounds(letter, span_start, span_end)
    # Ensure there is exactly one occurrence of the triple in that sentence
    sentence_text = letter[s_start:s_end]
    if len(re.findall(pattern, sentence_text, flags=re.S)) != 1:
        return False
    # Ensure exactly two semicolons between items in the sentence occurrence
    occ = re.search(pattern, sentence_text, flags=re.S)
    if occ:
        inner = sentence_text[occ.start():occ.end()]
        if inner.count(";") != 2:
            return False
    return True


def _check_guidance_and_email(letter: str) -> bool:
    # Must mention how the ranking will guide restitution priorities and invite feedback at given email
    # Deterministic keyword checks
    email_ok = "mayorretired@example.org" in letter
    # Both 'ranking' and 'restitution' and 'priority' or 'priorities'
    lower = letter.lower()
    has_ranking = "ranking" in lower
    has_restitution = "restitution" in lower
    has_priority = ("priority" in lower) or ("priorities" in lower)
    return email_ok and has_ranking and has_restitution and has_priority


def _check_tone_indicators(letter: str) -> bool:
    lower = letter.lower()
    contrite = any(k in lower for k in ["sorry", "apolog", "regret", "remorse"])
    accountable = any(k in lower for k in ["accountab", "responsib", "own up", "we own", "we take responsibility"])
    forward = any(k in lower for k in ["will", "plan", "commit", "next", "future", "moving forward"])
    # Require at least contrite + accountable + forward-looking indicators
    return contrite and accountable and forward


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "projects_csv_exists_and_header": 0.0,
        "projects_csv_content_correct": 0.0,
        "projects_json_exists_and_fields": 0.0,
        "projects_json_content_correct": 0.0,
        "csv_json_consistency": 0.0,
        "letter_exists_and_word_count": 0.0,
        "letter_top_three_sentence": 0.0,
        "letter_guidance_and_email": 0.0,
        "letter_tone_indicators": 0.0,
    }

    # Compute expected dataset from inputs
    expected = _compute_expected_dataset(workspace)

    # Paths to outputs
    csv_path = workspace / "output" / "projects_risk_ranked.csv"
    json_path = workspace / "output" / "projects_risk_ranked.json"
    letter_path = workspace / "output" / "outreach_letter_rewritten.txt"

    # CSV checks
    parsed_csv = _parse_csv_output(csv_path) if csv_path.exists() else None
    if parsed_csv is not None and expected is not None:
        header, csv_rows = parsed_csv
        # header & order check
        required_header = ["project_id", "title", "neighborhood", "total_amount_spent",
                           "findings_high", "findings_moderate", "findings_low",
                           "weighted_risk_score", "primary_finding_type", "top_finding_types", "rank"]
        if header == required_header:
            scores["projects_csv_exists_and_header"] = 1.0
        else:
            scores["projects_csv_exists_and_header"] = 0.0
        # Check content correctness, order and rank
        if _check_csv_order_and_rank(expected, header, csv_rows):
            scores["projects_csv_content_correct"] = 1.0
    else:
        # If CSV exists but malformed header, still mark exists? Spec asks for existence & header
        if csv_path.exists():
            # Try basic header read
            try:
                with csv_path.open("r", encoding="utf-8") as f:
                    first_line = f.readline()
                if first_line:
                    scores["projects_csv_exists_and_header"] = 0.0
            except Exception:
                scores["projects_csv_exists_and_header"] = 0.0

    # JSON checks
    json_rows = _parse_json_output(json_path) if json_path.exists() else None
    if json_rows is not None:
        # Check fields presence in each object
        required_fields = set(["project_id", "title", "neighborhood", "total_amount_spent",
                               "findings_high", "findings_moderate", "findings_low",
                               "weighted_risk_score", "primary_finding_type", "top_finding_types", "rank"])
        field_ok = True
        for obj in json_rows:
            if set(obj.keys()) != required_fields:
                field_ok = False
                break
        if field_ok:
            scores["projects_json_exists_and_fields"] = 1.0
        # Content correct (compare against expected, ignore ordering by sorting on rank)
        if expected is not None:
            # Reorder json_rows by rank ascending for comparison if possible
            try:
                json_sorted = sorted(json_rows, key=lambda r: (r.get("rank") if isinstance(r.get("rank"), int) else 10**9))
            except Exception:
                json_sorted = json_rows
            if _datasets_match(expected, json_sorted):
                scores["projects_json_content_correct"] = 1.0

    # CSV-JSON consistency
    if parsed_csv is not None and json_rows is not None:
        _, csv_rows = parsed_csv
        if _csv_json_consistent(csv_rows, json_rows):
            scores["csv_json_consistency"] = 1.0

    # Letter checks
    letter_text = _safe_read_text(letter_path) if letter_path.exists() else None
    if letter_text is not None:
        wc = _word_count(letter_text)
        if 150 <= wc <= 180:
            scores["letter_exists_and_word_count"] = 1.0
        # Top three sentence check requires expected
        if expected is not None and len(expected) >= 3:
            top_three = expected[:3]
            if _check_top_three_sentence(letter_text, top_three):
                scores["letter_top_three_sentence"] = 1.0
        # Guidance and email
        if _check_guidance_and_email(letter_text):
            scores["letter_guidance_and_email"] = 1.0
        # Tone indicators
        if _check_tone_indicators(letter_text):
            scores["letter_tone_indicators"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()