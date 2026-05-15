import json
import hashlib
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _extract_input_names(html: str) -> List[str]:
    pattern = re.compile(r'<input\b[^>]*\bname\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
    names = pattern.findall(html)
    return names


def _extract_data_input_names(html: str) -> List[str]:
    inputs = []
    for m in re.finditer(r'<input\b[^>]*>', html, flags=re.IGNORECASE | re.DOTALL):
        tag = m.group(0)
        name_m = re.search(r'\bname\s*=\s*["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
        if not name_m:
            continue
        name = name_m.group(1)
        type_m = re.search(r'\btype\s*=\s*["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
        input_type = (type_m.group(1).lower() if type_m else "text")
        if input_type in ("checkbox", "radio"):
            continue
        inputs.append(name)
    return inputs


def _find_checkbox_states(html: str) -> List[Tuple[str, bool]]:
    # Returns list of (name, is_checked_by_default)
    results = []
    for m in re.finditer(r'<input\b[^>]*\btype\s*=\s*["\']checkbox["\'][^>]*>', html, flags=re.IGNORECASE | re.DOTALL):
        tag = m.group(0)
        name_m = re.search(r'\bname\s*=\s*["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
        name = name_m.group(1) if name_m else ""
        checked = bool(re.search(r'\bchecked\b', tag, flags=re.IGNORECASE))
        results.append((name, checked))
    return results


def _snippet(text: str, start: int, end: int, window: int = 40) -> str:
    s = max(0, start - window)
    e = min(len(text), end + window)
    return text[s:e].strip()


def _compute_must_include_from_form(html: str) -> Tuple[Dict[str, bool], Dict[str, Optional[str]]]:
    text = html
    lower = text.lower()

    found: Dict[str, bool] = {}
    evidence: Dict[str, Optional[str]] = {}

    # cancellation_policy_statement
    m = re.search(r'cancellation', lower)
    found_key = "cancellation_policy_statement"
    if m:
        found[found_key] = True
        evidence[found_key] = _snippet(text, m.start(), m.end())
    else:
        found[found_key] = False
        evidence[found_key] = None

    # accessibility_notice
    k = "accessibility_notice"
    m = re.search(r'accessibility', lower)
    if m:
        found[k] = True
        evidence[k] = _snippet(text, m.start(), m.end())
    else:
        found[k] = False
        evidence[k] = None

    # privacy_notice_link: a link labeled "Privacy Notice"
    k = "privacy_notice_link"
    m = re.search(r'<a\b[^>]*>([^<]*privacy notice[^<]*)</a>', lower)
    if m:
        found[k] = True
        m2 = re.search(r'<a\b[^>]*>([^<]*Privacy Notice[^<]*)</a>', text, flags=re.IGNORECASE)
        if m2:
            evidence[k] = _snippet(text, m2.start(), m2.end())
        else:
            evidence[k] = "Privacy Notice link"
    else:
        found[k] = False
        evidence[k] = None

    # do_not_sell_or_share_statement
    k = "do_not_sell_or_share_statement"
    m = re.search(r'do not sell or share', lower)
    if m:
        found[k] = True
        evidence[k] = _snippet(text, m.start(), m.end())
    else:
        found[k] = False
        evidence[k] = None

    # email_consent_checkbox_unchecked_by_default
    k = "email_consent_checkbox_unchecked_by_default"
    checkboxes = _find_checkbox_states(text)
    any_unchecked = any(not checked for _, checked in checkboxes)
    if any_unchecked:
        match_consent = False
        for mtag in re.finditer(r'<label[^>]*>.*?<input\b[^>]*\btype\s*=\s*["\']checkbox["\'][^>]*>.*?</label>|<input\b[^>]*\btype\s*=\s*["\']checkbox["\'][^>]*>.*?(</label>|</p>|<br/?>)', text, flags=re.IGNORECASE | re.DOTALL):
            segment = mtag.group(0)
            if re.search(r'consent|update', segment, flags=re.IGNORECASE) and not re.search(r'\bchecked\b', segment, flags=re.IGNORECASE):
                match_consent = True
                evidence[k] = segment.strip()[:200]
                break
        found[k] = match_consent
        if not match_consent:
            evidence[k] = None
    else:
        found[k] = False
        evidence[k] = None

    # opt_out_instruction: "You can unsubscribe at any time."
    k = "opt_out_instruction"
    m = re.search(r'unsubscribe', lower)
    if m:
        found[k] = True
        evidence[k] = _snippet(text, m.start(), m.end())
    else:
        found[k] = False
        evidence[k] = None

    # data_retention_limit_30_days
    k = "data_retention_limit_30_days"
    m = re.search(r'30\s*days', lower)
    if m and re.search(r'(delete|retain|keep|retention)', lower):
        found[k] = True
        ctx_start = m.start()
        evidence[k] = _snippet(text, ctx_start, ctx_start + 8)
    else:
        found[k] = False
        evidence[k] = None

    return found, evidence


def _expected_policy_requirements() -> Dict[str, Any]:
    return {
        "from_files": ["input/policies/room_use_policy.html", "input/policies/privacy_notice.md"],
        "requirements": {
            "allowed_fields": ["name", "email"],
            "disallowed_fields": ["phone"],
            "must_include": [
                "cancellation_policy_statement",
                "accessibility_notice",
                "privacy_notice_link",
                "do_not_sell_or_share_statement",
                "email_consent_checkbox_unchecked_by_default",
                "opt_out_instruction",
                "data_retention_limit_30_days",
            ],
        },
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "policy_requirements_file_exists_and_valid_json": 0.0,
        "policy_requirements_from_files_correct": 0.0,
        "policy_requirements_content_lists_correct": 0.0,
        "validator_script_exists": 0.0,
        "run_log_command_recorded_correctly": 0.0,
        "compliance_report_file_exists_and_valid_json": 0.0,
        "compliance_report_checked_form_correct": 0.0,
        "compliance_report_requirements_fingerprint_correct": 0.0,
        "compliance_report_found_bools_correct": 0.0,
        "compliance_report_fields_form_field_names_correct": 0.0,
        "compliance_report_disallowed_fields_found_correct": 0.0,
        "compliance_report_unexpected_fields_present_correct": 0.0,
        "compliance_report_status_correct": 0.0,
        "compliance_report_evidence_present_and_consistent": 0.0,
        "email_to_guru_file_exists": 0.0,
        "email_word_limit_and_friendly_opening": 0.0,
        "email_has_positive_summary": 0.0,
        "email_lists_missing_items_with_fix_suggestions": 0.0,
        "email_avoids_legal_jargon": 0.0,
    }

    # Paths
    req_json_path = workspace / "output" / "policy_requirements.json"
    validator_script_path = workspace / "scripts" / "validate_form.py"
    run_log_path = workspace / "output" / "run_log.txt"
    compliance_report_path = workspace / "output" / "compliance_report.json"
    signup_form_path = workspace / "input" / "site" / "signup_form.html"
    email_out_path = workspace / "output" / "email_to_guru.txt"

    # 1) policy_requirements.json checks
    expected_requirements = _expected_policy_requirements()
    req_json = _load_json_safe(req_json_path)
    if isinstance(req_json, dict):
        scores["policy_requirements_file_exists_and_valid_json"] = 1.0
        if req_json.get("from_files") == expected_requirements["from_files"]:
            scores["policy_requirements_from_files_correct"] = 1.0
        reqs = req_json.get("requirements")
        if isinstance(reqs, dict):
            allowed = reqs.get("allowed_fields")
            disallowed = reqs.get("disallowed_fields")
            must_inc = reqs.get("must_include")
            if (
                allowed == expected_requirements["requirements"]["allowed_fields"]
                and disallowed == expected_requirements["requirements"]["disallowed_fields"]
                and must_inc == expected_requirements["requirements"]["must_include"]
            ):
                scores["policy_requirements_content_lists_correct"] = 1.0

    # 2) validator script and run log
    if validator_script_path.exists() and validator_script_path.is_file():
        scores["validator_script_exists"] = 1.0

    run_log_text = _read_text_safe(run_log_path)
    required_cmd = "python3 scripts/validate_form.py --requirements output/policy_requirements.json --form input/site/signup_form.html --out output/compliance_report.json"
    if run_log_text is not None:
        first_line = None
        for line in run_log_text.splitlines():
            if line.strip():
                first_line = line.strip()
                break
        if first_line == required_cmd:
            scores["run_log_command_recorded_correctly"] = 1.0

    # 2) compliance report checks
    report = _load_json_safe(compliance_report_path)
    signup_html = _read_text_safe(signup_form_path) or ""
    if isinstance(report, dict):
        scores["compliance_report_file_exists_and_valid_json"] = 1.0

        # checked_form
        if report.get("checked_form") == "input/site/signup_form.html":
            scores["compliance_report_checked_form_correct"] = 1.0

        # requirements fingerprint
        actual_fingerprint = _sha256_file(req_json_path)
        rep_fpr = report.get("requirements_fingerprint")
        if actual_fingerprint is not None and isinstance(rep_fpr, str) and rep_fpr == actual_fingerprint:
            scores["compliance_report_requirements_fingerprint_correct"] = 1.0

        # recompute expected found and evidence from the form
        expected_found, recomputed_evidence = _compute_must_include_from_form(signup_html)

        # found booleans match
        rep_found = report.get("found")
        if isinstance(rep_found, dict):
            keys_expected = set(expected_requirements["requirements"]["must_include"])
            keys_report = set(rep_found.keys())
            if keys_expected == keys_report:
                ok = True
                for k in keys_expected:
                    if not isinstance(rep_found.get(k), bool):
                        ok = False
                        break
                    if rep_found.get(k) != expected_found.get(k):
                        ok = False
                        break
                if ok:
                    scores["compliance_report_found_bools_correct"] = 1.0

        # fields.form_field_names and unexpected/disallowed
        rep_fields = report.get("fields")
        if isinstance(rep_fields, dict):
            # form_field_names must list input name attributes found
            rep_names = rep_fields.get("form_field_names")
            if isinstance(rep_names, list) and all(isinstance(x, str) for x in rep_names):
                true_names = _extract_input_names(signup_html)
                if set(rep_names) == set(true_names) and len(rep_names) == len(true_names):
                    scores["compliance_report_fields_form_field_names_correct"] = 1.0

            # disallowed_fields_found
            rep_disallowed = rep_fields.get("disallowed_fields_found")
            if isinstance(rep_disallowed, list) and all(isinstance(x, str) for x in rep_disallowed):
                disallowed = []
                if re.search(r'<input\b[^>]*\bname\s*=\s*["\']phone["\']', signup_html, flags=re.IGNORECASE):
                    disallowed.append("phone")
                if set(rep_disallowed) == set(disallowed) and len(rep_disallowed) == len(disallowed):
                    scores["compliance_report_disallowed_fields_found_correct"] = 1.0

            # unexpected_fields_present: items not allowed by policies
            rep_unexpected = rep_fields.get("unexpected_fields_present")
            if isinstance(rep_unexpected, list) and all(isinstance(x, str) for x in rep_unexpected):
                allowed_fields = expected_requirements["requirements"]["allowed_fields"]
                data_names = _extract_data_input_names(signup_html)
                unexpected = [n for n in data_names if n not in allowed_fields]
                if set(rep_unexpected) == set(unexpected) and len(rep_unexpected) == len(unexpected):
                    scores["compliance_report_unexpected_fields_present_correct"] = 1.0

        # status: compliant only if no must_include missing and no disallowed fields present in the form
        any_missing_required = not all(expected_found.values())
        disallowed_present = bool(re.search(r'<input\b[^>]*\bname\s*=\s*["\']phone["\']', signup_html, flags=re.IGNORECASE))
        expected_status = "compliant"
        if any_missing_required or disallowed_present:
            expected_status = "non_compliant"
        if report.get("status") == expected_status:
            scores["compliance_report_status_correct"] = 1.0

        # evidence
        rep_evidence = report.get("evidence")
        if isinstance(rep_evidence, dict):
            ok = True
            for k in expected_requirements["requirements"]["must_include"]:
                if k not in rep_evidence:
                    ok = False
                    break
                val = rep_evidence.get(k)
                if expected_found.get(k) is True:
                    if not isinstance(val, str) or not val.strip():
                        ok = False
                        break
                    # Relaxed containment: ensure at least one token from evidence appears in HTML or raw contains val
                    if val not in signup_html:
                        tokens = [t for t in re.split(r'\s+', val.strip()) if t]
                        if not any(t in signup_html for t in tokens):
                            ok = False
                            break
                else:
                    if val is not None:
                        ok = False
                        break
            if ok:
                scores["compliance_report_evidence_present_and_consistent"] = 1.0

    # 3) email checks
    email_text = _read_text_safe(email_out_path)
    if email_text is not None:
        scores["email_to_guru_file_exists"] = 1.0
        words = re.findall(r'\b\w+\b', email_text)
        friendly_opening_ok = False
        first_line = ""
        for line in email_text.splitlines():
            if line.strip():
                first_line = line.strip()
                break
        if re.match(r'^(hi|hello|hey|dear)\b', first_line.lower()):
            friendly_opening_ok = True
        if len(words) <= 150 and friendly_opening_ok:
            scores["email_word_limit_and_friendly_opening"] = 1.0

        # Positive summary sentence
        positive_ok = False
        for sent in re.split(r'[.!?]\s*', email_text):
            sl = sent.lower()
            if re.search(r'\b(looks|seems)\b', sl) and re.search(r'\b(okay|good|fine|solid|clear|in order|on track)\b', sl):
                positive_ok = True
                break
            if re.search(r'\b(what looks okay|looks good)\b', sl):
                positive_ok = True
                break
        if positive_ok:
            scores["email_has_positive_summary"] = 1.0

        # Avoid legal jargon
        lj_text = email_text.lower()
        if ("disclaimer" not in lj_text) and ("pursuant" not in lj_text) and ("hereby" not in lj_text):
            scores["email_avoids_legal_jargon"] = 1.0

        # Missing items with fix suggestions
        report = report if isinstance(report, dict) else None
        if report and isinstance(report.get("found"), dict):
            missing_keys = [k for k, v in report["found"].items() if v is False]
        else:
            exp_found, _ = _compute_must_include_from_form(signup_html)
            missing_keys = [k for k, v in exp_found.items() if v is False]

        key_to_terms = {
            "cancellation_policy_statement": ["cancellation"],
            "accessibility_notice": ["accessibility", "contact"],
            "privacy_notice_link": ["privacy notice", "privacy link"],
            "do_not_sell_or_share_statement": ["sell or share", "do not sell"],
            "email_consent_checkbox_unchecked_by_default": ["checkbox", "unchecked", "uncheck", "consent"],
            "opt_out_instruction": ["unsubscribe", "opt out"],
            "data_retention_limit_30_days": ["30 days", "retention", "delete", "keep"],
        }
        fix_verbs = ["add", "include", "link", "change", "set", "uncheck", "make", "provide", "state", "mention", "note", "show", "switch"]
        lines = [ln.strip() for ln in email_text.splitlines() if ln.strip()]
        covered = 0
        for key in missing_keys:
            terms = key_to_terms.get(key, [])
            found_line = False
            for ln in lines:
                ln_l = ln.lower()
                if terms and any(term in ln_l for term in terms) and any(v in ln_l for v in fix_verbs):
                    found_line = True
                    break
            if found_line:
                covered += 1
        if missing_keys:
            if covered == len(missing_keys):
                scores["email_lists_missing_items_with_fix_suggestions"] = 1.0
        else:
            scores["email_lists_missing_items_with_fix_suggestions"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()