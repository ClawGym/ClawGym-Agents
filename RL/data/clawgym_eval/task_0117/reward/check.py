import sys
import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
from email import policy
from email.parser import BytesParser


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""


def load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = list(reader)
            return headers, rows
    except Exception:
        return None, None


def write_json_stdout(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def normalize_email(email: str) -> str:
    if email is None:
        return ""
    return email.strip().lower()


def split_races(value: str):
    if not value:
        return []
    parts = re.split(r"[;,/]", value)
    return [p.strip() for p in parts if p.strip()]


def normalize_races(value: str) -> str:
    items = split_races(value)
    return "; ".join(items)


class SignupsTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_thead = False
        self.in_tbody = False
        self.in_row = False
        self.in_cell = False
        self.current_cell_data = []
        self.current_row = []
        self.rows = []
        self.table_id_stack = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self.table_id_stack.append(attrs_dict.get("id", ""))
            if attrs_dict.get("id") == "signups":
                self.in_table = True
        if self.in_table:
            if tag == "thead":
                self.in_thead = True
            elif tag == "tbody":
                self.in_tbody = True
            elif tag == "tr":
                self.in_row = True
                self.current_row = []
            elif tag in ("td", "th"):
                self.in_cell = True
                self.current_cell_data = []

    def handle_endtag(self, tag):
        if tag == "table":
            # Pop stack and exit signups table if applicable
            last_id = self.table_id_stack.pop() if self.table_id_stack else ""
            if last_id == "signups":
                self.in_table = False
        if self.in_table:
            if tag == "thead":
                self.in_thead = False
            elif tag == "tbody":
                self.in_tbody = False
            elif tag == "tr":
                if self.in_row and self.in_tbody and self.current_row:
                    self.rows.append([cell.strip() for cell in self.current_row])
                self.in_row = False
                self.current_row = []
            elif tag in ("td", "th"):
                if self.in_cell:
                    cell_text = "".join(self.current_cell_data).strip()
                    self.current_row.append(cell_text)
                    self.current_cell_data = []
                self.in_cell = False

    def handle_data(self, data):
        if self.in_table and self.in_row and self.in_cell:
            self.current_cell_data.append(data)


def parse_form_signups(path: Path):
    """
    Returns list of dicts with keys:
    full_name, email, self_identified_races, partner_races, availability, city, consent, message
    """
    if not path.exists():
        return []
    text = read_text(path)
    if not text:
        return []
    parser = SignupsTableParser()
    try:
        parser.feed(text)
    except Exception:
        return []
    records = []
    for row in parser.rows:
        # Expect 8 columns per spec
        if len(row) != 8:
            # Skip malformed rows strictly
            return []  # fail parsing if structure unexpected
        name, email, self_race, partner_race, availability, city, consent, message = row
        records.append({
            "full_name": name.strip(),
            "email": email.strip(),
            "self_identified_races": self_race.strip(),
            "partner_races": partner_race.strip(),
            "availability": availability.strip(),
            "city": city.strip(),
            "consent": consent.strip(),
            "message": message.strip(),
            "source": "form",
        })
    return records


def parse_eml_file(path: Path):
    try:
        with path.open("rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)
    except Exception:
        return None
    subject = msg.get("Subject", "").strip()
    # Get body text
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                try:
                    body = part.get_content().strip()
                    break
                except Exception:
                    try:
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore").strip()
                        break
                    except Exception:
                        continue
    else:
        try:
            body = msg.get_content().strip()
        except Exception:
            try:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore").strip()
            except Exception:
                body = ""
    # Parse key-value lines
    fields = {
        "Name": "",
        "Email": "",
        "Self-Identified Race(s)": "",
        "Partner Race(s)": "",
        "Availability": "",
        "Consent": "",
        "Message": "",
    }
    for line in body.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Match keys case-insensitively
            for canonical in list(fields.keys()):
                if key.lower() == canonical.lower():
                    fields[canonical] = val
                    break
    record = {
        "full_name": fields["Name"].strip(),
        "email": fields["Email"].strip(),
        "self_identified_races": fields["Self-Identified Race(s)"].strip(),
        "partner_races": fields["Partner Race(s)"].strip(),
        "availability": fields["Availability"].strip(),
        "city": "",  # emails don't include city by spec
        "consent": fields["Consent"].strip(),
        "message": fields["Message"].strip() if fields["Message"].strip() else "",
        "thread_subject": subject,
        "body": body,
        "source": "email",
    }
    return record


def parse_emails(dir_path: Path):
    if not dir_path.exists():
        return []
    records = []
    try:
        for p in sorted(dir_path.glob("*.eml")):
            rec = parse_eml_file(p)
            if rec:
                records.append(rec)
    except Exception:
        return []
    return records


def compute_expected(workspace: Path):
    # Parse inputs
    form_path = workspace / "input" / "signups.html"
    inbox_dir = workspace / "input" / "inbox"
    form_records = parse_form_signups(form_path)
    email_records = parse_emails(inbox_dir)

    # Counts
    total_form = len(form_records)
    total_emails_parsed = len(email_records)

    # Consent filtering (case-insensitive "yes")
    def is_yes(v: str):
        return isinstance(v, str) and v.strip().lower() == "yes"

    consenting_form = [r for r in form_records if is_yes(r.get("consent", ""))]
    consenting_email = [r for r in email_records if is_yes(r.get("consent", ""))]

    number_consenting = len(consenting_form) + len(consenting_email)

    # Missing race exclusions among consenting (self or partner empty after stripping)
    def has_both_races(r):
        return bool(r.get("self_identified_races", "").strip()) and bool(r.get("partner_races", "").strip())

    missing_race_exclusions = 0
    for r in consenting_form:
        if not has_both_races(r):
            missing_race_exclusions += 1
    for r in consenting_email:
        if not has_both_races(r):
            missing_race_exclusions += 1

    # Merge by email lowercase
    merged = {}
    sources = {}
    for r in consenting_form:
        if not has_both_races(r):
            continue
        key = normalize_email(r.get("email", ""))
        if not key:
            continue
        # Prepare normalized fields
        merged[key] = {
            "full_name": r.get("full_name", "").strip(),
            "email": r.get("email", "").strip(),
            "self_identified_races": normalize_races(r.get("self_identified_races", "")),
            "partner_races": normalize_races(r.get("partner_races", "")),
            "availability": r.get("availability", "").strip(),
            "city": r.get("city", "").strip(),
            "consent": r.get("consent", "").strip(),
            "thread_subject": "",
            "message_form": r.get("message", "").strip(),
            "message_email": None,
            "source": "form",
        }
        sources[key] = {"form": True, "email": False}
    for r in consenting_email:
        if not has_both_races(r):
            continue
        key = normalize_email(r.get("email", ""))
        if not key:
            continue
        if key in merged:
            # Update merged to reflect both sources
            merged[key]["source"] = "both"
            merged[key]["thread_subject"] = r.get("thread_subject", "").strip()
            merged[key]["message_email"] = r.get("message", "").strip() if r.get("message", "").strip() else ""
            # Prefer form demographics and availability if present; city already from form
            # Keep name from whichever present; default to existing
            if not merged[key].get("full_name"):
                merged[key]["full_name"] = r.get("full_name", "").strip()
        else:
            merged[key] = {
                "full_name": r.get("full_name", "").strip(),
                "email": r.get("email", "").strip(),
                "self_identified_races": normalize_races(r.get("self_identified_races", "")),
                "partner_races": normalize_races(r.get("partner_races", "")),
                "availability": r.get("availability", "").strip(),
                "city": "",
                "consent": r.get("consent", "").strip(),
                "thread_subject": r.get("thread_subject", "").strip(),
                "message_form": None,
                "message_email": r.get("message", "").strip() if r.get("message", "").strip() else "",
                "source": "email",
            }
        src = sources.get(key, {"form": False, "email": False})
        src["email"] = True
        sources[key] = src

    # Update 'source' field from recorded sources flags
    for k, flags in sources.items():
        if k in merged:
            if flags["form"] and flags["email"]:
                merged[k]["source"] = "both"
            elif flags["form"]:
                merged[k]["source"] = "form"
            elif flags["email"]:
                merged[k]["source"] = "email"

    # Build expected order list
    included_emails_sorted = sorted(list(merged.keys()))
    number_after_dedup = len(included_emails_sorted)

    # For message_preview expectations:
    # For form-only: use form message truncated to 60 chars
    # For email-only: use "Message:" content if present else first 60 non-whitespace chars of body
    # For both: ambiguous; accept either form or email approach. We'll compute both.
    expected_records = {}
    # Also need email subjects available for records (for email or both)
    # We already stored thread_subject in merged map.
    # For email-only and both: we may need to compute email-derived preview when message field absent: In inputs provided, all have "Message:" line; ok.

    # Build a helper to compute email message preview if message line missing
    def compute_email_preview(record_email: dict, raw_email_records: list) -> str:
        # Find matching raw email record by email address
        for reml in raw_email_records:
            if normalize_email(reml.get("email", "")) == normalize_email(record_email.get("email", "")):
                # Use message field if present
                msg_val = reml.get("message", "").strip()
                if msg_val:
                    preview = msg_val[:60]
                    return preview
                # Fallback: first 60 non-whitespace characters of body
                body = reml.get("body", "")
                # Remove whitespace characters when counting
                non_ws_chars = "".join(ch for ch in body if not ch.isspace())
                return non_ws_chars[:60]
        return ""

    # Build expected for each merged record
    for email_key in included_emails_sorted:
        rec = merged[email_key]
        source = rec["source"]
        # Compute previews
        form_preview = None
        email_preview = None
        if rec.get("message_form") is not None:
            form_preview = rec.get("message_form", "")
            form_preview = form_preview[:60]
        email_preview = compute_email_preview(rec, email_records)
        # Store expected
        expected_records[email_key] = {
            "full_name": rec.get("full_name", ""),
            "email": rec.get("email", ""),
            "self_identified_races": rec.get("self_identified_races", ""),
            "partner_races": rec.get("partner_races", ""),
            "availability": rec.get("availability", ""),
            "city": rec.get("city", ""),
            "consent": rec.get("consent", ""),
            "source": source,
            "thread_subject": rec.get("thread_subject", "") if source in ("email", "both") else "",
            "acceptable_message_previews": [p for p in [form_preview, email_preview] if p is not None],
        }

    return {
        "form_records": form_records,
        "email_records": email_records,
        "expected_records": expected_records,
        "included_emails_sorted": included_emails_sorted,
        "counts": {
            "total_form": total_form,
            "total_emails_parsed": total_emails_parsed,
            "number_consenting": number_consenting,
            "missing_race_exclusions": missing_race_exclusions,
            "number_after_dedup": number_after_dedup,
        },
    }


def parse_sentence_count(text: str) -> int:
    # Count sentences by splitting on ., !, ?; tolerate newlines as sentence ends if punctuation missing
    body = text.strip()
    # Remove the headers if present (handled by caller usually)
    # Split on punctuation
    candidates = re.split(r"[.!?]+(?:\s+|$)", body)
    parts = [p for p in candidates if p.strip()]
    if parts:
        return len(parts)
    # Fallback to lines
    lines = [l for l in body.splitlines() if l.strip()]
    return len(lines)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "merged_csv_exists_with_header": 0.0,
        "merged_csv_records_correct": 0.0,
        "followups_present_and_headers": 0.0,
        "followups_body_references_and_sentences": 0.0,
        "summary_counts_correct": 0.0,
    }

    # Check script exists
    script_path = workspace / "scripts" / "merge_contacts.py"
    if script_path.exists() and script_path.is_file():
        try:
            content = script_path.read_text(encoding="utf-8", errors="ignore")
            if content.strip():
                scores["script_exists"] = 1.0
        except Exception:
            scores["script_exists"] = 0.0

    # Compute expected from inputs
    expected_bundle = compute_expected(workspace)
    expected_records = expected_bundle.get("expected_records", {})
    included_emails_sorted = expected_bundle.get("included_emails_sorted", [])
    expected_counts = expected_bundle.get("counts", {})

    # Check merged_contacts.csv
    csv_path = workspace / "output" / "merged_contacts.csv"
    headers, rows = load_csv_rows(csv_path)
    expected_header = [
        "full_name",
        "email",
        "self_identified_races",
        "partner_races",
        "availability",
        "city",
        "consent",
        "source",
        "thread_subject",
        "message_preview",
    ]
    if headers == expected_header:
        scores["merged_csv_exists_with_header"] = 1.0
    else:
        scores["merged_csv_exists_with_header"] = 0.0

    # Validate CSV content strictly
    csv_ok = False
    if headers is not None and rows is not None and headers == expected_header:
        try:
            # Build actual map by email lower-case
            actual_map = {}
            for r in rows:
                email_val = r.get("email", "").strip()
                if email_val:
                    actual_map[normalize_email(email_val)] = r
            # Check set of emails equals expected set
            if set(actual_map.keys()) == set(included_emails_sorted) and len(rows) == len(included_emails_sorted):
                all_match = True
                for email_key in included_emails_sorted:
                    ar = actual_map[email_key]
                    er = expected_records.get(email_key, {})
                    # Check fields
                    # full_name exact
                    if ar.get("full_name", "").strip() != er.get("full_name", "").strip():
                        all_match = False
                        break
                    # email exact
                    if ar.get("email", "").strip() != er.get("email", "").strip():
                        all_match = False
                        break
                    # races normalized exact
                    if ar.get("self_identified_races", "").strip() != er.get("self_identified_races", "").strip():
                        all_match = False
                        break
                    if ar.get("partner_races", "").strip() != er.get("partner_races", "").strip():
                        all_match = False
                        break
                    # availability exact
                    if ar.get("availability", "").strip() != er.get("availability", "").strip():
                        all_match = False
                        break
                    # city exact
                    if ar.get("city", "").strip() != er.get("city", "").strip():
                        all_match = False
                        break
                    # consent must be "yes" case-insensitive
                    if ar.get("consent", "").strip().lower() != "yes":
                        all_match = False
                        break
                    # source exact
                    if ar.get("source", "").strip() != er.get("source", "").strip():
                        all_match = False
                        break
                    # thread_subject
                    if er.get("source") in ("email", "both"):
                        if ar.get("thread_subject", "").strip() != er.get("thread_subject", "").strip():
                            all_match = False
                            break
                    else:
                        if ar.get("thread_subject", "").strip() != "":
                            all_match = False
                            break
                    # message_preview: accept either form or email-derived preview if both sources
                    acceptable_previews = er.get("acceptable_message_previews", [])
                    actual_preview = ar.get("message_preview", "")
                    # For "form" only or "email" only, acceptable_previews should include exactly one appropriate preview
                    # We accept if actual equals any acceptable preview
                    if actual_preview not in acceptable_previews:
                        all_match = False
                        break
                if all_match:
                    csv_ok = True
        except Exception:
            csv_ok = False
    scores["merged_csv_records_correct"] = 1.0 if csv_ok else 0.0

    # Validate followups files and headers
    followups_dir = workspace / "output" / "followups"
    followups_ok_headers = False
    followups_ok_body = False
    if followups_dir.exists() and followups_dir.is_dir():
        try:
            header_checks = []
            body_checks = []
            for email_key in included_emails_sorted:
                er = expected_records[email_key]
                local_part = er["email"].split("@")[0]
                fpath = followups_dir / f"{local_part}.txt"
                if not fpath.exists():
                    header_checks.append(False)
                    body_checks.append(False)
                    continue
                content = read_text(fpath)
                if not content:
                    header_checks.append(False)
                    body_checks.append(False)
                    continue
                lines = content.splitlines()
                # Need at least two lines
                if len(lines) < 2:
                    header_checks.append(False)
                    body_checks.append(False)
                    continue
                # Exact header line checks
                line1_expected = f"To: {er['email']}"
                line2_expected = f"Subject: Interview Scheduling – {er['full_name']}"
                header_pass = (lines[0].strip() == line1_expected and lines[1].strip() == line2_expected)
                header_checks.append(header_pass)
                # Body checks: references to races and availability, 2–4 short sentences
                body_text = "\n".join(lines[2:]).strip()
                # Must reference self races terms (split into items)
                self_items = split_races(er["self_identified_races"])
                partner_items = split_races(er["partner_races"])
                availability = er["availability"]
                def contains_all(items, text):
                    t = text.lower()
                    return all(it.lower() in t for it in items)
                # Ensure all partner items present; self at least one item present (all ideally)
                ref_pass = contains_all(self_items, body_text) and contains_all(partner_items, body_text) and (availability.lower() in body_text.lower())
                # Sentence count
                sent_count = parse_sentence_count(body_text)
                sentence_pass = 2 <= sent_count <= 4
                body_checks.append(ref_pass and sentence_pass)
            followups_ok_headers = all(header_checks) if header_checks else False
            followups_ok_body = all(body_checks) if body_checks else False
        except Exception:
            followups_ok_headers = False
            followups_ok_body = False
    scores["followups_present_and_headers"] = 1.0 if followups_ok_headers else 0.0
    scores["followups_body_references_and_sentences"] = 1.0 if followups_ok_body else 0.0

    # Validate summary.txt
    summary_ok = False
    summary_path = workspace / "output" / "summary.txt"
    if summary_path.exists() and summary_path.is_file():
        try:
            stext = read_text(summary_path)
            lines = [ln for ln in stext.splitlines()]
            # Need at least 5 lines for counts
            if len(lines) >= 5:
                # Extract first integer from each of first 5 lines
                def first_int(line):
                    m = re.search(r"-?\d+", line)
                    return int(m.group(0)) if m else None
                a = first_int(lines[0])
                b = first_int(lines[1])
                c = first_int(lines[2])
                d = first_int(lines[3])
                e = first_int(lines[4])
                counts_match = (
                    a == expected_counts.get("total_form") and
                    b == expected_counts.get("total_emails_parsed") and
                    c == expected_counts.get("number_consenting") and
                    d == expected_counts.get("missing_race_exclusions") and
                    e == expected_counts.get("number_after_dedup")
                )
                # Next lines should be included emails sorted alphabetically
                listed_emails = [ln.strip() for ln in lines[5:] if ln.strip()]
                emails_match = listed_emails == expected_bundle.get("included_emails_sorted", [])
                summary_ok = counts_match and emails_match
        except Exception:
            summary_ok = False
    scores["summary_counts_correct"] = 1.0 if summary_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    write_json_stdout(result)


if __name__ == "__main__":
    main()