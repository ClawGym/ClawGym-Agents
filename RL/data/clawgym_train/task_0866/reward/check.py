import csv
import json
import re
import sys
import subprocess
from pathlib import Path
from html.parser import HTMLParser


class NexusTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cells = []
        self.rows = []
        self.current_table_id = None
        self.target_table_id = "nexus-thresholds"

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self.current_table_id = attrs_dict.get("id")
            if self.current_table_id == self.target_table_id:
                self.in_table = True
        elif tag == "tbody" and self.in_table:
            self.in_tbody = True
        elif tag == "tr" and self.in_tbody and self.in_table:
            self.in_tr = True
            self.current_cells = []
        elif tag == "td" and self.in_tr:
            self.in_td = True

    def handle_endtag(self, tag):
        if tag == "table" and self.in_table:
            self.in_table = False
            self.current_table_id = None
        elif tag == "tbody" and self.in_table:
            self.in_tbody = False
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if self.current_cells:
                self.rows.append(self.current_cells)
                self.current_cells = []
        elif tag == "td" and self.in_td:
            self.in_td = False

    def handle_data(self, data):
        if self.in_td and self.in_tr and self.in_tbody and self.in_table:
            text = data.strip()
            if text != "":
                self.current_cells.append(text)


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def safe_load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader), reader.fieldnames
    except Exception:
        return None, None


def parse_state_rules(html_text: str):
    parser = NexusTableParser()
    parser.feed(html_text)
    rules = {}
    for row in parser.rows:
        if len(row) >= 3:
            state = row[0].strip()
            try:
                threshold_revenue = float(row[1].strip())
            except ValueError:
                continue
            try:
                threshold_tx = int(row[2].strip())
            except ValueError:
                continue
            rules[state] = {
                "threshold_revenue": threshold_revenue,
                "threshold_transactions": threshold_tx,
            }
    return rules


def compute_expected_aggregates(sales_rows, rules):
    aggregates = {}
    for state, vals in rules.items():
        aggregates[state] = {
            "state": state,
            "revenue": 0.0,
            "taxable_revenue": 0.0,
            "orders": 0,
            "threshold_revenue": float(vals["threshold_revenue"]),
            "threshold_transactions": int(vals["threshold_transactions"]),
            "nexus_met": "no",
            "triggering_metric": "none",
        }
    for r in sales_rows:
        state = (r.get("state") or "").strip()
        if state not in aggregates:
            continue
        try:
            rev = float((r.get("order_total") or "0").strip() or 0)
        except ValueError:
            rev = 0.0
        try:
            tax = float((r.get("taxable_amount") or "0").strip() or 0)
        except ValueError:
            tax = 0.0
        aggregates[state]["revenue"] += rev
        aggregates[state]["taxable_revenue"] += tax
        aggregates[state]["orders"] += 1
    for s, vals in aggregates.items():
        met_rev = vals["revenue"] >= vals["threshold_revenue"]
        met_tx = vals["orders"] >= vals["threshold_transactions"]
        if met_rev and met_tx:
            vals["nexus_met"] = "yes"
            vals["triggering_metric"] = "both"
        elif met_rev:
            vals["nexus_met"] = "yes"
            vals["triggering_metric"] = "revenue"
        elif met_tx:
            vals["nexus_met"] = "yes"
            vals["triggering_metric"] = "transactions"
        else:
            vals["nexus_met"] = "no"
            vals["triggering_metric"] = "none"
    return aggregates


def float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def number_regex_pattern(n: float) -> re.Pattern:
    n_rounded = round(n, 2)
    if float_equal(n_rounded, round(n_rounded)):
        iv = int(round(n_rounded))
        s_plain = str(iv)
        s_commas = f"{iv:,}"
        inner = f"(?:{re.escape(s_plain)}|{re.escape(s_commas)})"
    else:
        s_plain = f"{n_rounded:.2f}".rstrip("0").rstrip(".")
        int_part, _, frac_part = s_plain.partition(".")
        try:
            int_val = int(int_part)
            int_commas = f"{int_val:,}"
            s_commas = int_commas + (("." + frac_part) if frac_part else "")
            inner = f"(?:{re.escape(s_plain)}|{re.escape(s_commas)})"
        except Exception:
            inner = re.escape(s_plain)
    pattern = rf"(?<!\d)\$?\s*{inner}(?:\.0+)?(?!\d)"
    return re.compile(pattern)


def parse_cli_counts_from_text(text: str):
    if text is None:
        return None
    errors = len(re.findall(r"(?m)^ERROR:", text))
    warnings = len(re.findall(r"(?m)^WARNING:", text))
    info = len(re.findall(r"(?m)^INFO:", text))
    m = re.search(r"SUMMARY:\s*processed\s+(\d+)\s+rows;\s+errors\s+(\d+);\s+warnings\s+(\d+);\s+info\s+(\d+)", text)
    processed = None
    if m:
        processed = int(m.group(1))
        try:
            errors = int(m.group(2))
            warnings = int(m.group(3))
            info = int(m.group(4))
        except Exception:
            pass
    return {"processed": processed, "errors": errors, "warnings": warnings, "info": info}


def run_cli_to_get_expected(workspace: Path):
    cli_path = workspace / "tools" / "nexus_cli.py"
    sales_path = workspace / "input" / "sales_2024_q1.csv"
    if not cli_path.exists() or not sales_path.exists():
        return None
    try:
        proc = subprocess.Popen(
            [sys.executable, str(cli_path), str(sales_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(workspace),
            text=True,
        )
        out, err = proc.communicate(timeout=10)
        combined = out + err
        return {
            "stdout": out,
            "stderr": err,
            "combined": combined,
            "returncode": proc.returncode,
        }
    except Exception:
        return None


def replicate_cli_expected_counts(sales_rows):
    allowed_states = {"CA", "NY", "TX", "WA"}
    errors = 0
    warnings = 0
    info = 0
    processed = 0
    for row in sales_rows:
        processed += 1
        state = (row.get("state") or "").strip()
        zip_code = (row.get("customer_zip") or "").strip()
        taxable_raw = (row.get("taxable_amount") or "0").strip()
        try:
            taxable = float(taxable_raw)
        except ValueError:
            taxable = 0.0
        if state not in allowed_states:
            errors += 1
            continue
        if zip_code == "":
            warnings += 1
        if taxable == 0:
            info += 1
    return {"processed": processed, "errors": errors, "warnings": warnings, "info": info}


def extract_section(text: str, anchor: str, anchors_all=None) -> str:
    if text is None:
        return ""
    lower = text.lower()
    start = lower.find(anchor.lower())
    if start == -1:
        return ""
    if anchors_all is None:
        anchors_all = []
    next_positions = []
    for a in anchors_all:
        if a.lower() == anchor.lower():
            continue
        pos = lower.find(a.lower(), start + 1)
        if pos != -1:
            next_positions.append(pos)
    end = min(next_positions) if next_positions else len(text)
    return text[start:end]


def contains_number(text: str, value: float) -> bool:
    if text is None:
        return False
    pat = number_regex_pattern(value)
    return bool(pat.search(text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "nexus_by_state_file_exists": 0.0,
        "nexus_by_state_headers_correct": 0.0,
        "nexus_by_state_states_coverage": 0.0,
        "nexus_by_state_aggregates_correct": 0.0,
        "nexus_by_state_thresholds_correct": 0.0,
        "nexus_by_state_nexus_logic_correct": 0.0,
        "cli_output_file_captured": 0.0,
        "cli_output_contains_expected_messages": 0.0,
        "data_quality_summary_json_valid": 0.0,
        "data_quality_counts_match_cli": 0.0,
        "social_post_headline_present": 0.0,
        "social_post_quick_stats_correct": 0.0,
        "social_post_top3_states_correct": 0.0,
        "social_post_where_collect_correct": 0.0,
        "social_post_data_quality_notes_correct": 0.0,
        "social_post_cta_present": 0.0,
    }

    sales_csv_path = workspace / "input" / "sales_2024_q1.csv"
    rules_html_path = workspace / "input" / "state_nexus_rules.html"
    sales_rows, _ = safe_load_csv_dicts(sales_csv_path)
    rules_html = safe_read_text(rules_html_path)
    if sales_rows is None or rules_html is None:
        return scores

    rules = parse_state_rules(rules_html)
    if not rules:
        return scores

    expected_aggs_map = compute_expected_aggregates(sales_rows, rules)

    nexus_csv_path = workspace / "output" / "nexus_by_state.csv"
    nexus_rows, nexus_headers = safe_load_csv_dicts(nexus_csv_path)
    if nexus_rows is not None and nexus_headers is not None:
        scores["nexus_by_state_file_exists"] = 1.0
        expected_headers = [
            "state",
            "revenue",
            "taxable_revenue",
            "orders",
            "threshold_revenue",
            "threshold_transactions",
            "nexus_met",
            "triggering_metric",
        ]
        if nexus_headers == expected_headers:
            scores["nexus_by_state_headers_correct"] = 1.0

        states_in_csv = [r.get("state", "").strip() for r in nexus_rows]
        if set(states_in_csv) == set(rules.keys()):
            scores["nexus_by_state_states_coverage"] = 1.0

        student_map = {}
        valid_parse = True
        for r in nexus_rows:
            st = (r.get("state") or "").strip()
            try:
                rev = float((r.get("revenue") or "0").strip() or 0)
                trev = float((r.get("taxable_revenue") or "0").strip() or 0)
                orders = int(float((r.get("orders") or "0").strip() or 0))
                thr_rev = float((r.get("threshold_revenue") or "0").strip() or 0)
                thr_tx = int(float((r.get("threshold_transactions") or "0").strip() or 0))
                nexus_met = (r.get("nexus_met") or "").strip().lower()
                trig = (r.get("triggering_metric") or "").strip().lower()
            except Exception:
                valid_parse = False
                break
            student_map[st] = {
                "revenue": rev,
                "taxable_revenue": trev,
                "orders": orders,
                "threshold_revenue": thr_rev,
                "threshold_transactions": thr_tx,
                "nexus_met": nexus_met,
                "triggering_metric": trig,
            }
        if valid_parse and set(student_map.keys()) == set(rules.keys()):
            aggs_ok = True
            thresholds_ok = True
            nexus_ok = True
            for st, exp in expected_aggs_map.items():
                stu = student_map.get(st)
                if stu is None:
                    aggs_ok = False
                    thresholds_ok = False
                    nexus_ok = False
                    break
                if not (float_equal(stu["revenue"], exp["revenue"]) and float_equal(stu["taxable_revenue"], exp["taxable_revenue"]) and stu["orders"] == exp["orders"]):
                    aggs_ok = False
                if not (float_equal(stu["threshold_revenue"], exp["threshold_revenue"]) and stu["threshold_transactions"] == exp["threshold_transactions"]):
                    thresholds_ok = False
                if not (stu["nexus_met"] == exp["nexus_met"] and stu["triggering_metric"] == exp["triggering_metric"]):
                    nexus_ok = False
            if aggs_ok:
                scores["nexus_by_state_aggregates_correct"] = 1.0
            if thresholds_ok:
                scores["nexus_by_state_thresholds_correct"] = 1.0
            if nexus_ok:
                scores["nexus_by_state_nexus_logic_correct"] = 1.0

    cli_output_path = workspace / "output" / "cli_output.txt"
    cli_text = safe_read_text(cli_output_path)
    if cli_text is not None:
        scores["cli_output_file_captured"] = 1.0
        run_res = run_cli_to_get_expected(workspace)
        if run_res is not None:
            exp_counts = parse_cli_counts_from_text(run_res["combined"])
        else:
            exp_counts = replicate_cli_expected_counts(sales_rows)
        expected_substrings = [
            "SUMMARY:",
            "ERROR: Unknown state code 'ZZ' on order_id 13",
            "WARNING: Missing ZIP on order_id 2 (state CA)",
            "INFO: Non-taxable order order_id 5 (state CA)",
        ]
        contains_all = all(sub in cli_text for sub in expected_substrings)
        if contains_all:
            scores["cli_output_contains_expected_messages"] = 1.0

    dq_json_path = workspace / "output" / "data_quality_summary.json"
    dq_json = safe_load_json(dq_json_path)
    if dq_json is not None and isinstance(dq_json, dict):
        has_keys = all(k in dq_json for k in ("errors", "warnings", "info"))
        if has_keys and all(isinstance(dq_json[k], (int, float)) for k in ("errors", "warnings", "info")):
            scores["data_quality_summary_json_valid"] = 1.0
            cli_counts = parse_cli_counts_from_text(cli_text or "")
            if cli_counts is None:
                run_res = run_cli_to_get_expected(workspace)
                if run_res is not None:
                    cli_counts = parse_cli_counts_from_text(run_res["combined"])
                else:
                    cli_counts = replicate_cli_expected_counts(sales_rows)
            if cli_counts is not None:
                if (
                    int(dq_json.get("errors", -1)) == int(cli_counts.get("errors", -2))
                    and int(dq_json.get("warnings", -1)) == int(cli_counts.get("warnings", -2))
                    and int(dq_json.get("info", -1)) == int(cli_counts.get("info", -2))
                ):
                    scores["data_quality_counts_match_cli"] = 1.0

    post_path = workspace / "output" / "social_post.md"
    post_text = safe_read_text(post_path)
    if post_text is not None:
        headline_ok = False
        for line in post_text.splitlines():
            l = line.strip().lower()
            if l and ("minimiz" in l) and ("compliant" in l or "compliance" in l):
                headline_ok = True
                break
        if headline_ok:
            scores["social_post_headline_present"] = 1.0

        student_nexus_rows = nexus_rows or []
        taxable_by_state = {}
        orders_by_state = {}
        total_orders = 0
        total_taxable = 0.0
        for r in student_nexus_rows:
            st = (r.get("state") or "").strip()
            try:
                trev = float((r.get("taxable_revenue") or "0").strip() or 0)
            except Exception:
                trev = 0.0
            try:
                ords = int(float((r.get("orders") or "0").strip() or 0))
            except Exception:
                ords = 0
            taxable_by_state[st] = trev
            orders_by_state[st] = ords
            total_orders += ords
            total_taxable += trev

        top3_states = []
        try:
            top3_states = sorted(taxable_by_state.items(), key=lambda x: (-x[1], x[0]))[:3]
        except Exception:
            top3_states = []
        top3_codes = [s for s, _ in top3_states]

        anchors = [
            "Quick stats",
            "Where we collect",
            "Data quality notes",
        ]
        quick_section = extract_section(post_text, "Quick stats", anchors_all=anchors)
        where_section = extract_section(post_text, "Where we collect", anchors_all=anchors)
        dq_section = extract_section(post_text, "Data quality notes", anchors_all=anchors)

        quick_ok = False
        top3_ok = False
        if quick_section:
            has_orders = contains_number(quick_section, float(total_orders))
            has_taxable = contains_number(quick_section, total_taxable)
            if has_orders and has_taxable:
                quick_ok = True
            if top3_states:
                present = True
                for st, val in top3_states:
                    if st and (st in quick_section):
                        if contains_number(quick_section, val):
                            continue
                        else:
                            present = False
                            break
                    else:
                        present = False
                        break
                if present and len(top3_states) >= 3:
                    top3_ok = True
        if quick_ok:
            scores["social_post_quick_stats_correct"] = 1.0
        if top3_ok:
            scores["social_post_top3_states_correct"] = 1.0

        where_ok = False
        if where_section and nexus_rows is not None:
            yes_states = []
            no_states = []
            state_revenue_map = {}
            reason_map = {}
            for r in nexus_rows:
                st = (r.get("state") or "").strip()
                nm = (r.get("nexus_met") or "").strip().lower()
                trig = (r.get("triggering_metric") or "").strip().lower()
                try:
                    rev = float((r.get("revenue") or "0").strip() or 0)
                except Exception:
                    rev = 0.0
                if nm == "yes":
                    yes_states.append(st)
                else:
                    no_states.append(st)
                state_revenue_map[st] = rev
                reason_map[st] = trig
            present_yes = all(st in where_section for st in yes_states)
            absent_no = all(st not in where_section for st in no_states)
            reasons_ok = True
            numbers_ok = True
            for st in yes_states:
                trig = reason_map.get(st, "")
                if trig == "revenue":
                    if "revenue" not in where_section.lower():
                        reasons_ok = False
                    if not contains_number(where_section, state_revenue_map.get(st, 0.0)):
                        numbers_ok = False
                elif trig == "transactions":
                    if "transaction" not in where_section.lower():
                        reasons_ok = False
                    if not contains_number(where_section, orders_by_state.get(st, 0)):
                        numbers_ok = False
                elif trig == "both":
                    l = where_section.lower()
                    if ("revenue" not in l) or ("transaction" not in l):
                        reasons_ok = False
                    if not (contains_number(where_section, state_revenue_map.get(st, 0.0)) or contains_number(where_section, orders_by_state.get(st, 0))):
                        numbers_ok = False
                else:
                    reasons_ok = False
            if present_yes and absent_no and reasons_ok and numbers_ok and len(yes_states) > 0:
                where_ok = True
        if where_ok:
            scores["social_post_where_collect_correct"] = 1.0

        dq_ok = False
        if dq_section:
            counts = None
            if dq_json is not None and isinstance(dq_json, dict):
                counts = {
                    "errors": int(dq_json.get("errors", -1)) if isinstance(dq_json.get("errors"), (int, float)) else -1,
                    "warnings": int(dq_json.get("warnings", -1)) if isinstance(dq_json.get("warnings"), (int, float)) else -1,
                    "info": int(dq_json.get("info", -1)) if isinstance(dq_json.get("info"), (int, float)) else -1,
                }
            else:
                cli_counts = parse_cli_counts_from_text(cli_text or "")
                if cli_counts:
                    counts = {
                        "errors": int(cli_counts.get("errors", -1)),
                        "warnings": int(cli_counts.get("warnings", -1)),
                        "info": int(cli_counts.get("info", -1)),
                    }
            counts_present = False
            if counts:
                ctext = dq_section.lower()
                err_ok = ("error" in ctext) and contains_number(dq_section, counts["errors"])
                warn_ok = ("warning" in ctext) and contains_number(dq_section, counts["warnings"])
                info_ok = ("info" in ctext) and contains_number(dq_section, counts["info"])
                counts_present = (err_ok and warn_ok and info_ok)
            bullets = [ln.strip() for ln in dq_section.splitlines() if ln.strip().startswith(("-", "*"))]
            bullet_ok = len(bullets) >= 1
            if counts_present and bullet_ok:
                dq_ok = True
        if dq_ok:
            scores["social_post_data_quality_notes_correct"] = 1.0

        lwr = post_text.lower()
        cta_ok = False
        if ("reach out" in lwr or "contact" in lwr) and ("tax" in lwr or "questions" in lwr):
            cta_ok = True
        if cta_ok:
            scores["social_post_cta_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()