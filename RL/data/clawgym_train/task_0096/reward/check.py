import json
import csv
import re
import sys
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
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


def _parse_money_to_int(val: str) -> Optional[int]:
    if val is None:
        return None
    try:
        # Strip everything except digits and dot
        digits = re.sub(r"[^\d.]", "", val)
        if digits == "":
            return None
        # Handle decimal by rounding or floor
        amount = float(digits)
        return int(round(amount))
    except Exception:
        return None


class GymHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_article = False
        self.current_chain = None
        self.gyms = []
        self.current_plans = []
        self.current_cities = []
        self.collect_cities = False
        self.current_hours = None
        self.current_pool = None
        self.current_dropin = None
        self.in_hours_p = False
        self.in_pool_p = False
        self.in_dropin_p = False
        self.in_cities_ul = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "article" and attrs_dict.get("class") == "gym":
            self.in_article = True
            self.current_chain = attrs_dict.get("data-chain")
            self.current_plans = []
            self.current_cities = []
            self.current_hours = None
            self.current_pool = None
            self.current_dropin = None
        if self.in_article and tag == "div" and attrs_dict.get("class") == "plan":
            name = attrs_dict.get("data-name")
            monthly = attrs_dict.get("data-monthly")
            self.current_plans.append((name, monthly))
        if self.in_article and tag == "ul" and attrs_dict.get("class") == "cities":
            self.in_cities_ul = True
        if self.in_article and self.in_cities_ul and tag == "li":
            self.collect_cities = True
        if self.in_article and tag == "p":
            cls = attrs_dict.get("class")
            if cls == "hours":
                self.in_hours_p = True
            elif cls == "pool":
                self.in_pool_p = True
            elif cls == "dropin":
                self.in_dropin_p = True

    def handle_endtag(self, tag):
        if tag == "article" and self.in_article:
            self.gyms.append({
                "chain": self.current_chain,
                "plans": self.current_plans.copy(),
                "cities": self.current_cities.copy(),
                "hours": self.current_hours,
                "pool": self.current_pool,
                "dropin": self.current_dropin
            })
            self.in_article = False
            self.current_chain = None
            self.current_plans = []
            self.current_cities = []
            self.current_hours = None
            self.current_pool = None
            self.current_dropin = None
            self.in_hours_p = False
            self.in_pool_p = False
            self.in_dropin_p = False
            self.in_cities_ul = False
            self.collect_cities = False
        if tag == "ul" and self.in_cities_ul:
            self.in_cities_ul = False
            self.collect_cities = False
        if tag == "p":
            self.in_hours_p = False
            self.in_pool_p = False
            self.in_dropin_p = False

    def handle_data(self, data):
        if not self.in_article:
            return
        text = data.strip()
        if not text:
            return
        if self.collect_cities and self.in_cities_ul:
            self.current_cities.append(text)
        if self.in_hours_p:
            # Expect "Hours: 5am–11pm" or similar
            if text.lower().startswith("hours"):
                parts = text.split(":", 1)
                if len(parts) == 2:
                    self.current_hours = parts[1].strip()
                else:
                    # If already just the hours
                    self.current_hours = text.strip()
            else:
                self.current_hours = text.strip()
        if self.in_pool_p:
            # Expect "Pool: No" or "Pool: Yes (select locations)"
            if text.lower().startswith("pool"):
                parts = text.split(":", 1)
                if len(parts) == 2:
                    self.current_pool = parts[1].strip()
                else:
                    self.current_pool = text.strip()
            else:
                self.current_pool = text.strip()
        if self.in_dropin_p:
            if text.lower().startswith("drop-in"):
                parts = text.split(":", 1)
                if len(parts) == 2:
                    self.current_dropin = parts[1].strip()
                else:
                    self.current_dropin = text.strip()
            else:
                self.current_dropin = text.strip()


def _parse_expected_from_html(html_path: Path) -> Optional[Dict[Tuple[str, str], Dict[str, object]]]:
    text = _read_text(html_path)
    if text is None:
        return None
    parser = GymHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    expected: Dict[Tuple[str, str], Dict[str, object]] = {}
    for gym in parser.gyms:
        chain = gym["chain"]
        hours = gym["hours"]
        pool = gym["pool"]
        dropin = _parse_money_to_int(gym["dropin"])
        cities = gym["cities"]
        for plan_name, monthly in gym["plans"]:
            monthly_price = _parse_money_to_int(monthly)
            key = (chain, plan_name)
            expected[key] = {
                "chain": chain,
                "plan": plan_name,
                "monthly_price": monthly_price,
                "dropin_price": dropin,
                "cities_covered": cities,
                "hours": hours,
                "pool": pool,
            }
    return expected


def _extract_structured_rows(structured_csv_path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    return _load_csv(structured_csv_path)


def _csv_cities_field_to_list(val: str) -> List[str]:
    if val is None:
        return []
    parts = [p.strip() for p in val.split(";") if p.strip()]
    return parts


def _validate_structured_csv(header: List[str], rows: List[Dict[str, str]], expected: Dict[Tuple[str, str], Dict[str, object]]) -> bool:
    # Check all expected rows exist with matching values
    seen = set()
    for row in rows:
        chain = (row.get("chain") or "").strip()
        plan = (row.get("plan") or "").strip()
        key = (chain, plan)
        if key not in expected:
            continue
        exp = expected[key]
        # monthly_price
        mp = _parse_money_to_int(row.get("monthly_price") or "")
        if mp != exp["monthly_price"]:
            return False
        # dropin_price
        dp = _parse_money_to_int(row.get("dropin_price") or "")
        if dp != exp["dropin_price"]:
            return False
        # cities_covered set equality ignoring order
        csv_cities = _csv_cities_field_to_list(row.get("cities_covered") or "")
        if set([c.strip() for c in csv_cities]) != set(exp["cities_covered"]):
            return False
        # hours: accept exact or with minor dash normalization
        hours_val = (row.get("hours") or "").strip()
        exp_hours = (exp["hours"] or "").strip()
        # Normalize en dash vs hyphen
        norm_hours_val = hours_val.replace("–", "-").replace("—", "-")
        norm_exp_hours = exp_hours.replace("–", "-").replace("—", "-")
        if norm_hours_val != norm_exp_hours:
            return False
        # pool exact
        pool_val = (row.get("pool") or "").strip()
        if pool_val != (exp["pool"] or "").strip():
            return False
        seen.add(key)
    # Ensure all expected keys are present
    return seen == set(expected.keys())


def _compute_availability_from_csv(csv_path: Path) -> Optional[Tuple[int, List[str], Dict[str, int]]]:
    header, rows = _load_csv(csv_path)
    if header is None or rows is None:
        return None
    if "work_hours" not in header:
        return None
    city_counts: Dict[str, int] = {}
    total_rows = 0
    for row in rows:
        total_rows += 1
        c = (row.get("city") or "").strip()
        if not c:
            continue
        city_counts[c] = city_counts.get(c, 0) + 1
    unique_cities = sorted(city_counts.keys())
    return total_rows, unique_cities, city_counts


def _contains_in_order(text: str, first: str, second: str) -> bool:
    i1 = text.find(first)
    i2 = text.find(second, i1 + 1 if i1 >= 0 else 0)
    return i1 >= 0 and i2 > i1


def _find_chosen_plan_in_text(text: str) -> Optional[Tuple[str, str]]:
    # Return the first matched plan mention
    patterns = [
        ("FlexFit", "Basic"),
        ("FlexFit", "Plus"),
        ("CityPower", "Core"),
        ("CityPower", "Elite"),
    ]
    lower_text = text.lower()
    for chain, plan in patterns:
        # Match case-insensitively
        if (chain + " " + plan).lower() in lower_text:
            return (chain, plan)
    return None


def _net_cost_for_plan(chain: str, plan: str, structured_rows: List[Dict[str, str]], corporate_subsidy: int) -> Optional[int]:
    for row in structured_rows:
        if (row.get("chain") or "").strip().lower() == chain.lower() and (row.get("plan") or "").strip().lower() == plan.lower():
            mp = _parse_money_to_int(row.get("monthly_price") or "")
            if mp is None:
                return None
            net = mp - corporate_subsidy
            return net
    return None


def _dropin_for_chain(chain: str, structured_rows: List[Dict[str, str]]) -> Optional[int]:
    for row in structured_rows:
        if (row.get("chain") or "").strip().lower() == chain.lower():
            return _parse_money_to_int(row.get("dropin_price") or "")
    return None


def _parse_preferences_yaml(yaml_path: Path) -> Optional[dict]:
    # Minimal YAML loader for simple key: value and nested mapping under 'preferences'
    content = _read_text(yaml_path)
    if content is None:
        return None
    data: Dict[str, object] = {}
    current_parent = None
    for line in content.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^\S.*:$", line.strip()):
            # section header
            key = line.strip()[:-1]
            data[key] = {}
            current_parent = key
            continue
        m = re.match(r"^(\s*)([A-Za-z0-9_]+):\s*(.*)$", line)
        if m:
            indent, key, value = m.groups()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value in ("true", "false"):
                value = True if value == "true" else False
            else:
                # Try int
                try:
                    value = int(value)
                except Exception:
                    pass
            if indent and current_parent:
                # nested
                if isinstance(data.get(current_parent), dict):
                    data[current_parent][key] = value
            else:
                data[key] = value
    return data


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "structured_csv_exists_and_header": 0.0,
        "structured_csv_rows_match_expected": 0.0,
        "travel_csv_corrected_header": 0.0,
        "validator_availability_json_valid": 0.0,
        "validator_log_contains_error_and_ok": 0.0,
        "wellness_memo_includes_plan_and_rationale": 0.0,
        "wellness_memo_coverage_analysis": 0.0,
        "wellness_memo_net_cost_and_dropin": 0.0,
        "email_contents_requirements": 0.0,
    }

    # Paths
    html_path = workspace / "input" / "gym_options.html"
    structured_csv_path = workspace / "output" / "structured" / "gym_options.csv"
    travel_csv_path = workspace / "input" / "work_travel.csv"
    availability_json_path = workspace / "output" / "availability.json"
    validator_log_path = workspace / "output" / "logs" / "validator_run.txt"
    wellness_memo_path = workspace / "output" / "wellness_plan_final.md"
    preferences_yaml_path = workspace / "input" / "preferences.yaml"
    email_path = workspace / "output" / "email_to_benefits.txt"

    # 1) Structured CSV: existence and header
    header, rows = _extract_structured_rows(structured_csv_path)
    expected_header = ["chain", "plan", "monthly_price", "dropin_price", "cities_covered", "hours", "pool"]
    if header is not None and rows is not None:
        if header == expected_header:
            scores["structured_csv_exists_and_header"] = 1.0
        else:
            scores["structured_csv_exists_and_header"] = 0.0
    else:
        scores["structured_csv_exists_and_header"] = 0.0

    # 1) Structured CSV: rows correctness compared to HTML
    expected_data = _parse_expected_from_html(html_path)
    if header is not None and rows is not None and expected_data is not None:
        if _validate_structured_csv(header, rows, expected_data):
            scores["structured_csv_rows_match_expected"] = 1.0
        else:
            scores["structured_csv_rows_match_expected"] = 0.0
    else:
        scores["structured_csv_rows_match_expected"] = 0.0

    # 2) Travel CSV corrected header
    t_header, t_rows = _load_csv(travel_csv_path)
    if t_header is not None:
        if ("work_hours" in t_header) and ("work_hrs" not in t_header):
            scores["travel_csv_corrected_header"] = 1.0
        else:
            scores["travel_csv_corrected_header"] = 0.0
    else:
        scores["travel_csv_corrected_header"] = 0.0

    # 2) Validator JSON valid (consistent with CSV)
    avail = _load_json(availability_json_path)
    recomputed = _compute_availability_from_csv(travel_csv_path)
    if avail is not None and isinstance(avail, dict) and recomputed is not None:
        rows_count, unique_cities_sorted, city_counts = recomputed
        valid = True
        if avail.get("rows") != rows_count:
            valid = False
        if avail.get("unique_cities") != unique_cities_sorted:
            valid = False
        if isinstance(avail.get("city_counts"), dict):
            # Convert keys to same type
            if avail.get("city_counts") != city_counts:
                valid = False
        else:
            valid = False
        scores["validator_availability_json_valid"] = 1.0 if valid else 0.0
    else:
        scores["validator_availability_json_valid"] = 0.0

    # 2) Validator log contains error then ok, and ok content matches expected numbers
    log_text = _read_text(validator_log_path) or ""
    if log_text:
        has_error = "ERROR:" in log_text and "Missing required column" in log_text
        has_ok = "OK: availability computed" in log_text
        order_ok = _contains_in_order(log_text, "ERROR:", "OK: availability computed")
        ok_numbers_match = True
        if recomputed is not None:
            rows_count, unique_cities_sorted, _ = recomputed
            expected_ok_snippet = f"OK: availability computed for {len(unique_cities_sorted)} unique cities and {rows_count} rows"
            ok_numbers_match = expected_ok_snippet in log_text
        if has_error and has_ok and order_ok and ok_numbers_match:
            scores["validator_log_contains_error_and_ok"] = 1.0
        else:
            scores["validator_log_contains_error_and_ok"] = 0.0
    else:
        scores["validator_log_contains_error_and_ok"] = 0.0

    # 3) Wellness memo contents
    memo_text = _read_text(wellness_memo_path) or ""
    prefs = _parse_preferences_yaml(preferences_yaml_path) or {}
    # Selected membership plan (chain + plan) and rationale: budget, 24/7, pool
    chosen = None
    if memo_text:
        chosen = _find_chosen_plan_in_text(memo_text)
    rationale_ok = False
    if memo_text:
        has_budget = "budget" in memo_text.lower()
        has_247 = "24/7" in memo_text
        has_pool = "pool" in memo_text.lower()
        rationale_ok = has_budget and has_247 and has_pool
    if memo_text and chosen and rationale_ok:
        scores["wellness_memo_includes_plan_and_rationale"] = 1.0
    else:
        scores["wellness_memo_includes_plan_and_rationale"] = 0.0

    # Coverage analysis: compare chain coverage vs unique cities, counts and list uncovered cities
    coverage_ok = False
    if memo_text and expected_data is not None and avail is not None and isinstance(avail, dict):
        project_cities = set(avail.get("unique_cities") or [])
        # Compute expected coverage sets from HTML
        # Cities per chain:
        chains_cities: Dict[str, set] = {}
        for (chain_name, _plan), info in expected_data.items():
            chains_cities[chain_name] = set(info["cities_covered"])
        if "FlexFit" in chains_cities and "CityPower" in chains_cities and project_cities:
            flex_covered = len(project_cities & chains_cities["FlexFit"])
            city_covered = len(project_cities & chains_cities["CityPower"])
            flex_uncovered = sorted(project_cities - chains_cities["FlexFit"])
            city_uncovered = sorted(project_cities - chains_cities["CityPower"])
            # Check memo mentions both chains and their uncovered cities names and coverage counts
            has_both_chains = ("FlexFit" in memo_text) and ("CityPower" in memo_text)
            # Require counts 3 and 4 appear
            counts_ok = ("3" in memo_text) and ("4" in memo_text)
            # Require uncovered city names presence
            uncovered_names_ok = all(name in memo_text for name in (flex_uncovered + city_uncovered))
            coverage_ok = has_both_chains and counts_ok and uncovered_names_ok
    scores["wellness_memo_coverage_analysis"] = 1.0 if coverage_ok else 0.0

    # Net monthly cost and drop-in price included for chosen plan
    net_ok = False
    if memo_text and chosen and header is not None and rows is not None:
        chain, plan = chosen
        subsidy = 0
        try:
            subsidy = int(prefs.get("corporate_subsidy", 0))
        except Exception:
            subsidy = 0
        net = _net_cost_for_plan(chain, plan, rows, subsidy)
        dropin = _dropin_for_chain(chain, rows)
        if net is not None and dropin is not None:
            # Look for net value as number or with dollar sign
            net_str_variants = [str(net), f"${net}"]
            found_net = any(ns in memo_text for ns in net_str_variants)
            dropin_str_variants = [str(dropin), f"${dropin}"]
            found_dropin = any(ds in memo_text for ds in dropin_str_variants)
            net_ok = found_net and found_dropin
    scores["wellness_memo_net_cost_and_dropin"] = 1.0 if net_ok else 0.0

    # 4) Email contents: summarize chosen plan, net monthly cost, reasoning, request confirmation subsidy and reimbursement, reference memo
    email_ok = False
    email_text = _read_text(email_path) or ""
    if email_text and chosen and header is not None and rows is not None:
        chain, plan = chosen
        subsidy = 0
        try:
            subsidy = int(prefs.get("corporate_subsidy", 0))
        except Exception:
            subsidy = 0
        net = _net_cost_for_plan(chain, plan, rows, subsidy)
        has_plan = ((chain + " " + plan).lower() in email_text.lower())
        has_net = False
        if net is not None:
            has_net = (str(net) in email_text) or (f"${net}" in email_text)
        has_reasoning = (("coverage" in email_text.lower() or "cities" in email_text.lower()) and ("hours" in email_text.lower() or "24/7" in email_text))
        has_request = ("subsidy" in email_text.lower() and "reimbursement" in email_text.lower())
        has_reference = ("wellness_plan_final.md" in email_text) or ("decision memo" in email_text.lower())
        email_ok = has_plan and has_net and has_reasoning and has_request and has_reference
    scores["email_contents_requirements"] = 1.0 if email_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()