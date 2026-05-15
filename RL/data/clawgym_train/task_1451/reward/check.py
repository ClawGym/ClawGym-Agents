import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _load_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (len(s) >= 2) and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _parse_bool(s: str) -> Optional[bool]:
    s = s.strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    return None


def _parse_int(s: str) -> Optional[int]:
    s = s.strip()
    try:
        return int(s)
    except Exception:
        return None


def _extract_section(text: str, section: str) -> Optional[str]:
    pattern = rf'^{re.escape(section)}:\s*\n(.*?)(?=^\w+:\s*\n|\Z)'
    m = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if not m:
        return None
    return m.group(1)


def _parse_list_from_block(block: str, key: str) -> Optional[List[str]]:
    pattern = rf'^\s*{re.escape(key)}:\s*\n((?:\s*-\s*.*\n)+)'
    m = re.search(pattern, block, flags=re.MULTILINE)
    if not m:
        return None
    list_block = m.group(1)
    items = re.findall(r'^\s*-\s*(.*)\s*$', list_block, flags=re.MULTILINE)
    return [_strip_quotes(it) for it in items]


def _parse_scalar_from_block(block: str, key: str) -> Optional[Any]:
    pattern = rf'^\s*{re.escape(key)}:\s*(.+)\s*$'
    matches = re.findall(pattern, block, flags=re.MULTILINE)
    if not matches:
        return None
    raw = matches[-1].strip()
    b = _parse_bool(raw)
    if b is not None:
        return b
    n = _parse_int(raw)
    if n is not None:
        return n
    return _strip_quotes(raw)


def _load_rules_yaml(path: Path) -> Optional[dict]:
    text = _read_text_safe(path)
    if text is None:
        return None
    rules: Dict[str, Any] = {}

    pitch_block = _extract_section(text, "pitch_rules")
    email_block = _extract_section(text, "email_rules")
    if pitch_block is None or email_block is None:
        return None

    pitch_rules: Dict[str, Any] = {}
    email_rules: Dict[str, Any] = {}

    rk = _parse_list_from_block(pitch_block, "required_keywords")
    if rk is None:
        return None
    pitch_rules["required_keywords"] = rk

    bw = _parse_list_from_block(pitch_block, "banned_words")
    if bw is None:
        return None
    pitch_rules["banned_words"] = bw

    mwc = _parse_scalar_from_block(pitch_block, "max_word_count")
    pae = _parse_scalar_from_block(pitch_block, "preserve_at_least_one_number_from_original")
    mex = _parse_scalar_from_block(pitch_block, "max_exclamations")
    if not isinstance(mwc, int) or not isinstance(pae, bool) or not isinstance(mex, int):
        return None
    pitch_rules["max_word_count"] = mwc
    pitch_rules["preserve_at_least_one_number_from_original"] = pae
    pitch_rules["max_exclamations"] = mex

    rka = _parse_list_from_block(email_block, "required_keywords_any")
    if rka is None:
        return None
    email_rules["required_keywords_any"] = rka

    ebw = _parse_list_from_block(email_block, "banned_words")
    if ebw is None:
        return None
    email_rules["banned_words"] = ebw

    irn = _parse_scalar_from_block(email_block, "include_recipient_name")
    ine = _parse_scalar_from_block(email_block, "include_neighborhood")
    smt = _parse_scalar_from_block(email_block, "subject_must_contain_topic_hint")
    smc = _parse_scalar_from_block(email_block, "subject_max_chars")
    mbw = _parse_scalar_from_block(email_block, "max_body_words")
    mex2 = _parse_scalar_from_block(email_block, "max_exclamations")

    if not isinstance(irn, bool) or not isinstance(ine, str) or not isinstance(smt, bool):
        return None
    if not isinstance(smc, int) or not isinstance(mbw, int) or not isinstance(mex2, int):
        return None

    email_rules["include_recipient_name"] = irn
    email_rules["include_neighborhood"] = ine
    email_rules["subject_must_contain_topic_hint"] = smt
    email_rules["subject_max_chars"] = smc
    email_rules["max_body_words"] = mbw
    email_rules["max_exclamations"] = mex2

    rules["pitch_rules"] = pitch_rules
    rules["email_rules"] = email_rules
    return rules


def _count_words(text: str) -> int:
    if not text:
        return 0
    tokens = re.findall(r'\b\w+\b', text, flags=re.UNICODE)
    return len(tokens)


def _count_exclamations(text: str) -> int:
    return text.count("!")


def _extract_numbers(text: str) -> List[str]:
    if not text:
        return []
    nums = re.findall(r'\d+', text)
    seen = set()
    res = []
    for n in nums:
        if n not in seen:
            seen.add(n)
            res.append(n)
    return res


def _contains_substring(text: str, phrase: str) -> bool:
    return phrase.lower() in text.lower()


def _contains_required_keywords(text: str, required_keywords: List[str]) -> Dict[str, bool]:
    res = {}
    lower_text = text.lower()
    for kw in required_keywords:
        res[kw] = (kw.lower() in lower_text)
    return res


def _find_banned_words(text: str, banned_words: List[str]) -> List[str]:
    found = set()
    lower_text = text.lower()
    if not banned_words:
        return []
    pattern = r'\b(' + '|'.join(re.escape(w.lower()) for w in banned_words) + r')\b'
    for m in re.finditer(pattern, lower_text, flags=re.IGNORECASE):
        found.add(m.group(1).lower())
    return sorted(found)


def _compute_pitch_metrics(rewrite_text: str, draft_text: str, pitch_rules: dict) -> Dict[str, Any]:
    word_count = _count_words(rewrite_text)
    exclamations = _count_exclamations(rewrite_text)
    required_map = _contains_required_keywords(rewrite_text, pitch_rules.get("required_keywords", []))
    banned_found = _find_banned_words(rewrite_text, pitch_rules.get("banned_words", []))
    includes_neighborhood = _contains_substring(rewrite_text, "South River Ward")
    original_numbers = _extract_numbers(draft_text)
    rewrite_numbers = _extract_numbers(rewrite_text)
    preserved = sorted(set(original_numbers).intersection(rewrite_numbers), key=lambda x: (original_numbers.index(x) if x in original_numbers else 0, x))

    pass_required = all(required_map.values()) if pitch_rules.get("required_keywords") else True
    pass_banned = len(banned_found) == 0
    pass_excl = exclamations <= pitch_rules.get("max_exclamations", 0)
    pass_words = word_count <= pitch_rules.get("max_word_count", 0)
    pass_numbers = (len(preserved) >= 1) if pitch_rules.get("preserve_at_least_one_number_from_original", False) else True
    passed = pass_required and pass_banned and pass_excl and pass_words and includes_neighborhood and pass_numbers

    return {
        "word_count": word_count,
        "exclamation_count": exclamations,
        "contains_required_keywords": required_map,
        "contains_banned_words": banned_found,
        "preserved_numbers": preserved,
        "includes_neighborhood": includes_neighborhood,
        "passed": passed,
    }


def _compute_email_row_metrics(row: Dict[str, str], contact: Dict[str, str], email_rules: dict) -> Dict[str, Any]:
    name = (row.get("name") or "").strip()
    outlet = (row.get("outlet") or "").strip()
    subject = (row.get("subject") or "")
    body = (row.get("body") or "")

    expected_topic_hint = (contact.get("topic_hint") or "")
    expected_outlet = (contact.get("outlet") or "")

    subject_length = len(subject)
    body_wc = _count_words(body)
    exclamations_body = _count_exclamations(body)
    includes_name = _contains_substring(body, name) if email_rules.get("include_recipient_name", True) else True
    includes_neighborhood = _contains_substring(body, email_rules.get("include_neighborhood", ""))
    required_any_list = email_rules.get("required_keywords_any", [])
    contains_any = any(_contains_substring(body, kw) for kw in required_any_list) if required_any_list else True
    banned_found = _find_banned_words(body, email_rules.get("banned_words", []))
    subject_contains_hint = _contains_substring(subject, expected_topic_hint) if email_rules.get("subject_must_contain_topic_hint", True) else True
    subject_len_ok = subject_length <= email_rules.get("subject_max_chars", 0)
    body_wc_ok = body_wc <= email_rules.get("max_body_words", 0)
    exclam_ok = exclamations_body <= email_rules.get("max_exclamations", 0)

    passed = (
        subject_len_ok
        and subject_contains_hint
        and includes_name
        and includes_neighborhood
        and contains_any
        and len(banned_found) == 0
        and exclam_ok
        and body_wc_ok
    )

    return {
        "recipient": name,
        "subject_length": subject_length,
        "exclamation_count": exclamations_body,
        "contains_required_keywords_any": contains_any,
        "contains_banned_words": banned_found,
        "includes_recipient_name": includes_name,
        "includes_neighborhood": includes_neighborhood,
        "subject_contains_topic_hint": subject_contains_hint,
        "body_word_count": body_wc,
        "passed": passed,
        "outlet_matches_contact": outlet.lower() == expected_outlet.lower(),
    }


def _compute_emails_metrics(emails_rows: List[Dict[str, str]], contacts: List[Dict[str, str]], email_rules: dict) -> Dict[str, Any]:
    contacts_by_name = { (c.get("name") or "").strip().lower(): c for c in contacts }
    results = []
    for row in emails_rows:
        name_key = (row.get("name") or "").strip().lower()
        contact = contacts_by_name.get(name_key)
        if contact is None:
            contact = {"name": row.get("name", ""), "outlet": row.get("outlet", ""), "topic_hint": ""}
        metrics = _compute_email_row_metrics(row, contact, email_rules)
        results.append(metrics)
    all_passed = all(m["passed"] for m in results) if results else False
    email_names = set((r.get("name") or "").strip().lower() for r in emails_rows)
    contact_names = set((c.get("name") or "").strip().lower() for c in contacts)
    structure_ok = (email_names == contact_names) and (len(emails_rows) == len(contacts))
    outlets_ok = all(m["outlet_matches_contact"] for m in results)
    return {"rows": results, "all_passed": all_passed, "structure_ok": structure_ok, "outlets_ok": outlets_ok}


def _load_contacts(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _load_csv_safe(path)
    if rows is None:
        return None
    required_cols = ["name", "outlet", "topic_hint"]
    fieldnames = None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            fieldnames = next(reader, None)
    except Exception:
        return None
    if fieldnames is None or [c.strip() for c in fieldnames] != required_cols:
        return None
    return rows


def _load_emails_with_header(path: Path) -> Tuple[Optional[List[Dict[str, str]]], bool]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            header_ok = header == ["name", "outlet", "subject", "body"]
    except Exception:
        return None, False
    rows = _load_csv_safe(path)
    return rows, bool(header_ok)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "pitch_file_present": 0.0,
        "pitch_rules_passed": 0.0,
        "emails_file_present": 0.0,
        "emails_header_correct": 0.0,
        "emails_structure_correct": 0.0,
        "emails_rules_passed_all": 0.0,
        "validation_report_present": 0.0,
        "validation_report_structure_valid": 0.0,
        "validation_report_matches_computed": 0.0,
        "all_success_criteria_met": 0.0,
    }

    rules_path = workspace / "input" / "tone_rules.yaml"
    draft_path = workspace / "input" / "pitch_draft.md"
    contacts_path = workspace / "input" / "contacts.csv"
    pitch_out_path = workspace / "output" / "pitch_rewrite.md"
    emails_out_path = workspace / "output" / "emails.csv"
    report_out_path = workspace / "output" / "validation_report.json"

    rules = _load_rules_yaml(rules_path)
    draft_text = _read_text_safe(draft_path) or ""

    pitch_text = _read_text_safe(pitch_out_path)
    if pitch_text is not None:
        scores["pitch_file_present"] = 1.0
    if pitch_text is not None and rules is not None and "pitch_rules" in rules and draft_text is not None:
        pitch_metrics = _compute_pitch_metrics(pitch_text, draft_text, rules["pitch_rules"])
        if pitch_metrics.get("passed", False):
            scores["pitch_rules_passed"] = 1.0

    emails_rows, header_ok = _load_emails_with_header(emails_out_path)
    if emails_rows is not None:
        scores["emails_file_present"] = 1.0
        scores["emails_header_correct"] = 1.0 if header_ok else 0.0
    contacts = _load_contacts(contacts_path)
    if emails_rows is not None and contacts is not None and rules is not None and "email_rules" in rules:
        emails_metrics = _compute_emails_metrics(emails_rows, contacts, rules["email_rules"])
        if emails_metrics.get("structure_ok", False):
            scores["emails_structure_correct"] = 1.0
        if emails_metrics.get("all_passed", False):
            scores["emails_rules_passed_all"] = 1.0

    report = _load_json_safe(report_out_path)
    if report is not None:
        scores["validation_report_present"] = 1.0

    if rules is not None and pitch_text is not None and emails_rows is not None and contacts is not None:
        expected_pitch = _compute_pitch_metrics(pitch_text, draft_text, rules["pitch_rules"])
        exp_emails = _compute_emails_metrics(emails_rows, contacts, rules["email_rules"])
        expected_report = {
            "pitch": {
                "word_count": expected_pitch["word_count"],
                "exclamation_count": expected_pitch["exclamation_count"],
                "contains_required_keywords": expected_pitch["contains_required_keywords"],
                "contains_banned_words": expected_pitch["contains_banned_words"],
                "preserved_numbers": expected_pitch["preserved_numbers"],
                "includes_neighborhood": expected_pitch["includes_neighborhood"],
                "passed": expected_pitch["passed"],
            },
            "emails": {
                "rows": [
                    {
                        "recipient": r["recipient"],
                        "subject_length": r["subject_length"],
                        "exclamation_count": r["exclamation_count"],
                        "contains_required_keywords_any": r["contains_required_keywords_any"],
                        "contains_banned_words": r["contains_banned_words"],
                        "includes_recipient_name": r["includes_recipient_name"],
                        "includes_neighborhood": r["includes_neighborhood"],
                        "subject_contains_topic_hint": r["subject_contains_topic_hint"],
                        "body_word_count": r["body_word_count"],
                        "passed": r["passed"],
                    }
                    for r in exp_emails["rows"]
                ],
                "all_passed": exp_emails["all_passed"],
            },
        }

        if report is not None:
            try:
                pitch_r = report.get("pitch", {})
                emails_r = report.get("emails", {})
                pitch_keys_ok = all(k in pitch_r for k in expected_report["pitch"].keys())
                email_rows = emails_r.get("rows", [])
                all_pass_flag_present = "all_passed" in emails_r
                structure_valid = isinstance(email_rows, list) and pitch_keys_ok and all_pass_flag_present
                scores["validation_report_structure_valid"] = 1.0 if structure_valid else 0.0

                def eq_banned_list(a: List[str], b: List[str]) -> bool:
                    try:
                        return set(a) == set(b)
                    except Exception:
                        return False

                def eq_preserved_numbers(a: List[str], b: List[str]) -> bool:
                    try:
                        return set(a) == set(b)
                    except Exception:
                        return False

                match_ok = True
                erp = expected_report["pitch"]
                match_ok &= (int(pitch_r.get("word_count", -1)) == erp["word_count"])
                match_ok &= (int(pitch_r.get("exclamation_count", -1)) == erp["exclamation_count"])
                crk_rep = pitch_r.get("contains_required_keywords", {})
                if isinstance(crk_rep, dict):
                    crk_rep_norm = {k: bool(v) for k, v in crk_rep.items()}
                else:
                    crk_rep_norm = {}
                match_ok &= (crk_rep_norm == erp["contains_required_keywords"])
                match_ok &= eq_banned_list(pitch_r.get("contains_banned_words", []), erp["contains_banned_words"])
                match_ok &= eq_preserved_numbers(pitch_r.get("preserved_numbers", []), erp["preserved_numbers"])
                match_ok &= (bool(pitch_r.get("includes_neighborhood", False)) == erp["includes_neighborhood"])
                match_ok &= (bool(pitch_r.get("passed", False)) == erp["passed"])

                expected_rows_by_recipient = {r["recipient"].lower(): r for r in expected_report["emails"]["rows"]}
                reported_rows_by_recipient = {}
                for r in email_rows:
                    rec = (r.get("recipient") or "").lower()
                    if rec:
                        reported_rows_by_recipient[rec] = r
                match_ok &= (set(expected_rows_by_recipient.keys()) == set(reported_rows_by_recipient.keys()))
                for rec, exp_row in expected_rows_by_recipient.items():
                    rep_row = reported_rows_by_recipient.get(rec, {})
                    match_ok &= (int(rep_row.get("subject_length", -1)) == exp_row["subject_length"])
                    match_ok &= (int(rep_row.get("exclamation_count", -1)) == exp_row["exclamation_count"])
                    match_ok &= (bool(rep_row.get("contains_required_keywords_any", False)) == exp_row["contains_required_keywords_any"])
                    match_ok &= eq_banned_list(rep_row.get("contains_banned_words", []), exp_row["contains_banned_words"])
                    match_ok &= (bool(rep_row.get("includes_recipient_name", False)) == exp_row["includes_recipient_name"])
                    match_ok &= (bool(rep_row.get("includes_neighborhood", False)) == exp_row["includes_neighborhood"])
                    match_ok &= (bool(rep_row.get("subject_contains_topic_hint", False)) == exp_row["subject_contains_topic_hint"])
                    match_ok &= (int(rep_row.get("body_word_count", -1)) == exp_row["body_word_count"])
                    match_ok &= (bool(rep_row.get("passed", False)) == exp_row["passed"])
                match_ok &= (bool(emails_r.get("all_passed", False)) == expected_report["emails"]["all_passed"])

                if match_ok:
                    scores["validation_report_matches_computed"] = 1.0
            except Exception:
                pass

    if (
        scores["pitch_rules_passed"] == 1.0
        and scores["emails_rules_passed_all"] == 1.0
        and scores["emails_structure_correct"] == 1.0
        and scores["validation_report_matches_computed"] == 1.0
    ):
        scores["all_success_criteria_met"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()