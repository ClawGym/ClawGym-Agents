import json
import sys;
import re
import csv
from pathlib import Path
from html.parser import HTMLParser
from html import unescape


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        text = safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def safe_read_csv(path: Path):
    try:
        text = safe_read_text(path)
        if text is None:
            return None, None
        lines = text.splitlines()
        if not lines:
            return None, None
        reader = csv.DictReader(lines)
        rows = list(reader)
        return reader.fieldnames, rows
    except Exception:
        return None, None


def parse_simple_yaml(path: Path) -> dict:
    content = safe_read_text(path)
    if content is None:
        return {}
    data = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            val = val[1:-1]
        data[key] = val
    return data


class CoxHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title_parts = []

        self.in_heading = False
        self.current_heading_tag = None
        self.heading_parts = []

        self.capture_next_ul_assumptions = False
        self.in_assumption_ul = False
        self.in_li = False
        self.li_parts = []
        self.assumptions = []

        self.in_code = False
        self.code_parts = []
        self.code_examples = []

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower == "title":
            self.in_title = True
        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.in_heading = True
            self.current_heading_tag = tag_lower
            self.heading_parts = []
        if tag_lower == "ul" and self.capture_next_ul_assumptions:
            self.in_assumption_ul = True
        if tag_lower == "li" and self.in_assumption_ul:
            self.in_li = True
            self.li_parts = []
        if tag_lower == "code":
            self.in_code = True
            self.code_parts = []

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower == "title":
            self.in_title = False
        if self.in_heading and self.current_heading_tag == tag_lower:
            heading_text = unescape("".join(self.heading_parts)).strip()
            if re.search(r"assumptions", heading_text, re.IGNORECASE):
                self.capture_next_ul_assumptions = True
            self.in_heading = False
            self.current_heading_tag = None
            self.heading_parts = []
        if tag_lower == "ul" and self.in_assumption_ul:
            self.in_assumption_ul = False
            self.capture_next_ul_assumptions = False
        if tag_lower == "li" and self.in_li:
            text = unescape("".join(self.li_parts)).strip()
            if text:
                self.assumptions.append(text)
            self.in_li = False
            self.li_parts = []
        if tag_lower == "code" and self.in_code:
            code_text = unescape("".join(self.code_parts)).strip()
            if re.search(r"(coxph|coxphfitter)", code_text, re.IGNORECASE):
                lines = code_text.splitlines()
                trimmed = "\n".join([line.rstrip() for line in lines]).strip()
                self.code_examples.append(trimmed)
            self.in_code = False
            self.code_parts = []

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if self.in_heading:
            self.heading_parts.append(data)
        if self.in_li:
            self.li_parts.append(data)
        if self.in_code:
            self.code_parts.append(data)


def parse_html_file(html_path: Path):
    text = safe_read_text(html_path)
    if text is None:
        return None
    parser = CoxHtmlParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    title = unescape("".join(parser.title_parts)).strip()
    code_examples = [c.strip() for c in parser.code_examples]
    assumptions = [a.strip() for a in parser.assumptions]
    return {
        "page_title": title,
        "assumptions": assumptions,
        "code_examples": code_examples,
    }


def compute_expected_from_inputs(workspace: Path):
    files = [
        workspace / "input" / "survival_vignette.html",
        workspace / "input" / "python_lifelines_tutorial.html",
    ]
    results = {}
    for p in files:
        parsed = parse_html_file(p)
        if parsed is None:
            return None
        results[str(p.relative_to(workspace))] = parsed
    return results


def expected_matched_keyword(assumption: str) -> str:
    tokens = ["proportional hazards", "linearity", "censoring", "collinearity"]
    lower = assumption.lower()
    for t in tokens:
        if t in lower:
            return t
    return ""


def normalize_whitespace(s: str) -> str:
    if s is None:
        return ""
    return "\n".join([line.rstrip() for line in s.strip().splitlines()]).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "json_file_parsed": 0.0,
        "json_sources_and_count": 0.0,
        "json_page_titles_match": 0.0,
        "json_assumptions_match": 0.0,
        "json_code_examples_match": 0.0,
        "csv_file_parsed": 0.0,
        "csv_header_correct": 0.0,
        "csv_row_count_correct": 0.0,
        "csv_rows_match_expected": 0.0,
        "email_cmd_line_in_header": 0.0,
        "email_salutation_correct": 0.0,
        "email_summary_paragraph_mentions_count_and_formats": 0.0,
        "email_three_bullets_valid": 0.0,
        "email_code_snippet_labeled_and_sourced": 0.0,
        "email_exact_question_included": 0.0,
        "email_closing_includes_name_and_course": 0.0,
    }

    expected = compute_expected_from_inputs(workspace)
    if expected is None:
        expected_sources = {}
    else:
        expected_sources = expected

    # JSON checks
    json_path = workspace / "outputs" / "coxscrape.json"
    json_data = safe_load_json(json_path)
    if isinstance(json_data, list):
        scores["json_file_parsed"] = 1.0
        try:
            if len(json_data) == 2 and all(isinstance(x, dict) for x in json_data):
                sources_in_json = {}
                for obj in json_data:
                    sf = obj.get("source_file")
                    if isinstance(sf, str):
                        sources_in_json[sf] = obj
                expected_source_files = set(expected_sources.keys()) if expected_sources else set()
                if expected_source_files and set(sources_in_json.keys()) == expected_source_files:
                    scores["json_sources_and_count"] = 1.0

                all_titles_match = True
                all_assumptions_match = True
                all_code_examples_match = True
                if expected_sources:
                    for sf, exp in expected_sources.items():
                        obj = sources_in_json.get(sf)
                        if not obj:
                            all_titles_match = False
                            all_assumptions_match = False
                            all_code_examples_match = False
                            continue
                        got_title = obj.get("page_title")
                        if not isinstance(got_title, str) or got_title.strip() != exp["page_title"].strip():
                            all_titles_match = False
                        got_assumptions = obj.get("assumptions")
                        if not isinstance(got_assumptions, list) or any(not isinstance(a, str) for a in got_assumptions):
                            all_assumptions_match = False
                        else:
                            exp_list = [a.strip() for a in exp["assumptions"]]
                            got_list = [a.strip() for a in got_assumptions]
                            if got_list != exp_list:
                                all_assumptions_match = False
                        got_code = obj.get("code_examples")
                        if not isinstance(got_code, list) or any(not isinstance(c, str) for c in got_code):
                            all_code_examples_match = False
                        else:
                            exp_code = [normalize_whitespace(c) for c in exp["code_examples"]]
                            got_code_norm = [normalize_whitespace(c) for c in got_code]
                            if got_code_norm != exp_code:
                                all_code_examples_match = False
                else:
                    all_titles_match = False
                    all_assumptions_match = False
                    all_code_examples_match = False

                if all_titles_match:
                    scores["json_page_titles_match"] = 1.0
                if all_assumptions_match:
                    scores["json_assumptions_match"] = 1.0
                if all_code_examples_match:
                    scores["json_code_examples_match"] = 1.0
        except Exception:
            pass
    else:
        scores["json_file_parsed"] = 0.0

    # CSV checks
    csv_path = workspace / "outputs" / "assumptions_flat.csv"
    headers, rows = safe_read_csv(csv_path)
    if headers is not None and rows is not None:
        scores["csv_file_parsed"] = 1.0
        expected_headers = ["source_file", "page_title", "assumption", "matched_keyword"]
        if headers == expected_headers:
            scores["csv_header_correct"] = 1.0

        expected_rows = []
        if expected_sources:
            for sf, exp in expected_sources.items():
                for assumption in exp["assumptions"]:
                    expected_rows.append({
                        "source_file": sf,
                        "page_title": exp["page_title"],
                        "assumption": assumption.strip(),
                        "matched_keyword": expected_matched_keyword(assumption),
                    })
        if expected_rows:
            if len(rows) == len(expected_rows):
                scores["csv_row_count_correct"] = 1.0

            try:
                exp_set = set(
                    (r["source_file"].strip(),
                     r["page_title"].strip(),
                     r["assumption"].strip(),
                     r["matched_keyword"].strip().lower())
                    for r in expected_rows
                )
                got_set = set()
                for r in rows:
                    sf = (r.get("source_file") or "").strip()
                    pt = (r.get("page_title") or "").strip()
                    asmp = (r.get("assumption") or "").strip()
                    mk = (r.get("matched_keyword") or "").strip().lower()
                    got_set.add((sf, pt, asmp, mk))
                if got_set == exp_set:
                    scores["csv_rows_match_expected"] = 1.0
            except Exception:
                pass

    # Email checks
    email_path = workspace / "outputs" / "email_draft.txt"
    email_text = safe_read_text(email_path)
    if email_text is not None:
        lines = email_text.splitlines()
        if lines:
            first_line = lines[0].strip()
            if first_line.startswith("CMD: "):
                cmd = first_line[len("CMD: "):].strip()
                has_script = "scripts/scrape_cox.py" in cmd
                has_input1 = "input/survival_vignette.html" in cmd
                has_input2 = "input/python_lifelines_tutorial.html" in cmd
                has_out_json = "--out-json outputs/coxscrape.json" in cmd
                has_out_csv = "--out-csv outputs/assumptions_flat.csv" in cmd
                if has_script and has_input1 and has_input2 and has_out_json and has_out_csv:
                    scores["email_cmd_line_in_header"] = 1.0

        yaml_data = parse_simple_yaml(workspace / "input" / "recipient.yaml")
        to_name = yaml_data.get("to_name", "").strip()
        signer_name = yaml_data.get("signer_name", "").strip()
        course = yaml_data.get("course", "").strip()

        first_content_line = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip():
                first_content_line = line.strip()
                break
        if to_name and first_content_line is not None:
            expected_salutation = f"Hi {to_name},"
            if first_content_line.startswith(expected_salutation):
                scores["email_salutation_correct"] = 1.0

        total_assumptions = None
        if rows is not None:
            total_assumptions = len(rows)
        if total_assumptions is not None:
            body_text = "\n".join(lines[1:]).lower()
            if str(total_assumptions) in body_text and ("csv" in body_text) and ("json" in body_text):
                scores["email_summary_paragraph_mentions_count_and_formats"] = 1.0

        bullet_lines = []
        for line in lines:
            l = line.strip()
            if l.startswith("- ") or l.startswith("* ") or l.startswith("• "):
                bullet_lines.append(l)
        valid_bullets = False
        if len(bullet_lines) == 3 and expected_sources:
            valid_pairs = set()
            for sf, exp in expected_sources.items():
                for a in exp["assumptions"]:
                    valid_pairs.add((a.strip(), exp["page_title"].strip()))
            assumptions_seen = set()
            pattern = re.compile(r"^\s*[-\*\u2022]\s+(?P<assumption>.+?)\s*\(source:\s*(?P<page>.+?)\)\s*$")
            all_valid = True
            for bl in bullet_lines:
                m = pattern.match(bl)
                if not m:
                    all_valid = False
                    break
                assumption_text = m.group("assumption").strip()
                page_title_text = m.group("page").strip()
                if assumption_text in assumptions_seen:
                    all_valid = False
                    break
                assumptions_seen.add(assumption_text)
                if (assumption_text, page_title_text) not in valid_pairs:
                    all_valid = False
                    break
            if all_valid:
                valid_bullets = True
        if valid_bullets:
            scores["email_three_bullets_valid"] = 1.0

        code_snippet_ok = False
        if json_data and isinstance(json_data, list):
            code_examples_all = []
            for obj in json_data:
                if isinstance(obj, dict) and isinstance(obj.get("code_examples"), list):
                    for ce in obj["code_examples"]:
                        code_examples_all.append(normalize_whitespace(str(ce)))
            for idx, line in enumerate(lines):
                l = line.strip()
                if l.startswith("R:") or l.startswith("Python:"):
                    label, rest = l.split(":", 1)
                    code_content = rest.strip()
                    follow_line = ""
                    if idx + 1 < len(lines):
                        next_line = lines[idx + 1].strip()
                        if next_line and not next_line.startswith(("Hi ", "CMD:", "- ", "* ", "• ")):
                            follow_line = next_line
                    combined = code_content if not follow_line else (code_content + "\n" + follow_line)
                    combined_norm = normalize_whitespace(combined)
                    if label == "R" and "coxph(" in combined:
                        if any(combined_norm in ce for ce in code_examples_all):
                            code_snippet_ok = True
                            break
                    if label == "Python" and re.search(r"CoxPHFitter", combined):
                        if any(combined_norm in ce for ce in code_examples_all):
                            code_snippet_ok = True
                            break
        if code_snippet_ok:
            scores["email_code_snippet_labeled_and_sourced"] = 1.0

        exact_question = "Is checking Schoenfeld residuals sufficient for assessing proportional hazards, or should I also model time-varying effects?"
        if exact_question in email_text:
            scores["email_exact_question_included"] = 1.0

        tail_lines = [ln.strip() for ln in lines if ln.strip()]
        tail_ok = False
        if signer_name and course and tail_lines:
            tail = tail_lines[-5:]
            tail_text = "\n".join(tail)
            if signer_name in tail_text and course in tail_text:
                tail_ok = True
        if tail_ok:
            scores["email_closing_includes_name_and_course"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()