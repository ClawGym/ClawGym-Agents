import json
import csv
import re
import sys
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n")


def _safe_load_jsonl(path: Path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    objs = []
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            return None
        objs.append(obj)
    return objs


def _safe_read_csv(path: Path):
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


def _extract_field(lines, label):
    pattern = re.compile(r"^\s*" + re.escape(label) + r"\s*(.*)$", flags=re.IGNORECASE)
    for line in lines:
        m = pattern.match(line)
        if m:
            return m.group(1).strip()
    return None


def _normalize_inbox_record(source_file: str, text: str) -> dict:
    lines = _normalize_newlines(text or "").split("\n")
    name = _extract_field(lines, "Name:")
    email = _extract_field(lines, "Email:")
    phone = _extract_field(lines, "Phone:")
    loan_purpose = _extract_field(lines, "Loan purpose:")
    property_state = _extract_field(lines, "Property state:")
    credit_score = _extract_field(lines, "Estimated credit score:")
    loan_amount = _extract_field(lines, "Loan amount:")

    customer_name = name.strip() if name else ""
    email_norm = email.strip() if email else ""
    if phone:
        digits = re.sub(r"\D", "", phone)
        phone_norm = digits if digits else ""
    else:
        phone_norm = ""
    lp_norm = "Other"
    if loan_purpose:
        lp_val = loan_purpose.strip().lower()
        if lp_val == "purchase":
            lp_norm = "Purchase"
        elif lp_val == "refinance":
            lp_norm = "Refinance"
        elif lp_val == "heloc":
            lp_norm = "HELOC"
        else:
            lp_norm = "Other"
    else:
        lp_norm = "Other"
    if property_state:
        ps = property_state.strip().upper()
        if len(ps) == 2 and ps.isalpha():
            property_state_norm = ps
        else:
            letters = re.findall(r"[A-Za-z]", ps)
            if len(letters) >= 2:
                property_state_norm = (letters[0] + letters[1]).upper()
            else:
                property_state_norm = ""
    else:
        property_state_norm = ""
    if credit_score and credit_score.strip() and credit_score.strip().lower() != "unknown":
        credit_score_norm = credit_score.strip()
    else:
        credit_score_norm = ""
    if loan_amount and loan_amount.strip():
        digits = re.sub(r"[^\d]", "", loan_amount)
        loan_amount_norm = digits if digits else ""
    else:
        loan_amount_norm = ""

    fields_order = ["customer_name", "email", "phone", "loan_purpose", "property_state", "credit_score", "loan_amount"]
    values_map = {
        "customer_name": customer_name,
        "email": email_norm,
        "phone": phone_norm,
        "loan_purpose": lp_norm,
        "property_state": property_state_norm,
        "credit_score": credit_score_norm,
        "loan_amount": loan_amount_norm,
    }
    missing_list = [k for k in fields_order if not values_map[k]]
    missing_fields = ";".join(missing_list)

    record_csv = {
        "source_file": source_file,
        "customer_name": customer_name,
        "email": email_norm,
        "phone": phone_norm,
        "loan_purpose": lp_norm,
        "property_state": property_state_norm,
        "credit_score": credit_score_norm,
        "loan_amount": loan_amount_norm,
        "missing_fields": missing_fields,
    }
    if loan_amount_norm != "":
        loan_amount_json = int(loan_amount_norm)
    else:
        loan_amount_json = ""
    record_json = {
        "source_file": source_file,
        "customer_name": customer_name,
        "email": email_norm,
        "phone": phone_norm,
        "loan_purpose": lp_norm,
        "property_state": property_state_norm,
        "credit_score": credit_score_norm,
        "loan_amount": loan_amount_json,
        "missing_fields": missing_fields,
    }
    return {"csv": record_csv, "json": record_json}


def _rewrite_body_line(line: str) -> str:
    s = line
    s = re.sub(r"\bkindly note that\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bjust\b", "", s, flags=re.IGNORECASE)
    repls = [
        (r"\bpls\b", "please"),
        (r"\bASAP\b", "as soon as possible"),
        (r"\bthx\b", "thank you"),
        (r"\bbtw\b", "by the way"),
    ]
    for pattern, replacement in repls:
        s = re.sub(pattern, replacement, s, flags=re.IGNORECASE)
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s


def _rewrite_draft(text: str, signature: str) -> str:
    content = _normalize_newlines(text or "")
    lines = content.split("\n")
    out_lines = []
    body_lines = []
    if lines and lines[0].startswith("Subject:"):
        out_lines.append(lines[0])
        body_lines = lines[1:]
    else:
        body_lines = lines
    transformed = [_rewrite_body_line(ln) for ln in body_lines]
    max_words = 120
    word_count = 0
    limited_lines = []
    for ln in transformed:
        if ln == "":
            limited_lines.append(ln)
            continue
        words = re.findall(r"\S+", ln)
        if not words:
            limited_lines.append("")
            continue
        remaining = max_words - word_count
        if remaining <= 0:
            break
        if len(words) <= remaining:
            limited_lines.append(ln)
            word_count += len(words)
        else:
            kept = " ".join(words[:remaining])
            limited_lines.append(kept)
            word_count += remaining
            break
    if out_lines:
        final = "\n".join([out_lines[0]] + limited_lines)
    else:
        final = "\n".join(limited_lines)
    if not final.endswith(signature):
        final = final + "\n\n" + signature
    return final


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "applications_csv_header": 0.0,
        "applications_csv_row_count_and_sources": 0.0,
        "applications_csv_normalization_correct": 0.0,
        "applications_jsonl_count_and_structure": 0.0,
        "applications_csv_jsonl_consistency": 0.0,
        "rewritten_drafts_files_present": 0.0,
        "rewritten_drafts_content_correct": 0.0,
    }

    inbox_dir = workspace / "input" / "inbox"
    drafts_dir = workspace / "input" / "drafts"
    signature_path = workspace / "input" / "signature.txt"

    inbox_files = []
    if inbox_dir.exists() and inbox_dir.is_dir():
        inbox_files = sorted([p for p in inbox_dir.glob("*.txt") if p.is_file()], key=lambda p: p.name)

    drafts_files = []
    if drafts_dir.exists() and drafts_dir.is_dir():
        drafts_files = sorted([p for p in drafts_dir.glob("*.txt") if p.is_file()], key=lambda p: p.name)

    expected_records_csv = {}
    expected_records_json = {}
    for p in inbox_files:
        text = _read_text(p)
        recs = _normalize_inbox_record(p.name, text or "")
        expected_records_csv[p.name] = recs["csv"]
        expected_records_json[p.name] = recs["json"]

    csv_path = workspace / "outputs" / "applications.csv"
    header, rows = _safe_read_csv(csv_path)
    required_header = [
        "source_file",
        "customer_name",
        "email",
        "phone",
        "loan_purpose",
        "property_state",
        "credit_score",
        "loan_amount",
        "missing_fields",
    ]
    if header == required_header:
        scores["applications_csv_header"] = 1.0

    if header is not None and rows is not None:
        expected_sources = set([p.name for p in inbox_files])
        actual_sources = set()
        for row in rows:
            actual_sources.add(row.get("source_file", ""))
        if len(rows) == len(inbox_files) and actual_sources == expected_sources:
            scores["applications_csv_row_count_and_sources"] = 1.0

        norm_ok = True
        if expected_records_csv and rows is not None:
            expected_by_src = expected_records_csv
            for row in rows:
                src = row.get("source_file", "")
                if src not in expected_by_src:
                    norm_ok = False
                    break
                expected_row = expected_by_src[src]
                for k in required_header:
                    v = row.get(k, "")
                    ev = expected_row.get(k, "")
                    if v != ev:
                        norm_ok = False
                        break
                if not norm_ok:
                    break
        else:
            norm_ok = False
        if norm_ok:
            scores["applications_csv_normalization_correct"] = 1.0

    jsonl_path = workspace / "outputs" / "applications.jsonl"
    json_objs = _safe_load_jsonl(jsonl_path)
    json_ok = False
    if json_objs is not None:
        if len(json_objs) == len(inbox_files):
            structure_ok = True
            vals_ok = True
            json_by_src = {}
            for obj in json_objs:
                if set(obj.keys()) != set(required_header):
                    structure_ok = False
                    break
                if "source_file" not in obj:
                    structure_ok = False
                    break
                json_by_src[obj["source_file"]] = obj
            if structure_ok:
                for p in inbox_files:
                    src = p.name
                    if src not in json_by_src:
                        vals_ok = False
                        break
                    obj = json_by_src[src]
                    expected = expected_records_json.get(src, {})
                    for k in required_header:
                        if k == "loan_amount":
                            ev = expected.get(k)
                            ov = obj.get(k)
                            if ev == "":
                                if ov != "":
                                    vals_ok = False
                                    break
                            else:
                                if not isinstance(ov, int) or ov != ev:
                                    vals_ok = False
                                    break
                        else:
                            if obj.get(k, "") != expected.get(k, ""):
                                vals_ok = False
                                break
                    if not vals_ok:
                        break
            if structure_ok and vals_ok:
                json_ok = True
    if json_ok:
        scores["applications_jsonl_count_and_structure"] = 1.0

    if header is not None and rows is not None and json_objs is not None:
        try:
            csv_by_src = {r.get("source_file", ""): r for r in rows}
            json_by_src = {o.get("source_file", ""): o for o in json_objs}
            consistent = True
            if set(csv_by_src.keys()) != set(json_by_src.keys()):
                consistent = False
            else:
                for src in csv_by_src:
                    crow = csv_by_src[src]
                    jrow = json_by_src[src]
                    for k in required_header:
                        if k == "loan_amount":
                            cval = crow.get(k, "")
                            jval = jrow.get(k)
                            if cval == "":
                                if jval != "":
                                    consistent = False
                                    break
                            else:
                                try:
                                    if int(cval) != jval:
                                        consistent = False
                                        break
                                except Exception:
                                    consistent = False
                                    break
                        else:
                            if crow.get(k, "") != jrow.get(k, ""):
                                consistent = False
                                break
                    if not consistent:
                        break
            if consistent and len(rows) == len(json_objs):
                scores["applications_csv_jsonl_consistency"] = 1.0
        except Exception:
            pass

    outputs_rewritten_dir = workspace / "outputs" / "rewritten_drafts"
    files_present_ok = True
    if drafts_files:
        for p in drafts_files:
            out_p = outputs_rewritten_dir / p.name
            if not out_p.exists() or not out_p.is_file():
                files_present_ok = False
                break
    else:
        files_present_ok = False
    if files_present_ok:
        scores["rewritten_drafts_files_present"] = 1.0

    content_ok = True
    sig_text = _read_text(signature_path)
    if not sig_text:
        content_ok = False
    else:
        sig_text = _normalize_newlines(sig_text)
        for p in drafts_files:
            out_p = outputs_rewritten_dir / p.name
            out_text = _read_text(out_p)
            in_text = _read_text(p)
            if out_text is None or in_text is None:
                content_ok = False
                break
            expected = _rewrite_draft(in_text, sig_text)
            out_text_norm = _normalize_newlines(out_text)
            expected_norm = _normalize_newlines(expected)
            if out_text_norm != expected_norm:
                content_ok = False
                break
    if drafts_files and content_ok:
        scores["rewritten_drafts_content_correct"] = 1.0
    elif not drafts_files:
        scores["rewritten_drafts_content_correct"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()