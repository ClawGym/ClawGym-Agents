import json
import sys
import re
import csv
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None, None


def _parse_int(s: str) -> Optional[int]:
    if s is None:
        return None
    ss = s.strip()
    if ss.lower() == "na":
        return None
    ss = re.sub(r"[,\$\s]", "", ss)
    if ss == "":
        return None
    try:
        return int(ss)
    except Exception:
        try:
            return int(float(ss))
        except Exception:
            return None


def _parse_float(s: str) -> Optional[float]:
    if s is None:
        return None
    ss = s.strip()
    if ss.lower() == "na":
        return None
    ss = ss.replace("%", "")
    ss = re.sub(r"[,\$\s]", "", ss)
    if ss == "":
        return None
    try:
        return float(ss)
    except Exception:
        return None


def _is_sorted_desc(values: List[float]) -> bool:
    for i in range(1, len(values)):
        if values[i] > values[i - 1] + 1e-12:
            return False
    return True


def _close(a: float, b: float, rel: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def _parse_markdown_metrics(md_text: str) -> List[Dict[str, str]]:
    lines = md_text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "metrics discussed":
            start_idx = i
            break
    if start_idx is None:
        return []

    table_start = None
    for i in range(start_idx + 1, len(lines)):
        if "|" in lines[i]:
            header_line = lines[i]
            if "ProgramID" in header_line and "BudgetUSD" in header_line:
                table_start = i
                break
    if table_start is None:
        return []

    table_lines = []
    for i in range(table_start, len(lines)):
        l = lines[i]
        if "|" not in l:
            break
        table_lines.append(l)

    if len(table_lines) < 3:
        return []

    header = [c.strip() for c in table_lines[0].strip().strip("|").split("|")]
    rows = []
    for row_line in table_lines[2:]:
        cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        required = ["ProgramID", "ProgramName", "BudgetUSD", "HouseholdsServed", "HumanIncidentsPrevented", "WildlifeSaved"]
        if not all(k in row for k in required):
            continue
        rows.append({
            "ProgramID": row["ProgramID"],
            "ProgramName": row["ProgramName"],
            "BudgetUSD": row["BudgetUSD"],
            "HouseholdsServed": row["HouseholdsServed"],
            "HumanIncidentsPrevented": row["HumanIncidentsPrevented"],
            "WildlifeSaved": row["WildlifeSaved"],
        })
    return rows


def _aggregate_program_metrics(rows_list: List[List[Dict[str, str]]]) -> Dict[str, Dict[str, float]]:
    agg: Dict[str, Dict[str, float]] = {}
    name_by_id: Dict[str, str] = {}
    for rows in rows_list:
        for r in rows:
            pid = r["ProgramID"]
            name = r["ProgramName"]
            b = _parse_int(r["BudgetUSD"]) or 0
            h = _parse_int(r["HouseholdsServed"]) or 0
            hi = _parse_int(r["HumanIncidentsPrevented"]) or 0
            ws = _parse_int(r["WildlifeSaved"]) or 0
            if pid not in agg:
                agg[pid] = {
                    "TotalBudgetUSD": 0,
                    "TotalHouseholdsServed": 0,
                    "TotalHumanIncidentsPrevented": 0,
                    "TotalWildlifeSaved": 0,
                }
                name_by_id[pid] = name
            agg[pid]["TotalBudgetUSD"] += b
            agg[pid]["TotalHouseholdsServed"] += h
            agg[pid]["TotalHumanIncidentsPrevented"] += hi
            agg[pid]["TotalWildlifeSaved"] += ws
            if not name_by_id.get(pid):
                name_by_id[pid] = name
    for pid, vals in agg.items():
        h = vals["TotalHouseholdsServed"]
        hi = vals["TotalHumanIncidentsPrevented"]
        budget = vals["TotalBudgetUSD"]
        if h == 0:
            vals["CostPerHouseholdUSD"] = None
        else:
            vals["CostPerHouseholdUSD"] = budget / h
        if hi == 0:
            vals["CostPerIncidentUSD"] = None
        else:
            vals["CostPerIncidentUSD"] = budget / hi
        vals["ProgramName"] = name_by_id.get(pid, "")
    return agg


def _extract_action_items(md_text: str) -> List[str]:
    lines = md_text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "action items":
            start_idx = i
            break
    if start_idx is None:
        return []
    items = []
    for i in range(start_idx + 1, len(lines)):
        l = lines[i].rstrip()
        if l.strip().startswith("-") or l.strip().startswith("*"):
            bullet = re.sub(r"^\s*[-*]\s*", "", l).strip()
            if bullet:
                items.append(bullet)
        elif l.strip() == "":
            continue
        else:
            break
    return items


def _number_variants(value: int) -> List[str]:
    s = str(value)
    variants = {s}
    parts = []
    tmp = s
    while len(tmp) > 3:
        parts.insert(0, tmp[-3:])
        tmp = tmp[:-3]
    parts.insert(0, tmp)
    comma = ",".join(parts)
    variants.add(comma)
    variants.add("$" + s)
    variants.add("$" + comma)
    return list(variants)


def _contains_any_number(text: str, values: List[int]) -> bool:
    for v in values:
        for variant in _number_variants(v):
            if variant in text:
                return True
    return False


def _find_sentence_with_keywords(text: str, must: List[str], any_of: List[str]) -> bool:
    sentences = re.split(r"(?<=[\.\!\?])\s+", text)
    for s in sentences:
        s_low = s.lower()
        if all(m in s_low for m in must) and any(a in s_low for a in any_of):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "metrics_by_program_exists": 0.0,
        "metrics_by_program_columns_and_sort": 0.0,
        "metrics_by_program_program_set": 0.0,
        "metrics_by_program_aggregates_correct": 0.0,
        "metrics_by_program_costs_correct": 0.0,
        "attendance_summary_exists": 0.0,
        "attendance_summary_columns_and_sort": 0.0,
        "attendance_summary_counts_correct": 0.0,
        "attendance_summary_percents_correct": 0.0,
        "meeting_summary_exists": 0.0,
        "meeting_summary_totals_present": 0.0,
        "meeting_summary_top2_present": 0.0,
        "meeting_summary_efficiency_sentence_present": 0.0,
        "meeting_summary_action_items_present": 0.0,
        "meeting_summary_high_cost_callout_present": 0.0,
        "email_to_editor_exists": 0.0,
        "email_subject_and_length": 0.0,
        "email_includes_computed_stats": 0.0,
        "email_skeptical_framing_and_ask": 0.0,
        "reproducibility_files_exist": 0.0,
        "run_log_nonempty": 0.0,
        "reproduce_md_contains_command": 0.0,
    }

    minutes1_path = workspace / "input" / "meeting_minutes_session1.md"
    minutes2_path = workspace / "input" / "meeting_minutes_session2.md"
    attendees_path = workspace / "input" / "attendees.csv"

    minutes1_text = _read_text(minutes1_path) or ""
    minutes2_text = _read_text(minutes2_path) or ""

    metrics_rows1 = _parse_markdown_metrics(minutes1_text) if minutes1_text else []
    metrics_rows2 = _parse_markdown_metrics(minutes2_text) if minutes2_text else []

    expected_agg = _aggregate_program_metrics([metrics_rows1, metrics_rows2]) if (metrics_rows1 or metrics_rows2) else {}

    total_budget = sum(v["TotalBudgetUSD"] for v in expected_agg.values()) if expected_agg else None
    total_households = sum(v["TotalHouseholdsServed"] for v in expected_agg.values()) if expected_agg else None
    total_incidents = sum(v["TotalHumanIncidentsPrevented"] for v in expected_agg.values()) if expected_agg else None
    total_wildlife = sum(v["TotalWildlifeSaved"] for v in expected_agg.values()) if expected_agg else None

    high_cpi_programs = []
    if expected_agg:
        for pid, data in expected_agg.items():
            cpi = data.get("CostPerIncidentUSD")
            if cpi is not None and cpi > 3000:
                high_cpi_programs.append(pid)
        high_cpi_programs.sort()

    out_dir = workspace / "out"
    metrics_csv = out_dir / "metrics_by_program.csv"
    attendance_csv = out_dir / "attendance_summary.csv"
    meeting_md = out_dir / "meeting_summary.md"
    email_txt = out_dir / "email_to_editor.txt"
    run_log = out_dir / "run.log"
    reproduce_md = out_dir / "REPRODUCE.md"

    if metrics_csv.exists():
        scores["metrics_by_program_exists"] = 1.0
        headers, rows = _load_csv(metrics_csv)
        expected_cols = [
            "ProgramID",
            "ProgramName",
            "TotalBudgetUSD",
            "TotalHouseholdsServed",
            "TotalHumanIncidentsPrevented",
            "TotalWildlifeSaved",
            "CostPerHouseholdUSD",
            "CostPerIncidentUSD",
        ]
        if headers == expected_cols and rows is not None:
            budgets = []
            ok_parse = True
            for r in rows:
                v = _parse_int(r.get("TotalBudgetUSD", ""))
                if v is None:
                    ok_parse = False
                    break
                budgets.append(float(v))
            if ok_parse and _is_sorted_desc(budgets):
                scores["metrics_by_program_columns_and_sort"] = 1.0

            if expected_agg:
                output_pids = {r.get("ProgramID", "") for r in rows}
                expected_pids = set(expected_agg.keys())
                if output_pids == expected_pids:
                    scores["metrics_by_program_program_set"] = 1.0

            if expected_agg:
                sums_ok = True
                costs_ok = True
                for r in rows:
                    pid = r.get("ProgramID", "")
                    if pid not in expected_agg:
                        sums_ok = False
                        costs_ok = False
                        break
                    exp = expected_agg[pid]
                    for k_out, k_exp in [
                        ("TotalBudgetUSD", "TotalBudgetUSD"),
                        ("TotalHouseholdsServed", "TotalHouseholdsServed"),
                        ("TotalHumanIncidentsPrevented", "TotalHumanIncidentsPrevented"),
                        ("TotalWildlifeSaved", "TotalWildlifeSaved"),
                    ]:
                        v_out = _parse_int(r.get(k_out, ""))
                        v_exp = int(exp[k_exp])
                        if v_out is None or v_out != v_exp:
                            sums_ok = False
                            break
                    cph_out_raw = r.get("CostPerHouseholdUSD", "")
                    cpi_out_raw = r.get("CostPerIncidentUSD", "")
                    cph_out = _parse_float(cph_out_raw)
                    cpi_out = _parse_float(cpi_out_raw)
                    exp_cph = exp.get("CostPerHouseholdUSD")
                    exp_cpi = exp.get("CostPerIncidentUSD")
                    if exp_cph is None:
                        if not (isinstance(cph_out_raw, str) and cph_out_raw.strip().lower() == "na"):
                            costs_ok = False
                    else:
                        if cph_out is None or not _close(cph_out, exp_cph):
                            costs_ok = False
                    if exp_cpi is None:
                        if not (isinstance(cpi_out_raw, str) and cpi_out_raw.strip().lower() == "na"):
                            costs_ok = False
                    else:
                        if cpi_out is None or not _close(cpi_out, exp_cpi):
                            costs_ok = False
                if sums_ok:
                    scores["metrics_by_program_aggregates_correct"] = 1.0
                if costs_ok:
                    scores["metrics_by_program_costs_correct"] = 1.0

    if attendance_csv.exists():
        scores["attendance_summary_exists"] = 1.0
        a_headers, a_rows = _load_csv(attendance_csv)
        if a_headers == ["AffiliationType", "Count", "PercentOfTotal"] and a_rows is not None:
            counts = []
            sorted_ok = True
            for r in a_rows:
                c = _parse_int(r.get("Count", ""))
                if c is None:
                    sorted_ok = False
                    break
                counts.append(float(c))
            if sorted_ok and _is_sorted_desc(counts):
                scores["attendance_summary_columns_and_sort"] = 1.0

            headers_in, rows_in = _load_csv(attendees_path)
            if headers_in and rows_in is not None:
                total_rows = len(rows_in)
                counts_exp: Dict[str, int] = {}
                for rr in rows_in:
                    aff = rr.get("AffiliationType", "").strip()
                    counts_exp[aff] = counts_exp.get(aff, 0) + 1
                counts_ok = True
                perc_ok = True
                perc_values = []
                for r in a_rows:
                    aff = r.get("AffiliationType", "").strip()
                    cnt = _parse_int(r.get("Count", ""))
                    if aff not in counts_exp or cnt is None or counts_exp[aff] != cnt:
                        counts_ok = False
                    p = _parse_float(r.get("PercentOfTotal", ""))
                    if p is None:
                        perc_ok = False
                    else:
                        perc_values.append(p)
                if counts_ok:
                    scores["attendance_summary_counts_correct"] = 1.0
                if perc_values:
                    sum_perc = sum(perc_values)
                    scale_100 = abs(sum_perc - 100.0) < 1e-2
                    scale_1 = abs(sum_perc - 1.0) < 1e-3
                    if scale_100 or scale_1:
                        perc_ok2 = True
                        for r in a_rows:
                            aff = r.get("AffiliationType", "").strip()
                            cnt = counts_exp.get(aff, 0)
                            p = _parse_float(r.get("PercentOfTotal", ""))
                            if p is None:
                                perc_ok2 = False
                                break
                            target = (cnt / total_rows) * (100.0 if scale_100 else 1.0)
                            if not _close(p, target, rel=1e-4, abs_tol=1e-4):
                                perc_ok2 = False
                                break
                        if perc_ok2:
                            scores["attendance_summary_percents_correct"] = 1.0
                    else:
                        perc_ok2 = True
                        for r in a_rows:
                            aff = r.get("AffiliationType", "").strip()
                            cnt = counts_exp.get(aff, 0)
                            p = _parse_float(r.get("PercentOfTotal", ""))
                            if p is None:
                                perc_ok2 = False
                                break
                            ok_this = _close(p, (cnt / total_rows) * 100.0, rel=1e-4, abs_tol=1e-4) or _close(p, (cnt / total_rows), rel=1e-4, abs_tol=1e-4)
                            if not ok_this:
                                perc_ok2 = False
                                break
                        if perc_ok2:
                            scores["attendance_summary_percents_correct"] = 1.0

    if meeting_md.exists():
        scores["meeting_summary_exists"] = 1.0
        mtext = _read_text(meeting_md) or ""
        totals_ok = False
        if all(v is not None for v in [total_budget, total_households, total_incidents, total_wildlife]):
            totals_ok = (
                _contains_any_number(mtext, [int(total_budget)]) and
                _contains_any_number(mtext, [int(total_households)]) and
                _contains_any_number(mtext, [int(total_incidents)]) and
                _contains_any_number(mtext, [int(total_wildlife)])
            )
        if totals_ok:
            scores["meeting_summary_totals_present"] = 1.0

        top2_ok = False
        if expected_agg:
            sorted_items = sorted(expected_agg.items(), key=lambda kv: kv[1]["TotalBudgetUSD"], reverse=True)
            top_two = sorted_items[:2]
            conditions = []
            for pid, data in top_two:
                name = data.get("ProgramName", "")
                amount = int(data.get("TotalBudgetUSD", 0))
                cond = (name and (name in mtext)) and _contains_any_number(mtext, [amount])
                conditions.append(cond)
            top2_ok = all(conditions)
        if top2_ok:
            scores["meeting_summary_top2_present"] = 1.0

        if _find_sentence_with_keywords(
            mtext,
            must=["human"],
            any_of=["budget", "cost", "efficient", "efficiency"]
        ):
            scores["meeting_summary_efficiency_sentence_present"] = 1.0

        bullets = re.findall(r"(?m)^\s*[-*]\s+.+$", mtext)
        action_phrases = [
            "Publish monthly hotline stats",
            "independent review",
            "sponsorship",
            "Draft MOU",
            "cost-per-incident",
            "grant matches",
        ]
        phrase_ok = all((p.lower() in mtext.lower()) for p in action_phrases)
        ids_ok = all((pid in mtext) for pid in ["P-101", "P-102", "P-103", "P-105"])
        if len(bullets) >= 6 and phrase_ok and ids_ok:
            scores["meeting_summary_action_items_present"] = 1.0

        callout_ok = False
        if high_cpi_programs:
            has_3000 = ("3000" in mtext) or ("3,000" in mtext)
            ids_present = all(pid in mtext for pid in high_cpi_programs)
            mentions_incident = ("incident" in mtext.lower()) or ("costperincident" in mtext.lower())
            callout_ok = has_3000 and ids_present and mentions_incident
        if callout_ok:
            scores["meeting_summary_high_cost_callout_present"] = 1.0

    if email_txt.exists():
        scores["email_to_editor_exists"] = 1.0
        etext = _read_text(email_txt) or ""
        lines = etext.splitlines()
        if lines:
            first = lines[0].strip()
            second = lines[1].strip() if len(lines) > 1 else None
            subject_ok = first.lower().startswith("subject:")
            blank_after = (second == "") if second is not None else False
            body = "\n".join(lines[2:]) if len(lines) > 2 else ""
            words = re.findall(r"\b\w+\b", body)
            length_ok = 120 <= len(words) <= 200
            if subject_ok and blank_after and length_ok:
                scores["email_subject_and_length"] = 1.0

            stats_values: List[int] = []
            if total_budget is not None:
                stats_values.append(int(total_budget))
            if total_households is not None:
                stats_values.append(int(total_households))
            if total_incidents is not None:
                stats_values.append(int(total_incidents))
            if total_wildlife is not None:
                stats_values.append(int(total_wildlife))
            if expected_agg:
                for pid, data in expected_agg.items():
                    stats_values.append(int(data["TotalBudgetUSD"]))
                for pid, data in expected_agg.items():
                    cpi = data.get("CostPerIncidentUSD")
                    if cpi is not None:
                        stats_values.append(int(round(cpi)))
            found_count = 0
            for v in stats_values:
                if _contains_any_number(body, [v]):
                    found_count += 1
                if found_count >= 2:
                    break
            if found_count >= 2:
                scores["email_includes_computed_stats"] = 1.0

            body_low = body.lower()
            framing = ("human" in body_low) and (any(x in body_low for x in ["funds", "budget", "spend", "spending", "allocation"])) and (any(x in body_low for x in ["question", "skeptic", "doubt", "reallocate", "redirect"]))
            tail = body_low[-200:] if len(body_low) > 200 else body_low
            ask = any(x in tail for x in ["approval", "approve", "sign off", "sign-off", "green light", "go-ahead", "permission", "next steps"])
            if framing and ask:
                scores["email_skeptical_framing_and_ask"] = 1.0

    reproduce_exist = reproduce_md.exists()
    runlog_exist = run_log.exists()
    if reproduce_exist and runlog_exist:
        scores["reproducibility_files_exist"] = 1.0

    if runlog_exist:
        content = _read_text(run_log) or ""
        if content.strip():
            scores["run_log_nonempty"] = 1.0

    if reproduce_exist:
        rtext = _read_text(reproduce_md) or ""
        lines_r = rtext.splitlines()
        good = False
        needed = ["input/meeting_minutes_session1.md", "input/meeting_minutes_session2.md", "input/attendees.csv", "out"]
        for ln in lines_r:
            ln_low = ln.lower()
            if all(n in ln_low for n in needed):
                good = True
                break
        if good:
            scores["reproduce_md_contains_command"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()