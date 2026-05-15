import json
import csv
import sys
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_json_load(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_yaml_simple_load(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML loader for flat key: value mappings with numeric scalars.
    Supports simple cases like:
      key: 1
      key2: 4.33
    Ignores blank lines and comments (# ...).
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            # malformed
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove inline comments
        if "#" in val:
            val = val.split("#", 1)[0].strip()
        # Interpret as float or int if possible, else keep as string
        if val == "" or val.lower() in {"null", "~"}:
            data[key] = None
        else:
            try:
                if re.fullmatch(r"-?\d+", val):
                    data[key] = int(val)
                else:
                    data[key] = float(val)
            except Exception:
                # strip potential quotes
                v = val.strip().strip("'").strip('"')
                data[key] = v
    return data


def _safe_csv_read_table(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_rows: List[Dict[str, str]] = []
        for r in rows[1:]:
            # pad/truncate to header length
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            elif len(r) > len(header):
                r = r[:len(header)]
            data_rows.append({h: v for h, v in zip(header, r)})
        return header, data_rows
    except Exception:
        return None, None


def _to_float(s: Any) -> Optional[float]:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        s_str = str(s).strip()
        if s_str == "":
            return None
        return float(s_str)
    except Exception:
        return None


def _parse_bool_cell(s: Any) -> Optional[bool]:
    if isinstance(s, bool):
        return s
    if s is None:
        return None
    v = str(s).strip().lower()
    if v in {"true", "t", "yes", "y", "1"}:
        return True
    if v in {"false", "f", "no", "n", "0"}:
        return False
    return None


def _round2(x: float) -> float:
    # Standard round; slight epsilon to reduce binary representation surprises
    return round(x + 1e-12, 2)


def _float_close(a: Optional[float], b: Optional[float], tol: float = 0.01) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _calc_metrics_for_option(opt: Dict[str, Any], att: Dict[str, Any]) -> Dict[str, Any]:
    visits_per_week = _to_float(att.get("visits_per_week")) or 0.0
    weeks_per_month = _to_float(att.get("weeks_per_month")) or 0.0
    childcare_needed_ratio = _to_float(att.get("childcare_needed_ratio")) or 0.0
    class_duration_hours = _to_float(att.get("class_duration_hours")) or 0.0
    max_monthly_budget = _to_float(att.get("max_monthly_budget"))
    max_commute_hours_per_month = _to_float(att.get("max_commute_hours_per_month"))

    membership_monthly_fee = _to_float(opt.get("membership_monthly_fee")) or 0.0
    included_childcare_visits_per_month = _to_float(opt.get("included_childcare_visits_per_month")) or 0.0
    childcare_fee_per_visit = _to_float(opt.get("childcare_fee_per_visit")) or 0.0
    avg_commute_minutes_one_way = _to_float(opt.get("avg_commute_minutes_one_way")) or 0.0

    visits_per_month = visits_per_week * weeks_per_month
    childcare_visits_per_month = visits_per_month * childcare_needed_ratio
    childcare_cost_component = max(childcare_visits_per_month - included_childcare_visits_per_month, 0.0) * childcare_fee_per_visit
    monthly_cost = membership_monthly_fee + childcare_cost_component
    cost_per_visit = (monthly_cost / visits_per_month) if visits_per_month > 0 else None
    commute_hours_per_month = (visits_per_month * avg_commute_minutes_one_way * 2.0) / 60.0
    total_monthly_time_hours = commute_hours_per_month + (visits_per_month * class_duration_hours)

    # Apply 2-dec rounding to computed numeric fields
    computed = {
        "visits_per_month": _round2(visits_per_month),
        "childcare_visits_per_month": _round2(childcare_visits_per_month),
        "childcare_cost_component": _round2(childcare_cost_component),
        "monthly_cost": _round2(monthly_cost),
        "cost_per_visit": _round2(cost_per_visit) if cost_per_visit is not None else None,
        "commute_hours_per_month": _round2(commute_hours_per_month),
        "total_monthly_time_hours": _round2(total_monthly_time_hours),
    }
    computed["within_budget"] = (computed["monthly_cost"] <= (max_monthly_budget if max_monthly_budget is not None else float("inf")))
    computed["within_commute_limit"] = (computed["commute_hours_per_month"] <= (max_commute_hours_per_month if max_commute_hours_per_month is not None else float("inf")))
    return computed


def _index_rows_by_name(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    idx: Dict[str, Dict[str, str]] = {}
    for r in rows:
        name = (r.get("name") or "").strip()
        if name:
            idx[name] = r
    return idx


def _extract_recommended_name_and_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    text = _safe_read_text(path)
    if text is None:
        return None, None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    if not lines:
        return None, text
    first = lines[0]
    prefix = "Recommended option:"
    if first.startswith(prefix):
        rec_name = first[len(prefix):].strip()
        return rec_name if rec_name else None, text
    return None, text


def _line_contains_number(text: str, number: float) -> bool:
    # Search for the formatted number with 2 decimals in the text
    pattern = f"{number:.2f}"
    return pattern in text


def _sentence_mentions_tradeoff(sent: str) -> bool:
    kw = ["cost", "commute", "time", "childcare", "fee"]
    s = sent.lower()
    return any(k in s for k in kw)


def _check_email_file(path: Path) -> Tuple[float, Dict[str, bool]]:
    """
    Returns a score component in [0,1] and detail flags for:
      - has_email1_label
      - has_email2_label
      - email1_subject
      - email2_subject
      - email1_intent_topics
      - email2_intent_topics
    """
    content = _safe_read_text(path)
    flags = {
        "has_email1_label": False,
        "has_email2_label": False,
        "email1_subject": False,
        "email2_subject": False,
        "email1_intent_topics": False,
        "email2_intent_topics": False,
    }
    if content is None:
        return 0.0, flags
    lower = content.lower()
    idx1 = content.find("Email 1")
    idx2 = content.find("Email 2")
    if idx1 != -1:
        flags["has_email1_label"] = True
    if idx2 != -1:
        flags["has_email2_label"] = True
    # Determine sections
    if idx1 != -1:
        end1 = idx2 if (idx2 != -1 and idx2 > idx1) else len(content)
        section1 = content[idx1:end1]
    else:
        section1 = ""
    if idx2 != -1:
        end2 = len(content)
        section2 = content[idx2:end2]
    else:
        section2 = ""
    flags["email1_subject"] = "Subject:" in section1
    flags["email2_subject"] = "Subject:" in section2

    def has_intent_topics(section: str) -> bool:
        s = section.lower()
        trial = any(k in s for k in ["trial", "try", "drop-in", "drop in", "guest pass", "guest-pass"])
        childcare = any(k in s for k in ["childcare", "child care"])
        cancel = any(k in s for k in ["cancel", "cancellation", "pause"])
        return trial and childcare and cancel

    flags["email1_intent_topics"] = has_intent_topics(section1)
    flags["email2_intent_topics"] = has_intent_topics(section2)

    # Score: each flag contributes equally (6 flags)
    points = sum(1.0 for v in flags.values() if v)
    return points / 6.0, flags


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "summary_header_correct": 0.0,
        "summary_rows_coverage": 0.0,
        "summary_values_accuracy": 0.0,
        "summary_booleans_correct": 0.0,
        "recommendation_first_line": 0.0,
        "recommendation_justification_and_limits": 0.0,
        "recommendation_nonchosen_mentions": 0.0,
        "emails_concise_professional_structure_and_intent": 0.0,
        "emails_warm_friendly_structure_and_intent": 0.0,
        "validator_script_references": 0.0,
        "tests_results_pass_lines": 0.0,
    }

    # Load inputs
    options_path = workspace / "input" / "options.json"
    attendance_path = workspace / "input" / "attendance.yaml"
    drafts_path = workspace / "input" / "drafts.md"
    options = _safe_json_load(options_path) or []
    attendance = _safe_yaml_simple_load(attendance_path) or {}

    # Summary CSV checks
    summary_path = workspace / "output" / "summary.csv"
    required_header = [
        "name",
        "visits_per_month",
        "childcare_visits_per_month",
        "childcare_cost_component",
        "monthly_cost",
        "cost_per_visit",
        "commute_hours_per_month",
        "total_monthly_time_hours",
        "within_budget",
        "within_commute_limit",
    ]
    header, rows = _safe_csv_read_table(summary_path)
    if header is not None and rows is not None:
        # header check
        scores["summary_header_correct"] = 1.0 if header == required_header else 0.0

        # coverage: one row per option and only those
        option_names = [o.get("name", "").strip() for o in options if isinstance(o, dict) and o.get("name")]
        summary_names = [r.get("name", "").strip() for r in rows]
        if set(option_names) == set(summary_names) and len(summary_names) == len(option_names):
            scores["summary_rows_coverage"] = 1.0
        else:
            scores["summary_rows_coverage"] = 0.0

        # values and booleans accuracy
        idx = _index_rows_by_name(rows)
        numeric_fields = [
            "visits_per_month",
            "childcare_visits_per_month",
            "childcare_cost_component",
            "monthly_cost",
            "cost_per_visit",
            "commute_hours_per_month",
            "total_monthly_time_hours",
        ]
        total_numeric_checks = 0
        numeric_pass = 0
        total_boolean_checks = 0
        boolean_pass = 0
        for opt in options:
            name = opt.get("name", "").strip()
            if not name or name not in idx:
                # counts as failures for all fields for this option
                total_numeric_checks += len(numeric_fields)
                total_boolean_checks += 2
                continue
            computed = _calc_metrics_for_option(opt, attendance)
            row = idx[name]
            # numeric fields
            for f in numeric_fields:
                expected_val = computed.get(f)
                actual_val = _to_float(row.get(f))
                total_numeric_checks += 1
                if expected_val is None:
                    # if expected None (e.g., cost_per_visit when visits_per_month==0), require cell empty
                    if (row.get(f) is None) or (str(row.get(f)).strip() == ""):
                        numeric_pass += 1
                else:
                    if _float_close(expected_val, actual_val, tol=0.01):
                        numeric_pass += 1
            # booleans
            for bf in ["within_budget", "within_commute_limit"]:
                expected_b = bool(computed.get(bf))
                actual_b = _parse_bool_cell(row.get(bf))
                total_boolean_checks += 1
                if actual_b is not None and actual_b == expected_b:
                    boolean_pass += 1

        scores["summary_values_accuracy"] = (numeric_pass / total_numeric_checks) if total_numeric_checks > 0 else 0.0
        scores["summary_booleans_correct"] = (boolean_pass / total_boolean_checks) if total_boolean_checks > 0 else 0.0
    else:
        # If missing or unreadable, all related checks are 0 by default
        pass

    # Recommendation checks
    recommendation_path = workspace / "output" / "recommendation.md"
    rec_name, rec_text = _extract_recommended_name_and_text(recommendation_path)
    if rec_text is not None and rec_name:
        scores["recommendation_first_line"] = 1.0
        # Find summary values for recommended option
        rec_values: Dict[str, Any] = {}
        if rows is not None:
            rec_row = None
            for r in rows:
                if (r.get("name") or "").strip() == rec_name:
                    rec_row = r
                    break
            if rec_row:
                # Use parsed floats from summary to check presence in text
                mc = _to_float(rec_row.get("monthly_cost"))
                ch = _to_float(rec_row.get("commute_hours_per_month"))
                wb = _parse_bool_cell(rec_row.get("within_budget"))
                wc = _parse_bool_cell(rec_row.get("within_commute_limit"))
                rec_values = {
                    "monthly_cost": mc,
                    "commute_hours_per_month": ch,
                    "within_budget": wb,
                    "within_commute_limit": wc,
                }
        # Justification: mention monthly_cost and commute_hours_per_month values and limits acknowledgment
        just_ok = False
        if rec_text and rec_values.get("monthly_cost") is not None and rec_values.get("commute_hours_per_month") is not None:
            has_mc_num = _line_contains_number(rec_text, _round2(rec_values["monthly_cost"]))
            has_ch_num = _line_contains_number(rec_text, _round2(rec_values["commute_hours_per_month"]))
            # Limits mention logic
            lower_text = rec_text.lower()
            if rec_values.get("within_budget") is True and rec_values.get("within_commute_limit") is True:
                # Should confirm meets both limits -> look for both words budget and commute with "meet/within"
                has_budget_word = "budget" in lower_text
                has_commute_word = "commute" in lower_text
                has_meet_within = any(w in lower_text for w in ["meet", "meets", "within"])
                limits_ok = has_budget_word and has_commute_word and has_meet_within
            else:
                # If fails either, must say which one and why still picked it
                fails_budget = rec_values.get("within_budget") is False
                fails_commute = rec_values.get("within_commute_limit") is False
                budget_mentioned = ("budget" in lower_text)
                commute_mentioned = ("commute" in lower_text)
                reason_words = any(w in lower_text for w in ["still", "despite", "because"])
                limits_ok = True
                if fails_budget:
                    limits_ok = limits_ok and budget_mentioned
                if fails_commute:
                    limits_ok = limits_ok and commute_mentioned
                limits_ok = limits_ok and reason_words
            just_ok = has_mc_num and has_ch_num and limits_ok
        scores["recommendation_justification_and_limits"] = 1.0 if just_ok else 0.0

        # Non-chosen options mentioned with trade-offs
        non_chosen_ok = True
        if rows is not None:
            other_names = [r.get("name", "").strip() for r in rows if (r.get("name", "").strip() and r.get("name", "").strip() != rec_name)]
            text_sentences = re.split(r"(?<=[.!?])\s+", rec_text.strip())
            for other in other_names:
                # find any sentence mentioning the other option and containing tradeoff keyword
                found = False
                for sent in text_sentences:
                    if other in sent:
                        if _sentence_mentions_tradeoff(sent):
                            found = True
                            break
                if not found:
                    non_chosen_ok = False
                    break
        else:
            non_chosen_ok = False
        scores["recommendation_nonchosen_mentions"] = 1.0 if non_chosen_ok else 0.0
    else:
        scores["recommendation_first_line"] = 0.0
        scores["recommendation_justification_and_limits"] = 0.0
        scores["recommendation_nonchosen_mentions"] = 0.0

    # Email rewrites checks
    concise_path = workspace / "output" / "revised_emails" / "concise_professional.md"
    warm_path = workspace / "output" / "revised_emails" / "warm_friendly.md"
    concise_score, _ = _check_email_file(concise_path)
    warm_score, _ = _check_email_file(warm_path)
    scores["emails_concise_professional_structure_and_intent"] = concise_score
    scores["emails_warm_friendly_structure_and_intent"] = warm_score

    # Validator script existence and references
    validator_path = workspace / "scripts" / "validate.py"
    vtxt = _safe_read_text(validator_path)
    if vtxt is not None:
        has_inputs = ("input/options.json" in vtxt) and ("input/attendance.yaml" in vtxt) and ("output/summary.csv" in vtxt)
        has_pass = "PASS:" in vtxt
        scores["validator_script_references"] = 1.0 if (has_inputs and has_pass) else 0.0
    else:
        scores["validator_script_references"] = 0.0

    # Tests results checks
    results_path = workspace / "tests" / "results.txt"
    rtxt = _safe_read_text(results_path)
    if rtxt is not None:
        lines = [ln.strip() for ln in rtxt.splitlines() if ln.strip()]
        pass_lines = [ln for ln in lines if ln.upper().startswith("PASS:")]
        fail_lines = [ln for ln in lines if ln.upper().startswith("FAIL:")]
        # Basic conditions: at least some PASS lines, and no FAIL lines
        cond_basic = (len(pass_lines) >= 3) and (len(fail_lines) == 0)
        # Contains PASS lines referencing each option name and some key terms
        names_ok = True
        for opt in options:
            n = opt.get("name", "").strip()
            if n:
                if not any(n in pl for pl in pass_lines):
                    names_ok = False
                    break
        # Key term presence
        lower_pass = " ".join(pass_lines).lower()
        has_monthly_cost = "monthly_cost" in lower_pass
        has_commute = "commute" in lower_pass
        has_emails = any(k in lower_pass for k in ["emails", "subject", "revised_emails"])
        has_columns = "column" in lower_pass or "columns" in lower_pass
        cond = cond_basic and names_ok and has_monthly_cost and has_commute and has_emails and has_columns
        scores["tests_results_pass_lines"] = 1.0 if cond else 0.0
    else:
        scores["tests_results_pass_lines"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()