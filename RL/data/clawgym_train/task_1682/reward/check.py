import json
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv(path: Path, delimiter: str = ",") -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            rows = list(reader)
            # Validate header exists
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _unquote_and_unescape_scalar(val: str) -> str:
    s = val.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        s = s[1:-1]
    s = s.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")
    return s


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, root)]
    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        m = re.match(r"^(\s*)([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if not m:
            return None
        indent_str, key, value = m.groups()
        indent = len(indent_str.replace("\t", "  "))
        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        parent = stack[-1][1]
        if value == "" or value is None:
            new_map: Dict[str, Any] = {}
            parent[key] = new_map
            stack.append((indent + 2, new_map))
        else:
            scalar = _unquote_and_unescape_scalar(value)
            parent[key] = scalar
    return root


def _month_str_to_num(mon: str) -> Optional[int]:
    months = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    return months.get(mon.strip().lower())


def _iso_date(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


def _round2(x: float) -> float:
    return float(f"{x:.2f}")


def _parse_money_numbers(text: str) -> List[float]:
    nums: List[float] = []
    for m in re.finditer(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)", text):
        val = m.group(1).replace(",", "")
        try:
            nums.append(float(val))
        except ValueError:
            continue
    return nums


def _extract_claims_from_draft(draft_path: Path, schedule_csv: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(draft_path)
    if text is None:
        return None
    rows = _parse_csv(schedule_csv, delimiter=",")
    if rows is None or len(rows) == 0:
        return None
    years = []
    for r in rows:
        d = r.get("date", "")
        if isinstance(d, str) and len(d) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            y = int(d[:4])
            years.append(y)
    if not years:
        return None
    year = max(set(years), key=years.count)

    num_plays_claimed: Optional[int] = None
    m_num = re.search(r"\bWe\s+staged\s+(\d+)\s+plays", text, flags=re.IGNORECASE)
    if m_num:
        try:
            num_plays_claimed = int(m_num.group(1))
        except Exception:
            num_plays_claimed = None
    if num_plays_claimed is None:
        words_map = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
        }
        m_word = re.search(r"\bWe\s+staged\s+([A-Za-z]+)\s+plays", text, flags=re.IGNORECASE)
        if m_word:
            num_plays_claimed = words_map.get(m_word.group(1).lower())

    title_date_pairs: List[Tuple[str, str]] = []
    for m in re.finditer(r"([A-Z0-9][^,\n\.]+?)\s+on\s+([A-Za-z]{3,9})\s+(\d{1,2})", text):
        title = m.group(1).strip()
        mon = m.group(2)
        day = int(m.group(3))
        mon_num = _month_str_to_num(mon)
        if mon_num:
            title_date_pairs.append((title, _iso_date(year, mon_num, day)))

    avg_att_claimed: Optional[float] = None
    m_att = re.search(r"Average\s+attendance\s+was\s+([0-9]+(?:\.[0-9]+)?)\s+per\s+show", text, flags=re.IGNORECASE)
    if m_att:
        try:
            avg_att_claimed = float(m_att.group(1))
        except Exception:
            avg_att_claimed = None

    money_nums = _parse_money_numbers(text)
    concessions_claimed: Optional[float] = money_nums[0] if len(money_nums) >= 1 else None
    props_claimed: Optional[float] = money_nums[1] if len(money_nums) >= 2 else None

    claims = {
        "num_plays": num_plays_claimed,
        "dates_ordered_titles": [t for t, _ in title_date_pairs],
        "dates_claimed_values": [d for _, d in title_date_pairs],
        "avg_attendance": avg_att_claimed,
        "concessions_total": concessions_claimed,
        "props_total": props_claimed,
    }
    return claims


def _compute_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    plays_path = workspace / "input" / "plays_schedule.csv"
    concessions_path = workspace / "input" / "concessions.tsv"
    expenses_path = workspace / "input" / "expenses.json"

    rows = _parse_csv(plays_path, delimiter=",")
    if rows is None:
        return None
    if not rows or any(k not in rows[0] for k in ("date", "title", "attendance")):
        return None
    plays_count = len(rows)
    att_vals: List[float] = []
    for r in rows:
        try:
            att_vals.append(float(r.get("attendance", "0")))
        except Exception:
            return None
    avg_att = sum(att_vals) / len(att_vals) if att_vals else 0.0
    avg_att_2 = _round2(avg_att)

    cons_rows = _parse_csv(concessions_path, delimiter="\t")
    if cons_rows is None or not cons_rows or any(k not in cons_rows[0] for k in ("date", "amount")):
        return None
    cons_total = 0.0
    for r in cons_rows:
        try:
            cons_total += float(r.get("amount", "0"))
        except Exception:
            return None
    cons_total_2 = _round2(cons_total)

    expenses = _load_json(expenses_path)
    if not isinstance(expenses, dict):
        return None
    props = expenses.get("props")
    if not isinstance(props, list):
        return None
    props_total = 0.0
    for item in props:
        if not isinstance(item, dict):
            return None
        amt = item.get("amount")
        try:
            props_total += float(amt)
        except Exception:
            return None
    props_total_2 = _round2(props_total)

    title_to_date: Dict[str, str] = {}
    for r in rows:
        title_to_date[r["title"]] = r["date"]

    return {
        "plays_count": plays_count,
        "avg_attendance": avg_att_2,
        "concessions_total": cons_total_2,
        "props_total": props_total_2,
        "title_to_date": title_to_date,
    }


def _is_tab_delimiter(value: str) -> bool:
    if value is None:
        return False
    return value == "\t" or value == "\\t"


def _token_numbers(text: str) -> List[int]:
    nums: List[int] = []
    for tok in re.findall(r"\b\d{1,3}(?:,\d{3})*|\b\d+\b", text):
        try:
            nums.append(int(tok.replace(",", "")))
        except Exception:
            continue
    return nums


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_date_field_correct": 0.0,
        "config_attendance_field_correct": 0.0,
        "config_concessions_delimiter_correct": 0.0,
        "report_exists_and_readable": 0.0,
        "report_structure_valid": 0.0,
        "report_claims_values_correct_from_draft": 0.0,
        "report_computed_values_correct_from_inputs": 0.0,
        "report_status_logic_correct": 0.0,
        "report_summary_correct": 0.0,
        "email_rewrite_exists": 0.0,
        "email_includes_correct_titles_and_dates": 0.0,
        "email_includes_rounded_numbers": 0.0,
        "email_word_limit": 0.0,
        "email_thank_you_present": 0.0,
    }

    cfg_path = workspace / "config" / "verification.yaml"
    cfg = _parse_simple_yaml(cfg_path) if cfg_path.exists() else None
    plays_csv_path = workspace / "input" / "plays_schedule.csv"
    concessions_tsv_path = workspace / "input" / "concessions.tsv"
    expenses_json_path = workspace / "input" / "expenses.json"
    email_md_path = workspace / "input" / "draft_email.md"

    if cfg is not None and isinstance(cfg, dict):
        plays_cfg = cfg.get("plays") if isinstance(cfg.get("plays"), dict) else None
        concessions_cfg = cfg.get("concessions") if isinstance(cfg.get("concessions"), dict) else None

        if plays_csv_path.exists():
            rows = _parse_csv(plays_csv_path, delimiter=",")
            if rows is not None and rows:
                header = set(rows[0].keys())
                if plays_cfg and plays_cfg.get("date_field") == "date" and "date" in header:
                    scores["config_date_field_correct"] = 1.0
                if plays_cfg and plays_cfg.get("attendance_field") == "attendance" and "attendance" in header:
                    scores["config_attendance_field_correct"] = 1.0

        if concessions_cfg:
            delim_val = concessions_cfg.get("delimiter")
            if isinstance(delim_val, str) and _is_tab_delimiter(delim_val):
                scores["config_concessions_delimiter_correct"] = 1.0

    report_path = workspace / "output" / "verification_report.json"
    report = _load_json(report_path) if report_path.exists() else None
    if report is not None:
        scores["report_exists_and_readable"] = 1.0

    computed = _compute_from_inputs(workspace)
    claims_from_draft = _extract_claims_from_draft(email_md_path, plays_csv_path) if email_md_path.exists() else None

    if isinstance(report, dict) and "claims" in report and "computed_summary" in report:
        claims_list = report.get("claims")
        comp_sum = report.get("computed_summary")
        structure_ok = isinstance(claims_list, list) and isinstance(comp_sum, dict)
        required_ids = {"num_plays", "dates", "avg_attendance", "concessions_total", "props_total"}
        seen_ids = set()
        claim_entries_ok = True
        if structure_ok:
            for entry in claims_list:
                if not isinstance(entry, dict):
                    claim_entries_ok = False
                    break
                required_keys = {"id", "claim", "claimed_value", "computed_value", "status", "source"}
                if set(entry.keys()) < required_keys:
                    claim_entries_ok = False
                    break
                if not isinstance(entry["id"], str):
                    claim_entries_ok = False
                    break
                if not isinstance(entry["claim"], str):
                    claim_entries_ok = False
                    break
                if not isinstance(entry["status"], str) or entry["status"] not in {"match", "mismatch", "approximate"}:
                    claim_entries_ok = False
                    break
                if not isinstance(entry["source"], str) or not entry["source"]:
                    claim_entries_ok = False
                    break
                seen_ids.add(entry["id"])
                if entry["id"] == "dates":
                    if not (isinstance(entry["claimed_value"], list) and isinstance(entry["computed_value"], list)):
                        claim_entries_ok = False
                        break
                    for s in entry["claimed_value"] + entry["computed_value"]:
                        if not (isinstance(s, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", s)):
                            claim_entries_ok = False
                            break
                else:
                    if not (isinstance(entry["claimed_value"], (int, float)) and isinstance(entry["computed_value"], (int, float))):
                        claim_entries_ok = False
                        break
            if seen_ids != required_ids:
                claim_entries_ok = False
        scores["report_structure_valid"] = 1.0 if (structure_ok and claim_entries_ok) else 0.0

    if report is not None and claims_from_draft is not None:
        claims_map = {c["id"]: c for c in report.get("claims", []) if isinstance(c, dict) and "id" in c}
        ok = True
        c = claims_map.get("num_plays")
        if not c or claims_from_draft.get("num_plays") is None:
            ok = False
        else:
            try:
                ok = ok and (float(c["claimed_value"]) == float(claims_from_draft["num_plays"]))
            except Exception:
                ok = False
        c = claims_map.get("dates")
        if not c:
            ok = False
        else:
            expected_dates_claimed = claims_from_draft.get("dates_claimed_values") or []
            if not isinstance(c.get("claimed_value"), list):
                ok = False
            else:
                ok = ok and (c["claimed_value"] == expected_dates_claimed)
        c = claims_map.get("avg_attendance")
        if not c or claims_from_draft.get("avg_attendance") is None:
            ok = False
        else:
            try:
                ok = ok and (float(c["claimed_value"]) == float(claims_from_draft["avg_attendance"]))
            except Exception:
                ok = False
        c = claims_map.get("concessions_total")
        if not c or claims_from_draft.get("concessions_total") is None:
            ok = False
        else:
            try:
                ok = ok and (float(c["claimed_value"]) == float(claims_from_draft["concessions_total"]))
            except Exception:
                ok = False
        c = claims_map.get("props_total")
        if not c or claims_from_draft.get("props_total") is None:
            ok = False
        else:
            try:
                ok = ok and (float(c["claimed_value"]) == float(claims_from_draft["props_total"]))
            except Exception:
                ok = False
        scores["report_claims_values_correct_from_draft"] = 1.0 if ok else 0.0

    if report is not None and computed is not None and claims_from_draft is not None:
        claims_map = {c["id"]: c for c in report.get("claims", []) if isinstance(c, dict) and "id" in c}
        ok = True
        c = claims_map.get("num_plays")
        if not c or float(c.get("computed_value", -1)) != float(computed["plays_count"]):
            ok = False
        c = claims_map.get("avg_attendance")
        if not c or _round2(float(c.get("computed_value", -1))) != _round2(float(computed["avg_attendance"])):
            ok = False
        c = claims_map.get("concessions_total")
        if not c or _round2(float(c.get("computed_value", -1))) != _round2(float(computed["concessions_total"])):
            ok = False
        c = claims_map.get("props_total")
        if not c or _round2(float(c.get("computed_value", -1))) != _round2(float(computed["props_total"])):
            ok = False
        c = claims_map.get("dates")
        titles_order = claims_from_draft.get("dates_ordered_titles") or []
        expected_dates = []
        title_to_date = computed.get("title_to_date", {})
        try:
            for t in titles_order:
                expected_dates.append(title_to_date[t])
        except Exception:
            ok = False
        if not c or c.get("computed_value") != expected_dates:
            ok = False
        scores["report_computed_values_correct_from_inputs"] = 1.0 if ok else 0.0

    if report is not None and computed is not None and claims_from_draft is not None:
        claims_map = {c["id"]: c for c in report.get("claims", []) if isinstance(c, dict) and "id" in c}
        ok = True
        c = claims_map.get("num_plays")
        if not c:
            ok = False
        else:
            try:
                claimed = float(c["claimed_value"])
                comp = float(c["computed_value"])
                exp_status = "match" if claimed == comp else "mismatch"
                if c["status"] != exp_status:
                    ok = False
            except Exception:
                ok = False
        c = claims_map.get("dates")
        if not c:
            ok = False
        else:
            exp_status = "match" if c["claimed_value"] == c["computed_value"] else "mismatch"
            if c["status"] != exp_status:
                ok = False
        c = claims_map.get("avg_attendance")
        if not c:
            ok = False
        else:
            try:
                claimed = float(c["claimed_value"])
                comp = float(c["computed_value"])
                if claimed == comp:
                    exp_status = "match"
                elif int(round(comp)) == int(claimed):
                    exp_status = "approximate"
                else:
                    exp_status = "mismatch"
                if c["status"] != exp_status:
                    ok = False
            except Exception:
                ok = False
        c = claims_map.get("concessions_total")
        if not c:
            ok = False
        else:
            try:
                claimed = float(c["claimed_value"])
                comp = float(c["computed_value"])
                if claimed == comp:
                    exp_status = "match"
                elif int(round(comp)) == int(claimed):
                    exp_status = "approximate"
                else:
                    exp_status = "mismatch"
                if c["status"] != exp_status:
                    ok = False
            except Exception:
                ok = False
        c = claims_map.get("props_total")
        if not c:
            ok = False
        else:
            try:
                claimed = float(c["claimed_value"])
                comp = float(c["computed_value"])
                if claimed == comp:
                    exp_status = "match"
                elif int(round(comp)) == int(claimed):
                    exp_status = "approximate"
                else:
                    exp_status = "mismatch"
                if c["status"] != exp_status:
                    ok = False
            except Exception:
                ok = False
        scores["report_status_logic_correct"] = 1.0 if ok else 0.0

    if report is not None and computed is not None and isinstance(report.get("computed_summary"), dict):
        s = report["computed_summary"]
        ok = True
        try:
            ok = ok and float(s.get("plays_count", -1)) == float(computed["plays_count"])
            ok = ok and _round2(float(s.get("avg_attendance", -1))) == _round2(float(computed["avg_attendance"]))
            ok = ok and _round2(float(s.get("concessions_total", -1))) == _round2(float(computed["concessions_total"]))
            ok = ok and _round2(float(s.get("props_total", -1))) == _round2(float(computed["props_total"]))
        except Exception:
            ok = False
        scores["report_summary_correct"] = 1.0 if ok else 0.0

    email_rewrite_path = workspace / "output" / "email_rewrite.md"
    email_text = _read_text(email_rewrite_path) if email_rewrite_path.exists() else None
    if email_text is not None:
        scores["email_rewrite_exists"] = 1.0

    if email_text is not None and computed is not None:
        titles_dates_ok = True
        title_to_date = computed.get("title_to_date", {})
        expected_pairs = list(title_to_date.items())
        if not expected_pairs:
            titles_dates_ok = False
        else:
            def date_variants(iso: str) -> List[str]:
                y, m, d = iso.split("-")
                month_num = int(m)
                day_num = int(d)
                months_short = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                months_long = ["January", "February", "March", "April", "May", "June",
                               "July", "August", "September", "October", "November", "December"]
                return [
                    iso,
                    f"{months_short[month_num-1]} {day_num}",
                    f"{months_long[month_num-1]} {day_num}",
                ]

            lower_email = email_text.lower()
            for title, iso_date_str in expected_pairs:
                if title not in email_text:
                    titles_dates_ok = False
                    break
                variants = date_variants(iso_date_str)
                if not any(v.lower() in lower_email for v in variants):
                    titles_dates_ok = False
                    break
        scores["email_includes_correct_titles_and_dates"] = 1.0 if titles_dates_ok else 0.0

        rounded_ok = True
        avg_att_rounded = int(round(float(computed["avg_attendance"])))
        concessions_rounded = int(round(float(computed["concessions_total"])))
        props_rounded = int(round(float(computed["props_total"])))
        nums_present = _token_numbers(email_text)
        if avg_att_rounded not in nums_present:
            rounded_ok = False
        if concessions_rounded not in nums_present:
            rounded_ok = False
        if props_rounded not in nums_present:
            rounded_ok = False
        scores["email_includes_rounded_numbers"] = 1.0 if rounded_ok else 0.0

        words = re.findall(r"\b\w+\b", email_text)
        scores["email_word_limit"] = 1.0 if len(words) <= 120 else 0.0

        scores["email_thank_you_present"] = 1.0 if re.search(r"thank", email_text, flags=re.IGNORECASE) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()