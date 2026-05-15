import sys
import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


class CookiesTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_cookies_table = False
        self.current_tag = None
        self.current_row = []
        self.rows = []
        self.capture_text = False
        self.buffer = []
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.in_th = False
        self.table_stack = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self.table_stack.append(attrs_dict.get("id", ""))
            if attrs_dict.get("id") == "cookies":
                self.in_cookies_table = True
        if self.in_cookies_table:
            if tag == "tbody":
                self.in_tbody = True
            if tag == "tr" and self.in_tbody:
                self.in_tr = True
                self.current_row = []
            if tag == "td" and self.in_tr:
                self.in_td = True
                self.buffer = []
            if tag == "th" and self.in_tr:
                self.in_th = True
                self.buffer = []

    def handle_endtag(self, tag):
        if tag == "table":
            if self.table_stack:
                last = self.table_stack.pop()
                if last == "cookies":
                    self.in_cookies_table = False
        if not self.in_cookies_table:
            return
        if tag == "tbody":
            self.in_tbody = False
        if tag == "tr":
            if self.in_tr and self.current_row:
                # Only consider rows with td cells (skip header rows with th only)
                self.rows.append([cell.strip() for cell in self.current_row])
            self.in_tr = False
        if tag == "td":
            if self.in_td:
                text = "".join(self.buffer).strip()
                self.current_row.append(text)
                self.in_td = False
                self.buffer = []
        if tag == "th":
            if self.in_th:
                # ignore header text
                self.in_th = False
                self.buffer = []

    def handle_data(self, data):
        if self.in_cookies_table and self.in_tr and (self.in_td or self.in_th):
            self.buffer.append(data)


def parse_cookies_from_policy(html_text: str):
    parser = CookiesTableParser()
    parser.feed(html_text)
    # Expect 5 columns per row
    expected_rows = []
    for r in parser.rows:
        if len(r) != 5:
            # malformed row; fail by returning None to indicate parse failure
            return None
        expected_rows.append({
            "cookie_name": r[0].strip(),
            "provider": r[1].strip(),
            "purpose": r[2].strip(),
            "expiry": r[3].strip(),
            "type": r[4].strip(),
        })
    return expected_rows


def read_csv_as_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_dicts = []
        for r in rows[1:]:
            # Make sure we have exactly expected number of columns
            data_dicts.append(r)
        return header, data_dicts
    except Exception:
        return None, None


def normalize_hyphens(text: str) -> str:
    hyphens = ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"]
    for h in hyphens:
        text = text.replace(h, "-")
    return text


def parse_sections(markdown_text: str) -> dict:
    lines = markdown_text.splitlines()
    sections = {"findings": "", "discrepancies": "", "recommendations": ""}
    order = ["findings", "discrepancies", "recommendations"]
    current = None
    for line in lines:
        # Normalize heading
        stripped = line.strip()
        stripped_no_hash = stripped.lstrip("#").strip()
        lower = stripped_no_hash.lower().rstrip(":")
        if lower in sections.keys():
            current = lower
            continue
        if current:
            sections[current] += (line + "\n")
    return sections


def infer_loads_before_consent(site_config: dict, tracking_js_text: str) -> dict:
    # Based on tracking.js logic: GA/FB load if enabled and (consented || consentMode == 'opt-out').
    # Hotjar loads only if enabled and consented.
    consent_mode = (((site_config or {}).get("consent") or {}).get("mode") or "").lower()
    tools = ((site_config or {}).get("tracking_tools") or {})
    def enabled(tool_name):
        t = tools.get(tool_name) or {}
        return bool(t.get("enabled", False))
    loads = {}
    # GA:
    loads["google_analytics"] = enabled("google_analytics") and (consent_mode == "opt-out")
    # FB:
    loads["facebook_pixel"] = enabled("facebook_pixel") and (consent_mode == "opt-out")
    # Hotjar:
    loads["hotjar"] = False  # requires consented true in code, so before consent it's False
    return loads


def extract_flagged_tools_from_findings(findings_text: str) -> set:
    # Look for the "Non-essential trackers load before consent:" line and scan that line and next few lines for tool mentions.
    text_norm = normalize_hyphens(findings_text)
    lines = text_norm.splitlines()
    idx = -1
    pattern = re.compile(r"non-?essential trackers load before consent:\s*(yes|no)", re.IGNORECASE)
    for i, line in enumerate(lines):
        if pattern.search(line):
            idx = i
            break
    scan_text = ""
    if idx != -1:
        window = lines[idx: idx + 6]
        scan_text = "\n".join(window).lower()
    else:
        scan_text = text_norm.lower()
    flagged = set()
    if ("google analytics" in scan_text) or ("ga4" in scan_text) or ("_ga" in scan_text):
        flagged.add("google_analytics")
    if ("facebook pixel" in scan_text) or ("meta pixel" in scan_text) or ("facebook" in scan_text) or ("_fbp" in scan_text):
        flagged.add("facebook_pixel")
    if ("hotjar" in scan_text) or ("_hjid" in scan_text):
        flagged.add("hotjar")
    return flagged


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cookies_csv_header_correct": 0.0,
        "cookies_csv_rows_match_policy": 0.0,
        "config_summary_core_fields": 0.0,
        "config_summary_loads_before_consent_correct": 0.0,
        "compliance_report_sections_present": 0.0,
        "compliance_report_findings_yes_no_correct": 0.0,
        "compliance_report_findings_tools_listed_correct": 0.0,
        "compliance_report_discrepancies_mismatch_mentioned": 0.0,
        "compliance_report_recommendations_concrete": 0.0,
        "email_references_and_tone": 0.0,
        "cross_consistency_report_vs_summary": 0.0,
    }

    # Load inputs
    policy_html_path = workspace / "input" / "privacy_policy.html"
    site_config_path = workspace / "input" / "site_config.json"
    tracking_js_path = workspace / "input" / "tracking.js"

    policy_html_text = safe_read_text(policy_html_path)
    expected_cookies = None
    if policy_html_text:
        expected_cookies = parse_cookies_from_policy(policy_html_text)

    site_config = safe_load_json(site_config_path) or {}
    tracking_js_text = safe_read_text(tracking_js_path)

    # Expected cookies list (from policy)
    # Also compute mapping from tools to expected cookie names (from policy)
    tool_cookie_map = {
        "google_analytics": "_ga",
        "facebook_pixel": "_fbp",
        "hotjar": "_hjid",
    }
    cookies_present = set()
    if expected_cookies is not None:
        for row in expected_cookies:
            cookies_present.add(row.get("cookie_name", "").strip())

    # Deliverable 1: out/cookies.csv
    cookies_csv_path = workspace / "out" / "cookies.csv"
    header, rows = read_csv_as_dicts(cookies_csv_path)
    required_header = ["cookie_name", "provider", "purpose", "expiry", "type"]
    if header is not None and header == required_header:
        scores["cookies_csv_header_correct"] = 1.0
    else:
        scores["cookies_csv_header_correct"] = 0.0

    if expected_cookies is not None and header is not None and header == required_header and rows is not None:
        # Build actual rows as list of dicts
        actual_rows = []
        for r in rows:
            if len(r) != len(required_header):
                actual_rows = None
                break
            actual_rows.append({
                "cookie_name": r[0].strip(),
                "provider": r[1].strip(),
                "purpose": r[2].strip(),
                "expiry": r[3].strip(),
                "type": r[4].strip(),
            })
        if actual_rows is not None:
            # Compare as sets of tuples to ignore order
            expected_set = set((d["cookie_name"], d["provider"], d["purpose"], d["expiry"], d["type"]) for d in expected_cookies)
            actual_set = set((d["cookie_name"], d["provider"], d["purpose"], d["expiry"], d["type"]) for d in actual_rows)
            if expected_set == actual_set and len(actual_rows) == len(expected_cookies):
                scores["cookies_csv_rows_match_policy"] = 1.0
            else:
                scores["cookies_csv_rows_match_policy"] = 0.0
        else:
            scores["cookies_csv_rows_match_policy"] = 0.0
    else:
        scores["cookies_csv_rows_match_policy"] = 0.0

    # Deliverable 2: out/config_summary.json
    config_summary_path = workspace / "out" / "config_summary.json"
    config_summary = safe_load_json(config_summary_path)
    expected_consent_mode = (((site_config or {}).get("consent") or {}).get("mode"))
    expected_block_before = (((site_config or {}).get("consent") or {}).get("block_non_essential_before_consent"))
    expected_loads = infer_loads_before_consent(site_config, tracking_js_text)

    # Check core fields existence and values
    core_ok = False
    if isinstance(config_summary, dict):
        has_core = ("consent_mode" in config_summary and "block_non_essential_before_consent" in config_summary)
        tools_ok = all(k in config_summary for k in ["google_analytics", "facebook_pixel", "hotjar"])
        if has_core and tools_ok:
            cm_ok = (config_summary.get("consent_mode") == expected_consent_mode)
            bn_ok = (config_summary.get("block_non_essential_before_consent") == expected_block_before)
            # Check subkeys for enabled and load_on_first_page presence
            sub_ok = True
            for tool_key in ["google_analytics", "facebook_pixel", "hotjar"]:
                sub = config_summary.get(tool_key)
                cfg = ((site_config.get("tracking_tools") or {}).get(tool_key) or {})
                if not isinstance(sub, dict):
                    sub_ok = False
                    break
                if "enabled" not in sub or "load_on_first_page" not in sub or "loads_before_consent" not in sub:
                    sub_ok = False
                    break
                if sub.get("enabled") != cfg.get("enabled"):
                    sub_ok = False
                    break
                if sub.get("load_on_first_page") != cfg.get("load_on_first_page"):
                    sub_ok = False
                    break
            if cm_ok and bn_ok and sub_ok:
                core_ok = True
    scores["config_summary_core_fields"] = 1.0 if core_ok else 0.0

    # Check loads_before_consent correctness
    lbc_ok = False
    if isinstance(config_summary, dict):
        try:
            lbc_ok = True
            for tool_key in ["google_analytics", "facebook_pixel", "hotjar"]:
                sub = config_summary.get(tool_key) or {}
                if sub.get("loads_before_consent") != expected_loads.get(tool_key, False):
                    lbc_ok = False
                    break
        except Exception:
            lbc_ok = False
    scores["config_summary_loads_before_consent_correct"] = 1.0 if lbc_ok else 0.0

    # Deliverable 3: out/compliance_report.md
    report_path = workspace / "out" / "compliance_report.md"
    report_text = safe_read_text(report_path)
    sections_present = False
    findings_yesno_ok = False
    findings_tools_ok = False
    discrepancies_ok = False
    recommendations_ok = False
    reported_preconsent_set = set()
    if report_text:
        sections = parse_sections(report_text)
        if all(sections.get(k, "").strip() != "" for k in ["findings", "discrepancies", "recommendations"]):
            sections_present = True

        # Findings: check line "Non-essential trackers load before consent: Yes/No"
        findings_text = sections.get("findings", "")
        findings_norm = normalize_hyphens(findings_text)
        m = re.search(r"non-?essential trackers load before consent:\s*(yes|no)", findings_norm, flags=re.IGNORECASE)
        expected_preconsent_set = set(k for k, v in expected_loads.items() if v)
        if m:
            reported_yesno = m.group(1).strip().lower()
            expected_yesno = "yes" if len(expected_preconsent_set) > 0 else "no"
            if reported_yesno == expected_yesno:
                findings_yesno_ok = True
        # Check listed tools that load before consent
        reported_preconsent_set = extract_flagged_tools_from_findings(findings_text)
        if reported_preconsent_set == expected_preconsent_set:
            findings_tools_ok = True

        # Discrepancies: check mismatches between policy and config
        # Compute expected mismatches
        expected_mismatches = []
        tools_cfg = (site_config.get("tracking_tools") or {})
        for tool_key, cookie_name in tool_cookie_map.items():
            enabled = bool((tools_cfg.get(tool_key) or {}).get("enabled", False))
            cookie_listed = cookie_name in cookies_present
            if enabled and not cookie_listed:
                expected_mismatches.append((tool_key, "enabled_without_cookie"))
            if (not enabled) and cookie_listed:
                expected_mismatches.append((tool_key, "cookie_disclosed_for_disabled"))
        discrepancies_text = sections.get("discrepancies", "").lower()
        # Ensure that expected mismatches are mentioned; specifically we expect Hotjar mismatch
        hotjar_mismatch_expected = any(tk == "hotjar" for tk, _ in expected_mismatches)
        if hotjar_mismatch_expected and ("hotjar" in discrepancies_text):
            discrepancies_ok = True
        elif not hotjar_mismatch_expected:
            # If no mismatches expected, allow discrepancies section to state none
            if "none" in discrepancies_text or "no discrepancies" in discrepancies_text:
                discrepancies_ok = True

        # Recommendations: look for concrete fixes
        rec_text = sections.get("recommendations", "").lower()
        rec_hits = 0
        if ("opt-in" in rec_text) or ("opt in" in rec_text):
            rec_hits += 1
        if ("block" in rec_text and "consent" in rec_text):
            rec_hits += 1
        if ("update policy" in rec_text) or ("policy" in rec_text and ("align" in rec_text or "match" in rec_text or "update" in rec_text)):
            rec_hits += 1
        if rec_hits >= 2:
            recommendations_ok = True

    scores["compliance_report_sections_present"] = 1.0 if sections_present else 0.0
    scores["compliance_report_findings_yes_no_correct"] = 1.0 if findings_yesno_ok else 0.0
    scores["compliance_report_findings_tools_listed_correct"] = 1.0 if findings_tools_ok else 0.0
    scores["compliance_report_discrepancies_mismatch_mentioned"] = 1.0 if discrepancies_ok else 0.0
    scores["compliance_report_recommendations_concrete"] = 1.0 if recommendations_ok else 0.0

    # Deliverable 4: out/email_to_manager.txt
    email_path = workspace / "out" / "email_to_manager.txt"
    email_text = safe_read_text(email_path)
    email_ok = False
    if email_text:
        et = email_text.lower()
        # Check references to files by name (allow base names)
        files_ok = all(any(name in et for name in [f"out/{fname}", fname]) for fname in ["cookies.csv", "config_summary.json", "compliance_report.md"])
        trust_ok = ("trust" in et) and ("transparency" in et)
        risk_ok = ("risk" in et or "risks" in et)
        next_steps_ok = ("next steps" in et) or ("next" in et and "steps" in et)
        email_ok = files_ok and trust_ok and risk_ok and next_steps_ok
    scores["email_references_and_tone"] = 1.0 if email_ok else 0.0

    # Cross consistency between report and config_summary
    cross_ok = False
    if isinstance(config_summary, dict) and report_text:
        # Extract loads_before_consent set from config_summary
        try:
            summary_set = set(k for k in ["google_analytics", "facebook_pixel", "hotjar"] if ((config_summary.get(k) or {}).get("loads_before_consent") is True))
            # reported_preconsent_set was extracted earlier
            if summary_set == reported_preconsent_set:
                cross_ok = True
        except Exception:
            cross_ok = False
    scores["cross_consistency_report_vs_summary"] = 1.0 if cross_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()