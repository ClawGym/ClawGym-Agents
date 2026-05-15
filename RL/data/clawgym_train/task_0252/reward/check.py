import json
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from html.parser import HTMLParser
from typing import Optional, Tuple, List, Dict, Any
from collections import Counter


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            sniffer_sample = f.read(2048)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sniffer_sample)
            except Exception:
                dialect = csv.excel
            reader = csv.DictReader(f, dialect=dialect)
            headers = reader.fieldnames
            rows = []
            for row in reader:
                clean_row = {k: (v if v is not None else "") for k, v in row.items()}
                rows.append(clean_row)
            return headers, rows
    except Exception:
        return None, None


def _validate_email_basic(email: str) -> bool:
    if not isinstance(email, str):
        return False
    email = email.strip()
    pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    return bool(pattern.match(email))


class _PressHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_text_parts: List[str] = []
        self.description: Optional[str] = None
        self.canonical: Optional[str] = None
        self.date: Optional[str] = None
        self.in_article = False
        self.article_text_parts: List[str] = []
        self.mailto_emails_all: List[str] = []
        self.mailto_emails_article: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = {k.lower(): (v if v is not None else "") for k, v in attrs}
        if tag.lower() == "title":
            self.in_title = True
        elif tag.lower() == "meta":
            name = attrs_dict.get("name", "").lower()
            if name == "description" and "content" in attrs_dict:
                self.description = attrs_dict.get("content")
        elif tag.lower() == "link":
            rel = attrs_dict.get("rel", "").lower()
            if "canonical" in rel and "href" in attrs_dict:
                self.canonical = attrs_dict.get("href")
        elif tag.lower() == "time":
            if "datetime" in attrs_dict:
                self.date = attrs_dict.get("datetime")
        elif tag.lower() == "article":
            self.in_article = True
        elif tag.lower() == "a":
            href = attrs_dict.get("href", "")
            if href.lower().startswith("mailto:"):
                email = href.split(":", 1)[1]
                email = email.strip()
                if email:
                    self.mailto_emails_all.append(email)
                    if self.in_article:
                        self.mailto_emails_article.append(email)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False
        elif tag.lower() == "article":
            self.in_article = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_text_parts.append(data)
        if self.in_article:
            self.article_text_parts.append(data)

    def get_result(self) -> Dict[str, Any]:
        title = "".join(self.title_text_parts).strip() if self.title_text_parts else None
        article_text = " ".join(self.article_text_parts).strip()
        return {
            "title": title,
            "description": self.description,
            "canonical": self.canonical,
            "date": self.date,
            "article_text": article_text,
            "mailto_emails_article": self.mailto_emails_article[:],
            "mailto_emails_all": self.mailto_emails_all[:],
        }


def _parse_press_release(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        parser = _PressHTMLParser()
        parser.feed(text)
        return parser.get_result()
    except Exception:
        return None


def _domain_matches(canonical_url: str, expected_domain: str) -> bool:
    try:
        parsed = urlparse(canonical_url)
        host = parsed.netloc.lower()
        exp = expected_domain.lower()
        host = host.split("@")[-1]
        host = host.split(":")[0]
        if host.startswith("www."):
            stripped_host = host[4:]
        else:
            stripped_host = host
        if exp.startswith("www."):
            exp = exp[4:]
        if stripped_host == exp:
            return True
        if stripped_host.endswith("." + exp):
            return True
        if host == exp or host.endswith("." + exp):
            return True
        return False
    except Exception:
        return False


def _compute_focus_alignment(beats_str: str, focus_topics: List[str]) -> bool:
    if beats_str is None:
        return False
    beats = [b.strip().lower() for b in beats_str.split(";") if b.strip()]
    focus_set = {t.strip().lower() for t in focus_topics}
    for b in beats:
        if b in focus_set:
            return True
    return False


def _expected_clean_contacts(rows: List[Dict[str, str]], focus_topics: List[str]) -> List[Dict[str, str]]:
    required_cols = ["Outlet", "Name", "Email", "City", "State", "Beats"]
    clean_rows: List[Dict[str, str]] = []
    seen_emails = set()
    for row in rows:
        if any(col not in row for col in required_cols):
            continue
        email = (row.get("Email") or "").strip()
        beats = row.get("Beats") or ""
        if not _validate_email_basic(email):
            continue
        if not _compute_focus_alignment(beats, focus_topics):
            continue
        if email.lower() in seen_emails:
            continue
        seen_emails.add(email.lower())
        clean_rows.append({col: row.get(col, "") for col in required_cols})
    return clean_rows


def _expected_validation_statuses(
    contacts_headers: Optional[List[str]],
    contacts_rows: Optional[List[Dict[str, str]]],
    focus: Optional[Dict[str, Any]],
    press: Optional[Dict[str, Any]],
    key_messages: Optional[List[str]],
) -> Optional[Dict[str, str]]:
    if contacts_headers is None or contacts_rows is None or focus is None or press is None or key_messages is None:
        return None
    statuses: Dict[str, str] = {}

    required_headers = ["Outlet", "Name", "Email", "City", "State", "Beats"]
    has_required = all(h in (contacts_headers or []) for h in required_headers)
    statuses["contacts_required_columns"] = "pass" if has_required else "fail"

    invalid_count = 0
    for r in contacts_rows:
        email = (r.get("Email") or "").strip()
        if not _validate_email_basic(email):
            invalid_count += 1
    statuses["contacts_valid_emails"] = "pass" if invalid_count == 0 else "fail"

    emails = [((r.get("Email") or "").strip().lower()) for r in contacts_rows]
    freq = Counter([e for e in emails if e])
    _ = [e for e, c in freq.items() if c > 1]
    statuses["contacts_duplicates_detected"] = "pass"

    focus_topics = list(focus.get("focus_topics", [])) if isinstance(focus.get("focus_topics"), list) else []
    all_aligned = True
    for r in contacts_rows:
        beats = r.get("Beats") or ""
        aligned = _compute_focus_alignment(beats, focus_topics)
        if not aligned:
            all_aligned = False
            break
    statuses["contacts_focus_topics_alignment"] = "pass" if all_aligned else "fail"

    press_meta_ok = (
        isinstance(press.get("title"), str) and press.get("title") != "" and
        isinstance(press.get("description"), (str, type(None))) and
        isinstance(press.get("canonical"), str) and press.get("canonical") != "" and
        isinstance(press.get("date"), str) and press.get("date") != ""
    )
    statuses["press_meta_extracted"] = "pass" if press_meta_ok else "fail"

    launch_date = str(focus.get("launch_date")) if focus.get("launch_date") is not None else None
    statuses["press_launch_date_matches"] = "pass" if (launch_date and press.get("date") == launch_date) else "fail"

    org_domain = str(focus.get("organization_domain")) if focus.get("organization_domain") is not None else None
    domain_matches = False
    if org_domain and isinstance(press.get("canonical"), str):
        domain_matches = _domain_matches(press.get("canonical"), org_domain)
    statuses["press_canonical_matches_org_domain"] = "pass" if domain_matches else "fail"

    article_text = (press.get("article_text") or "").lower()
    msgs = [m.strip() for m in key_messages if m.strip()]
    matched = []
    for m in msgs:
        if m.lower() in article_text:
            matched.append(m)
    statuses["press_key_messages_coverage"] = "pass" if len(set(matched)) >= 3 else "fail"

    mailtos = press.get("mailto_emails_article") or press.get("mailto_emails_all") or []
    press_email = None
    if isinstance(mailtos, list) and len(mailtos) > 0:
        press_email = mailtos[0].strip()
    appears_once = False
    if press_email:
        count_in_contacts = sum(1 for e in emails if e == press_email.lower())
        appears_once = (count_in_contacts == 1)
    statuses["press_contact_email_exists_in_contacts"] = "pass" if (press_email and appears_once) else "fail"

    return statuses


def _load_key_messages(path: Path) -> Optional[List[str]]:
    txt = _read_text(path)
    if txt is None:
        return None
    lines = [line.strip() for line in txt.splitlines() if line.strip() != ""]
    return lines


def _compare_clean_contacts(expected_rows: List[Dict[str, str]], out_path: Path) -> bool:
    headers, rows = _read_csv_dicts(out_path)
    if headers is None or rows is None:
        return False
    required_headers = ["Outlet", "Name", "Email", "City", "State", "Beats"]
    if headers != required_headers:
        return False
    if len(rows) != len(expected_rows):
        return False
    for got, exp in zip(rows, expected_rows):
        for k in required_headers:
            if (got.get(k) or "") != (exp.get(k) or ""):
                return False
    return True


def _compare_extracted_press_meta(expected: Dict[str, Any], out_path: Path) -> bool:
    obj = _load_json(out_path)
    if not isinstance(obj, dict):
        return False
    required_keys = ["title", "description", "canonical", "date", "matched_messages_count", "matched_messages", "domain_matches"]
    for k in required_keys:
        if k not in obj:
            return False
    if not isinstance(obj.get("title"), str) or obj["title"] != expected["title"]:
        return False
    if obj.get("description") != expected["description"]:
        return False
    if not isinstance(obj.get("canonical"), str) or obj["canonical"] != expected["canonical"]:
        return False
    if not isinstance(obj.get("date"), str) or obj["date"] != expected["date"]:
        return False
    mm = obj.get("matched_messages")
    if not isinstance(mm, list):
        return False
    mm_set = {str(x) for x in mm}
    exp_set = {str(x) for x in expected["matched_messages"]}
    if mm_set != exp_set:
        return False
    if obj.get("matched_messages_count") != len(expected["matched_messages"]):
        return False
    if bool(obj.get("domain_matches")) != bool(expected["domain_matches"]):
        return False
    return True


def _parse_validation_report(path: Path) -> Optional[Dict[str, Any]]:
    obj = _load_json(path)
    if not isinstance(obj, dict):
        return None
    if "tests" not in obj or "summary" not in obj:
        return None
    tests = obj.get("tests")
    summary = obj.get("summary")
    if not isinstance(tests, list) or not isinstance(summary, dict):
        return None
    return obj


def _extract_press_expected(press: Dict[str, Any], focus: Dict[str, Any], key_messages: List[str]) -> Dict[str, Any]:
    title = press.get("title") or ""
    description = press.get("description") or ""
    canonical = press.get("canonical") or ""
    date = press.get("date") or ""
    article_text = (press.get("article_text") or "").lower()
    msgs = [m.strip() for m in key_messages if m.strip()]
    matched = []
    for m in msgs:
        if m.lower() in article_text:
            matched.append(m)
    domain_matches = False
    org_domain = str(focus.get("organization_domain")) if focus.get("organization_domain") is not None else ""
    if canonical and org_domain:
        domain_matches = _domain_matches(canonical, org_domain)
    return {
        "title": title,
        "description": description,
        "canonical": canonical,
        "date": date,
        "matched_messages": sorted(list({m for m in matched})),
        "domain_matches": domain_matches,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "validation_report_exists_and_parseable": 0.0,
        "validation_report_tests_present": 0.0,
        "validation_report_statuses_correct": 0.0,
        "validation_report_summary_correct": 0.0,
        "clean_contacts_csv_correct": 0.0,
        "extracted_press_meta_json_correct": 0.0,
    }

    input_contacts = workspace / "input" / "media_contacts.csv"
    input_focus = workspace / "input" / "campaign_focus.json"
    input_messages = workspace / "input" / "campaign_key_messages.txt"
    input_press = workspace / "input" / "press_release.html"

    out_report = workspace / "outputs" / "validation_report.json"
    out_clean = workspace / "outputs" / "clean_contacts.csv"
    out_press_meta = workspace / "outputs" / "extracted_press_meta.json"

    headers, rows = _read_csv_dicts(input_contacts) if input_contacts.exists() else (None, None)
    focus = _load_json(input_focus) if input_focus.exists() else None
    key_messages = _load_key_messages(input_messages) if input_messages.exists() else None
    press = _parse_press_release(input_press) if input_press.exists() else None

    expected_statuses = _expected_validation_statuses(headers, rows, focus, press, key_messages) if all(v is not None for v in [headers, rows, focus, press, key_messages]) else None

    expected_clean: Optional[List[Dict[str, str]]] = None
    if rows is not None and focus is not None and all(col in (headers or []) for col in ["Outlet", "Name", "Email", "City", "State", "Beats"]) and isinstance(focus.get("focus_topics"), list):
        expected_clean = _expected_clean_contacts(rows, focus.get("focus_topics"))
    expected_press_meta: Optional[Dict[str, Any]] = None
    if press is not None and focus is not None and key_messages is not None:
        expected_press_meta = _extract_press_expected(press, focus, key_messages)

    report_obj = _parse_validation_report(out_report) if out_report.exists() else None
    if report_obj is not None:
        scores["validation_report_exists_and_parseable"] = 1.0
        tests_list = report_obj.get("tests", [])
        test_map = {}
        all_have_fields = True
        for t in tests_list:
            if not isinstance(t, dict):
                all_have_fields = False
                break
            name = t.get("name")
            status = t.get("status")
            details = t.get("details")
            if not isinstance(name, str) or not isinstance(status, str) or not isinstance(details, (str, type(None))):
                all_have_fields = False
                break
            test_map[name] = t
        required_test_names = [
            "contacts_required_columns",
            "contacts_valid_emails",
            "contacts_duplicates_detected",
            "contacts_focus_topics_alignment",
            "press_meta_extracted",
            "press_launch_date_matches",
            "press_canonical_matches_org_domain",
            "press_key_messages_coverage",
            "press_contact_email_exists_in_contacts",
        ]
        tests_present = all(name in test_map for name in required_test_names) and all_have_fields
        if tests_present:
            scores["validation_report_tests_present"] = 1.0

        if expected_statuses is not None and tests_present:
            statuses_match = True
            for name in required_test_names:
                expected_status = expected_statuses.get(name)
                got_status = (test_map.get(name) or {}).get("status")
                if got_status not in ("pass", "fail"):
                    statuses_match = False
                    break
                if expected_status != got_status:
                    statuses_match = False
                    break
            if statuses_match:
                scores["validation_report_statuses_correct"] = 1.0

        summary = report_obj.get("summary", {})
        if isinstance(summary, dict) and tests_present:
            try:
                passed = int(summary.get("passed"))
                failed = int(summary.get("failed"))
                counted_pass = sum(1 for t in tests_list if isinstance(t, dict) and t.get("status") == "pass")
                counted_fail = sum(1 for t in tests_list if isinstance(t, dict) and t.get("status") == "fail")
                if passed == counted_pass and failed == counted_fail:
                    if expected_statuses is not None:
                        exp_pass = sum(1 for v in expected_statuses.values() if v == "pass")
                        exp_fail = sum(1 for v in expected_statuses.values() if v == "fail")
                        if exp_pass == counted_pass and exp_fail == counted_fail:
                            scores["validation_report_summary_correct"] = 1.0
                    else:
                        scores["validation_report_summary_correct"] = 1.0
            except Exception:
                pass

    if out_clean.exists() and expected_clean is not None:
        if _compare_clean_contacts(expected_clean, out_clean):
            scores["clean_contacts_csv_correct"] = 1.0

    if out_press_meta.exists() and expected_press_meta is not None:
        exp = {
            "title": expected_press_meta["title"],
            "description": expected_press_meta["description"],
            "canonical": expected_press_meta["canonical"],
            "date": expected_press_meta["date"],
            "matched_messages": expected_press_meta["matched_messages"],
            "domain_matches": expected_press_meta["domain_matches"],
        }
        if _compare_extracted_press_meta(exp, out_press_meta):
            scores["extracted_press_meta_json_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()