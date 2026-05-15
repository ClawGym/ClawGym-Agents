import csv
import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


AS_OF_DATE = "2026-05-15"
KEYWORDS = ["native", "pollinator", "habitat restoration", "invasive species", "prairie", "riparian"]

# -----------------------------
# Helper functions
# -----------------------------


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_json_load(path: Path) -> Optional[Any]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def split_topics(text: str) -> List[str]:
    parts = re.split(r"[;,]", text)
    return [p.strip() for p in parts if p.strip()]


def parse_money_to_int(text: str) -> Optional[int]:
    try:
        # Remove currency symbols and commas/spaces
        cleaned = re.sub(r"[^\d]", "", text)
        if cleaned == "":
            return None
        return int(cleaned)
    except Exception:
        return None


def is_iso_date(date_str: str) -> bool:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except Exception:
        return False


def format_money_usd(amount: int) -> str:
    return f"${amount:,}"


def to_lower(s: str) -> str:
    return s.lower()


class Page1TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.table_id_target = "grants"
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_row: List[str] = []
        self.current_cell_data: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "table" and attrs_dict.get("id") == self.table_id_target:
            self.in_table = True
        elif self.in_table and tag == "tbody":
            self.in_tbody = True
        elif self.in_table and self.in_tbody and tag == "tr":
            self.in_tr = True
            self.current_row = []
        elif self.in_table and self.in_tbody and self.in_tr and tag == "td":
            self.in_td = True
            self.current_cell_data = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self.in_table:
            self.in_table = False
        elif tag == "tbody" and self.in_table and self.in_tbody:
            self.in_tbody = False
        elif tag == "tr" and self.in_table and self.in_tbody and self.in_tr:
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)
        elif tag == "td" and self.in_table and self.in_tbody and self.in_tr and self.in_td:
            cell_text = "".join(self.current_cell_data).strip()
            self.current_row.append(cell_text)
            self.in_td = False
            self.current_cell_data = []

    def handle_data(self, data: str) -> None:
        if self.in_table and self.in_tbody and self.in_tr and self.in_td:
            self.current_cell_data.append(data)


class Page2DivParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_grant_div = False
        self.current_grant: Dict[str, Any] = {}
        self.grants: List[Dict[str, Any]] = []
        self.in_h3 = False
        self.current_text_fragments: List[str] = []
        self.in_dt = False
        self.in_dd = False
        self.current_dt_name: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "div":
            class_attr = attrs_dict.get("class", "")
            if class_attr and "grant" in class_attr.split():
                self.in_grant_div = True
                self.current_grant = {}
        if self.in_grant_div and tag == "h3":
            self.in_h3 = True
            self.current_text_fragments = []
        if self.in_grant_div and tag == "dt":
            self.in_dt = True
            self.current_text_fragments = []
        if self.in_grant_div and tag == "dd":
            self.in_dd = True
            self.current_text_fragments = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.in_grant_div:
            # Finish a grant record
            self.in_grant_div = False
            if self.current_grant:
                self.grants.append(self.current_grant)
            self.current_grant = {}
        if tag == "h3" and self.in_grant_div and self.in_h3:
            text = "".join(self.current_text_fragments).strip()
            self.current_grant["Program"] = text
            self.in_h3 = False
            self.current_text_fragments = []
        if tag == "dt" and self.in_grant_div and self.in_dt:
            dt_text = "".join(self.current_text_fragments).strip()
            self.current_dt_name = dt_text
            self.in_dt = False
            self.current_text_fragments = []
        if tag == "dd" and self.in_grant_div and self.in_dd:
            dd_text = "".join(self.current_text_fragments).strip()
            if self.current_dt_name:
                self.current_grant[self.current_dt_name] = dd_text
            self.in_dd = False
            self.current_text_fragments = []

    def handle_data(self, data: str) -> None:
        if self.in_grant_div and (self.in_h3 or self.in_dt or self.in_dd):
            self.current_text_fragments.append(data)


def parse_input_grants(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    # Parse both HTML input files and produce standardized list of grants
    input1 = workspace / "input" / "grants_page1.html"
    input2 = workspace / "input" / "grants_page2.html"

    expected: List[Dict[str, Any]] = []

    # Page 1
    text1 = safe_read_text(input1)
    if text1 is None:
        return None
    p1 = Page1TableParser()
    try:
        p1.feed(text1)
    except Exception:
        return None
    for row in p1.rows:
        # Expect 6 columns: Program, Agency, Topics, Max Award, Deadline, Eligibility
        if len(row) != 6:
            return None
        program, agency, topics_text, max_award_text, deadline_text, eligibility_text = row
        topics_list = split_topics(topics_text)
        max_award = parse_money_to_int(max_award_text)
        if max_award is None:
            return None
        if not is_iso_date(deadline_text):
            return None
        expected.append(
            {
                "program_name": program,
                "agency": agency,
                "topics": topics_list,
                "max_award_usd": max_award,
                "deadline": deadline_text,
                "eligibility": eligibility_text,
                "source_file": "input/grants_page1.html",
            }
        )

    # Page 2
    text2 = safe_read_text(input2)
    if text2 is None:
        return None
    p2 = Page2DivParser()
    try:
        p2.feed(text2)
    except Exception:
        return None
    for g in p2.grants:
        # Normalize keys
        program = g.get("Program")
        agency = g.get("Agency")
        topics_text = g.get("Topics")
        max_award_text = g.get("Max Award")
        deadline_text = g.get("Deadline")
        eligibility_text = g.get("Eligibility")
        if not all(isinstance(x, str) and x.strip() for x in [program, agency, topics_text, max_award_text, deadline_text, eligibility_text]):
            return None
        topics_list = split_topics(topics_text)
        max_award = parse_money_to_int(max_award_text)
        if max_award is None:
            return None
        if not is_iso_date(deadline_text):
            return None
        expected.append(
            {
                "program_name": program.strip(),
                "agency": agency.strip(),
                "topics": topics_list,
                "max_award_usd": max_award,
                "deadline": deadline_text.strip(),
                "eligibility": eligibility_text.strip(),
                "source_file": "input/grants_page2.html",
            }
        )
    return expected


def normalize_record_core(rec: Dict[str, Any]) -> Tuple:
    # Only include required fields, with types normalized
    return (
        rec.get("program_name"),
        rec.get("agency"),
        tuple(rec.get("topics") or []),
        int(rec.get("max_award_usd")) if isinstance(rec.get("max_award_usd"), int) or (isinstance(rec.get("max_award_usd"), str) and rec.get("max_award_usd").isdigit()) else rec.get("max_award_usd"),
        rec.get("deadline"),
        rec.get("eligibility"),
        rec.get("source_file"),
    )


def load_extracted_json(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = safe_json_load(path)
    if not isinstance(data, list):
        return None
    # Ensure all list items are dicts
    for item in data:
        if not isinstance(item, dict):
            return None
    return data


def filter_and_rank(grants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Filter by keywords and eligibility and deadline on/after AS_OF_DATE
    cutoff = datetime.strptime(AS_OF_DATE, "%Y-%m-%d")
    filtered: List[Dict[str, Any]] = []

    for rec in grants:
        topics_field = rec.get("topics")
        if isinstance(topics_field, list):
            topics_text = "; ".join(t for t in topics_field if isinstance(t, str))
        elif isinstance(topics_field, str):
            topics_text = topics_field
        else:
            continue
        topics_lower = topics_text.lower()
        matched = [kw for kw in KEYWORDS if kw in topics_lower]
        eligibility = rec.get("eligibility", "")
        if not isinstance(eligibility, str):
            continue
        eligible_state = ("midvale" in eligibility.lower()) or ("nationwide" in eligibility.lower())
        deadline_str = rec.get("deadline")
        if not isinstance(deadline_str, str) or not is_iso_date(deadline_str):
            continue
        deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d")
        if matched and eligible_state and deadline_dt >= cutoff:
            new_rec = dict(rec)
            new_rec["_matched_keywords"] = matched
            filtered.append(new_rec)

    # Rank by deadline asc, max_award desc, program_name asc
    filtered.sort(
        key=lambda r: (
            datetime.strptime(r["deadline"], "%Y-%m-%d"),
            -int(r["max_award_usd"]),
            r["program_name"],
        )
    )
    return filtered


def safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)
        return header, rows
    except Exception:
        return None, None


def compute_relevance_keywords(topics: List[str]) -> str:
    # Compute matched keywords in specified order, lowercase, semicolon-separated
    topics_text = "; ".join(topics).lower()
    matched = [kw for kw in KEYWORDS if kw in topics_text]
    return ";".join(matched)


def all_required_fields_present_and_typed(rec: Dict[str, Any]) -> bool:
    # program_name: str
    # agency: str
    # topics: list of str
    # max_award_usd: int
    # deadline: YYYY-MM-DD
    # eligibility: str
    # source_file: str
    if not isinstance(rec, dict):
        return False
    required = ["program_name", "agency", "topics", "max_award_usd", "deadline", "eligibility", "source_file"]
    for k in required:
        if k not in rec:
            return False
    if not isinstance(rec["program_name"], str):
        return False
    if not isinstance(rec["agency"], str):
        return False
    if not isinstance(rec["topics"], list) or not all(isinstance(t, str) for t in rec["topics"]):
        return False
    if not isinstance(rec["max_award_usd"], int):
        return False
    if not isinstance(rec["deadline"], str) or not is_iso_date(rec["deadline"]):
        return False
    if not isinstance(rec["eligibility"], str):
        return False
    if not isinstance(rec["source_file"], str):
        return False
    return True


def find_email_subject_line(text: str, expected_subject: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines()]
    for ln in lines:
        if not ln:
            continue
        if ln == expected_subject:
            return True
        if ln.lower().startswith("subject:"):
            subj = ln[len("subject:"):].strip()
            if subj == expected_subject:
                return True
    return False


def email_contains_criteria(text: str) -> bool:
    t = text.lower()
    # Must mention keywords concept, Midvale or Nationwide, and the as-of date
    has_keywords = ("keyword" in t)
    has_elig = ("midvale" in t) or ("nationwide" in t)
    has_date = (AS_OF_DATE in text)
    return has_keywords and has_elig and has_date


def email_lists_programs(text: str, programs: List[Dict[str, Any]]) -> bool:
    # For each program in order, ensure there is a line that includes program_name, agency, deadline, and max award (formatted)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for idx, rec in enumerate(programs, start=1):
        prog = rec["program_name"]
        agency = rec["agency"]
        deadline = rec["deadline"]
        amt = format_money_usd(int(rec["max_award_usd"]))
        found = False
        for ln in lines:
            # Require the line to include program name, agency, deadline date, and amount
            if (prog in ln) and (agency in ln) and (deadline in ln) and (amt in ln):
                # Prefer but not strictly require rank number presence
                if str(idx) in ln:
                    found = True
                    break
                else:
                    # If not present with number, still accept to avoid over-failing if formatting differs
                    found = True
                    break
        if not found:
            return False
    return True


def email_has_closing_and_refs(text: str) -> bool:
    t = text.lower()
    has_matching = ("matching fund" in t)
    has_outreach = ("outreach" in t)
    has_coord = ("coordinat" in t)  # coordinate/coordination
    has_refs = ("output/native_plant_grants_ranked.csv" in text) and ("output/grants_extracted.json" in text)
    return has_matching and has_outreach and has_coord and has_refs


# -----------------------------
# Grader
# -----------------------------


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "extracted_json_exists_and_valid": 0.0,
        "extracted_json_record_count_correct": 0.0,
        "extracted_json_field_types_valid": 0.0,
        "extracted_json_content_match": 0.0,
        "ranked_csv_exists_and_header": 0.0,
        "ranked_csv_row_count_and_order": 0.0,
        "ranked_csv_content_values": 0.0,
        "relevance_keywords_correct": 0.0,
        "email_exists_and_subject": 0.0,
        "email_includes_selection_criteria": 0.0,
        "email_lists_top5_matching_csv": 0.0,
        "email_includes_closing_and_data_refs": 0.0,
    }

    # Compute expected dataset by parsing inputs
    expected_grants = parse_input_grants(workspace)
    expected_valid = isinstance(expected_grants, list) and len(expected_grants) > 0
    expected_count = len(expected_grants) if expected_valid else None

    # Expected filtered and ranked top 5
    expected_top5: Optional[List[Dict[str, Any]]] = None
    if expected_valid:
        filtered_ranked = filter_and_rank(expected_grants)
        expected_top5 = filtered_ranked[:5]

    # 1) Validate extracted JSON
    extracted_path = workspace / "output" / "grants_extracted.json"
    extracted_data = load_extracted_json(extracted_path)
    if isinstance(extracted_data, list):
        scores["extracted_json_exists_and_valid"] = 1.0

        # Types check
        if all(all_required_fields_present_and_typed(rec) for rec in extracted_data):
            scores["extracted_json_field_types_valid"] = 1.0

        # Record count check
        if expected_count is not None and len(extracted_data) == expected_count:
            scores["extracted_json_record_count_correct"] = 1.0

        # Content match check
        if expected_valid:
            try:
                # Build normalized sets
                expected_norm = set()
                for rec in expected_grants:
                    expected_norm.add(
                        (
                            rec["program_name"],
                            rec["agency"],
                            tuple(rec["topics"]),
                            int(rec["max_award_usd"]),
                            rec["deadline"],
                            rec["eligibility"],
                            rec["source_file"],
                        )
                    )
                extracted_norm = set()
                for rec in extracted_data:
                    # Must have required keys
                    if not all(k in rec for k in ["program_name", "agency", "topics", "max_award_usd", "deadline", "eligibility", "source_file"]):
                        extracted_norm = set()
                        break
                    topics = rec["topics"] if isinstance(rec["topics"], list) else []
                    extracted_norm.add(
                        (
                            rec["program_name"],
                            rec["agency"],
                            tuple(topics),
                            int(rec["max_award_usd"]) if isinstance(rec["max_award_usd"], int) else rec["max_award_usd"],
                            rec["deadline"],
                            rec["eligibility"],
                            rec["source_file"],
                        )
                    )
                if expected_norm == extracted_norm and len(expected_norm) == len(expected_grants):
                    scores["extracted_json_content_match"] = 1.0
            except Exception:
                pass

    # 2) Validate ranked CSV
    csv_path = workspace / "output" / "native_plant_grants_ranked.csv"
    header, rows = safe_read_csv(csv_path)
    expected_header = ["rank", "program_name", "agency", "max_award_usd", "deadline", "eligibility", "relevance_keywords"]

    if header is not None and rows is not None:
        if header == expected_header:
            scores["ranked_csv_exists_and_header"] = 1.0

        # Check row count and order compared to expected
        if expected_top5 is not None and header == expected_header:
            # Row count must be exactly 5
            if len(rows) == 5:
                # Check order: program_name sequence must match expected_top5
                order_ok = True
                for i, (row, exp) in enumerate(zip(rows, expected_top5), start=1):
                    # Rank should be 1..5 and as string representing int
                    try:
                        if int(row["rank"]) != i:
                            order_ok = False
                            break
                    except Exception:
                        order_ok = False
                        break
                    if row["program_name"] != exp["program_name"]:
                        order_ok = False
                        break
                    if row["deadline"] != exp["deadline"]:
                        order_ok = False
                        break
                if order_ok:
                    scores["ranked_csv_row_count_and_order"] = 1.0

            # Content values check
            content_ok = True
            if len(rows) != 5:
                content_ok = False
            else:
                for i, (row, exp) in enumerate(zip(rows, expected_top5), start=1):
                    # agency
                    if row.get("agency") != exp["agency"]:
                        content_ok = False
                        break
                    # deadline iso
                    if not is_iso_date(row.get("deadline", "")) or row.get("deadline") != exp["deadline"]:
                        content_ok = False
                        break
                    # eligibility must match verbatim
                    if row.get("eligibility") != exp["eligibility"]:
                        content_ok = False
                        break
                    # max_award_usd numeric and equal
                    try:
                        row_amt = int(str(row.get("max_award_usd", "")).strip())
                    except Exception:
                        content_ok = False
                        break
                    if row_amt != int(exp["max_award_usd"]):
                        content_ok = False
                        break
            if content_ok:
                scores["ranked_csv_content_values"] = 1.0

            # relevance_keywords check
            rel_ok = True
            if len(rows) == 5:
                for row, exp in zip(rows, expected_top5):
                    # Compute expected relevance keywords from topics
                    exp_rel = compute_relevance_keywords(exp["topics"])
                    row_rel = (row.get("relevance_keywords") or "").strip()
                    if row_rel != exp_rel:
                        rel_ok = False
                        break
            else:
                rel_ok = False
            if rel_ok:
                scores["relevance_keywords_correct"] = 1.0

    # 3) Validate email draft
    email_path = workspace / "output" / "email_draft.md"
    email_text = safe_read_text(email_path)
    if email_text is not None:
        subject = "Top 5 upcoming grant opportunities to advance native plant restoration (as of 2026-05-15)"
        if find_email_subject_line(email_text, subject):
            scores["email_exists_and_subject"] = 1.0
        if email_contains_criteria(email_text):
            scores["email_includes_selection_criteria"] = 1.0

        # Email lists top 5 entries matching the CSV and rank order
        if rows is not None and header == expected_header and len(rows) == 5:
            # Build program dicts from CSV rows for check
            csv_programs: List[Dict[str, Any]] = []
            for row in rows:
                try:
                    amt = int(str(row["max_award_usd"]).strip())
                except Exception:
                    amt = None
                csv_programs.append(
                    {
                        "program_name": row["program_name"],
                        "agency": row["agency"],
                        "deadline": row["deadline"],
                        "max_award_usd": amt if amt is not None else 0,
                    }
                )
            if email_lists_programs(email_text, csv_programs):
                scores["email_lists_top5_matching_csv"] = 1.0

        if email_has_closing_and_refs(email_text):
            scores["email_includes_closing_and_data_refs"] = 1.0

    return scores


# -----------------------------
# CLI Entrypoint
# -----------------------------


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()