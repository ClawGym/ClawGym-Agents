import json
import sys
import re
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_parse_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    out: List[Dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        if not line.strip():
            # Allow empty lines; skip them
            continue
        try:
            obj = json.loads(line)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        out.append(obj)
    return out


def safe_parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _parse_yaml_value(val: str) -> Any:
    s = val.strip()
    if s == "":
        return None
    low = s.lower()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if low == "true":
        return True
    if low == "false":
        return False
    # integer
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except Exception:
            pass
    # float (unlikely in this task)
    if re.fullmatch(r"-?\d+\.\d+", s):
        try:
            return float(s)
        except Exception:
            pass
    # inline list resembling JSON
    if s.startswith("[") and s.endswith("]"):
        try:
            return json.loads(s)
        except Exception:
            # fallback: split crudely by comma, strip quotes/spaces
            items = s[1:-1].split(",")
            cleaned = []
            for it in items:
                it = it.strip()
                if (it.startswith('"') and it.endswith('"')) or (it.startswith("'") and it.endswith("'")):
                    cleaned.append(it[1:-1])
                else:
                    cleaned.append(it)
            return cleaned
    # default to raw string (unquoted)
    return s


def parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Very small YAML parser sufficient for the provided tone_guidelines.yaml:
    - Handles nested dicts via indentation.
    - Keys end with ":".
    - Values on same line supported (strings, numbers, booleans, inline JSON-like lists).
    - Ignores empty lines and comments.
    """
    text = safe_read_text(path)
    if text is None:
        return None
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    try:
        for raw_line in text.splitlines():
            if not raw_line.strip():
                continue
            if raw_line.lstrip().startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            line = raw_line.strip()
            # Determine current dict by indentation
            while stack and indent <= stack[-1][0]:
                stack.pop()
            current = stack[-1][1] if stack else root
            if ":" in line:
                key_part, val_part = line.split(":", 1)
                key = key_part.strip()
                if val_part.strip() == "":
                    # New nested dict
                    new_dict: Dict[str, Any] = {}
                    current[key] = new_dict
                    stack.append((indent, new_dict))
                else:
                    value = _parse_yaml_value(val_part)
                    current[key] = value
            else:
                # Unexpected format
                return None
    except Exception:
        return None
    return root


def word_count(text: str) -> int:
    return len(text.split())


def starts_with_accepted_greeting(text: str, greetings: List[str]) -> bool:
    s = text.lstrip()
    s_low = s.lower()
    for g in greetings:
        gl = g.lower()
        if s_low.startswith(gl):
            # Ensure boundary after greeting
            if len(s_low) == len(gl):
                return True
            next_ch = s_low[len(gl)]
            if next_ch in (" ", ",", "!", ":", "-", "."):
                return True
    return False


def required_phrases_ok(text: str, phrases: List[str]) -> bool:
    t = text.lower()
    return all(p.lower() in t for p in phrases)


def banned_words_ok(text: str, banned: List[str]) -> bool:
    t = text.lower()
    return not any(b.lower() in t for b in banned)


def compute_message_checks(message: str, audience_rules: Dict[str, Any]) -> Dict[str, bool]:
    max_words = audience_rules.get("max_words")
    require_greeting = bool(audience_rules.get("require_greeting"))
    accepted_greetings = audience_rules.get("accepted_greetings") or []
    required_phrases = audience_rules.get("required_phrases") or []
    banned_words = audience_rules.get("banned_words") or []

    wc_ok = isinstance(max_words, int) and word_count(message) <= max_words
    if require_greeting:
        greeting_ok = starts_with_accepted_greeting(message, list(accepted_greetings))
    else:
        greeting_ok = True
    required_ok = required_phrases_ok(message, list(required_phrases))
    banned_ok = banned_words_ok(message, list(banned_words))
    overall_ok = wc_ok and greeting_ok and required_ok and banned_ok
    return {
        "words_ok": bool(wc_ok),
        "greeting_ok": bool(greeting_ok),
        "required_ok": bool(required_ok),
        "banned_ok": bool(banned_ok),
        "overall_ok": bool(overall_ok),
    }


def load_guidelines(workspace: Path) -> Optional[Dict[str, Any]]:
    yaml_path = workspace / "input" / "tone_guidelines.yaml"
    return parse_simple_yaml(yaml_path)


def load_messages(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    in_path = workspace / "input" / "messages.jsonl"
    return safe_parse_jsonl(in_path)


def load_revised_messages(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    out_path = workspace / "outputs" / "revised_messages.jsonl"
    return safe_parse_jsonl(out_path)


def messages_index_by_id(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rid = r.get("id")
        if isinstance(rid, str):
            out[rid] = r
    return out


def safe_load_validation_results(workspace: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    path = workspace / "outputs" / "validation_results.json"
    obj = safe_load_json(path)
    if obj is None:
        return None
    results: Dict[str, Dict[str, Any]] = {}
    if isinstance(obj, list):
        for item in obj:
            if not isinstance(item, dict):
                return None
            rid = item.get("id")
            if not isinstance(rid, str):
                return None
            results[rid] = item
    elif isinstance(obj, dict):
        # Could be mapping id->result
        # Ensure values are dicts and contain id or we inject the key as id
        for k, v in obj.items():
            if not isinstance(v, dict):
                return None
            rid = v.get("id", k)
            if not isinstance(rid, str):
                return None
            results[rid] = v
    else:
        return None
    return results


def find_count_in_report(text: str, kind_keywords: List[str]) -> Optional[int]:
    """
    Look for a number near keywords. Returns the first matched integer.
    """
    # Simple approach: search lines containing any keyword, then extract first integer
    for line in text.splitlines():
        low = line.lower()
        if any(k in low for k in kind_keywords):
            m = re.search(r"(-?\d+)", line)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    continue
    return None


def report_lists_failed_ids_with_checks(text: str, failed_checks: Dict[str, List[str]]) -> bool:
    """
    failed_checks: mapping id -> list of failed categories among ["words", "greeting", "required", "banned"]
    The report must mention each failed id and indicate which checks failed.
    We'll require for each failed id that:
      - There exists a line containing the id, and
      - That line contains all failed category keywords (reasonable variants allowed).
    """
    # Precompute lines lowercase
    lines = text.splitlines()
    success_all = True
    for mid, failures in failed_checks.items():
        # Find line containing id
        matched_line = None
        for line in lines:
            if mid in line:
                matched_line = line
                break
        if matched_line is None:
            success_all = False
            continue
        low = matched_line.lower()
        # Map category to acceptable synonyms
        synonyms = {
            "words": ["words", "word count", "max_words", "length"],
            "greeting": ["greeting"],
            "required": ["required", "required phrases", "required_phrases"],
            "banned": ["banned", "banned words"],
        }
        for cat in failures:
            ok = any(term in low for term in synonyms.get(cat, []))
            if not ok:
                success_all = False
    return success_all


def extract_email_components(text: str) -> Tuple[Optional[str], List[str]]:
    """
    Returns (subject_line, body_lines_excluding_subject)
    """
    lines = text.splitlines()
    subject_line: Optional[str] = None
    body_lines: List[str] = []
    for line in lines:
        if subject_line is None and line.strip().lower().startswith("subject:"):
            subject_line = line.strip()
        else:
            body_lines.append(line)
    return subject_line, body_lines


def body_word_count(lines: List[str]) -> int:
    joined = "\n".join(lines)
    return word_count(joined)


def email_contains_accepted_greeting(lines: List[str], greetings: List[str]) -> bool:
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if starts_with_accepted_greeting(s, greetings):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "revised_messages_present_and_matching_inputs": 0.0,
        "revised_word_count_compliant": 0.0,
        "revised_greeting_compliant": 0.0,
        "revised_required_phrases_compliant": 0.0,
        "revised_banned_words_compliant": 0.0,
        "validation_results_present_and_correct": 0.0,
        "report_counts_correct": 0.0,
        "report_failed_ids_with_checks_listed": 0.0,
        "report_has_next_step_recommendation": 0.0,
        "emails_exist_and_subject_contains_topic": 0.0,
        "emails_greeting_accepted": 0.0,
        "emails_body_constraints_compliant": 0.0,
    }

    # Load inputs
    guidelines = load_guidelines(workspace)
    messages_in = load_messages(workspace)
    revised = load_revised_messages(workspace)

    if guidelines is None or messages_in is None or revised is None:
        # We will still attempt to compute partial scores where possible
        pass

    # Build audience rules map
    audience_rules: Dict[str, Dict[str, Any]] = {}
    if isinstance(guidelines, dict):
        for aud, rule in guidelines.items():
            if isinstance(rule, dict):
                audience_rules[aud] = rule

    # Check revised messages file completeness and correctness of fields
    revised_ok = False
    if messages_in is not None and revised is not None:
        in_by_id = messages_index_by_id(messages_in)
        out_by_id = messages_index_by_id(revised)
        # Must cover exactly all ids
        if set(in_by_id.keys()) == set(out_by_id.keys()) and len(revised) == len(in_by_id):
            fields_ok = True
            for rid, in_row in in_by_id.items():
                out_row = out_by_id.get(rid)
                if out_row is None:
                    fields_ok = False
                    break
                # Required fields present
                for key in ("id", "audience", "original_message", "revised_message"):
                    if key not in out_row:
                        fields_ok = False
                        break
                if not fields_ok:
                    break
                # Types and matching
                if out_row["id"] != in_row.get("id"):
                    fields_ok = False
                if out_row.get("audience") != in_row.get("audience"):
                    fields_ok = False
                if out_row.get("original_message") != in_row.get("original_message"):
                    fields_ok = False
                if not isinstance(out_row.get("revised_message"), str) or not out_row.get("revised_message").strip():
                    fields_ok = False
                if not fields_ok:
                    break
            if fields_ok:
                revised_ok = True
    if revised_ok:
        scores["revised_messages_present_and_matching_inputs"] = 1.0

    # Compute compliance for revised messages
    if revised_ok and audience_rules:
        in_by_id = messages_index_by_id(messages_in)  # type: ignore[arg-type]
        out_by_id = messages_index_by_id(revised)  # type: ignore[arg-type]
        words_all = True
        greet_all = True
        required_all = True
        banned_all = True
        computed_checks: Dict[str, Dict[str, bool]] = {}
        for rid, out_row in out_by_id.items():
            aud = out_row.get("audience")
            msg = out_row.get("revised_message", "")
            rules = audience_rules.get(aud, {})
            checks = compute_message_checks(msg, rules)
            computed_checks[rid] = checks
            if not checks["words_ok"]:
                words_all = False
            if not checks["greeting_ok"]:
                greet_all = False
            if not checks["required_ok"]:
                required_all = False
            if not checks["banned_ok"]:
                banned_all = False

        scores["revised_word_count_compliant"] = 1.0 if words_all else 0.0
        scores["revised_greeting_compliant"] = 1.0 if greet_all else 0.0
        scores["revised_required_phrases_compliant"] = 1.0 if required_all else 0.0
        scores["revised_banned_words_compliant"] = 1.0 if banned_all else 0.0
    else:
        # leave as 0.0
        pass

    # Validate validation_results.json correctness
    val_results = safe_load_validation_results(workspace)
    if revised_ok and audience_rules and val_results is not None:
        out_by_id = messages_index_by_id(revised)  # type: ignore[arg-type]
        # recompute checks
        all_ids = set(out_by_id.keys())
        if set(val_results.keys()) == all_ids:
            all_match = True
            for rid, out_row in out_by_id.items():
                aud = out_row.get("audience")
                msg = out_row.get("revised_message", "")
                rules = audience_rules.get(aud, {})
                checks = compute_message_checks(msg, rules)
                # Ensure validation file contains booleans and overall_ok as AND
                recorded = val_results.get(rid, {})
                try:
                    words_ok = bool(recorded["words_ok"])
                    greeting_ok = bool(recorded["greeting_ok"])
                    required_ok = bool(recorded["required_ok"])
                    banned_ok = bool(recorded["banned_ok"])
                    overall_ok = bool(recorded["overall_ok"])
                except Exception:
                    all_match = False
                    break
                if not (
                    words_ok == checks["words_ok"]
                    and greeting_ok == checks["greeting_ok"]
                    and required_ok == checks["required_ok"]
                    and banned_ok == checks["banned_ok"]
                    and overall_ok == checks["overall_ok"]
                ):
                    all_match = False
                    break
            if all_match:
                scores["validation_results_present_and_correct"] = 1.0

    # Report.md checks
    report_path = workspace / "outputs" / "report.md"
    report_text = safe_read_text(report_path)
    if report_text is not None and revised_ok and audience_rules:
        out_by_id = messages_index_by_id(revised)  # type: ignore[arg-type]
        # Recompute overall statuses
        overall_map: Dict[str, bool] = {}
        failed_checks_detail: Dict[str, List[str]] = {}
        passed_count = 0
        for rid, out_row in out_by_id.items():
            aud = out_row.get("audience")
            msg = out_row.get("revised_message", "")
            rules = audience_rules.get(aud, {})
            checks = compute_message_checks(msg, rules)
            overall_map[rid] = checks["overall_ok"]
            if checks["overall_ok"]:
                passed_count += 1
            else:
                failures: List[str] = []
                if not checks["words_ok"]:
                    failures.append("words")
                if not checks["greeting_ok"]:
                    failures.append("greeting")
                if not checks["required_ok"]:
                    failures.append("required")
                if not checks["banned_ok"]:
                    failures.append("banned")
                failed_checks_detail[rid] = failures

        processed_expected = len(out_by_id)
        failed_expected = processed_expected - passed_count

        processed_in_report = find_count_in_report(report_text, ["processed"])
        passed_in_report = find_count_in_report(report_text, ["passed"])
        failed_in_report = find_count_in_report(report_text, ["failed"])

        if (
            processed_in_report == processed_expected
            and passed_in_report == passed_count
            and failed_in_report == failed_expected
        ):
            scores["report_counts_correct"] = 1.0

        # Failed ids listing with notes
        if failed_expected == 0:
            # No failures; nothing to list; consider this check satisfied
            scores["report_failed_ids_with_checks_listed"] = 1.0
        else:
            if report_lists_failed_ids_with_checks(report_text, failed_checks_detail):
                scores["report_failed_ids_with_checks_listed"] = 1.0

        # Next-step recommendation presence
        low = report_text.lower()
        if any(kw in low for kw in ["next step", "next steps", "recommendation", "recommendations", "second pass"]):
            scores["report_has_next_step_recommendation"] = 1.0

    # Emails checks
    email_targets = safe_parse_csv(workspace / "input" / "email_targets.csv")
    emails_exist_ok = True
    emails_subject_ok = True
    emails_greeting_ok = True
    emails_body_ok = True
    if email_targets is not None and audience_rules:
        for row in email_targets:
            slug = row.get("slug")
            audience = row.get("audience")
            topic = row.get("topic")
            if not slug or not audience or not topic:
                emails_exist_ok = False
                emails_subject_ok = False
                emails_greeting_ok = False
                emails_body_ok = False
                break
            email_path = workspace / "outputs" / "emails" / f"{slug}.md"
            text = safe_read_text(email_path)
            if text is None:
                emails_exist_ok = False
                emails_subject_ok = False
                emails_greeting_ok = False
                emails_body_ok = False
                continue
            subject_line, body_lines = extract_email_components(text)
            if subject_line is None:
                emails_subject_ok = False
            else:
                # Subject must contain topic (case-insensitive)
                if topic.lower() not in subject_line.lower():
                    emails_subject_ok = False
            rules = audience_rules.get(audience, {})
            accepted_greetings = rules.get("accepted_greetings") or []
            require_greeting = bool(rules.get("require_greeting"))
            if require_greeting:
                if not email_contains_accepted_greeting(body_lines, list(accepted_greetings)):
                    emails_greeting_ok = False
            # Body constraints: max_words, banned, required
            max_words = rules.get("max_words")
            req_phrases = rules.get("required_phrases") or []
            banned = rules.get("banned_words") or []
            body_text = "\n".join(body_lines)
            wc_ok = isinstance(max_words, int) and word_count(body_text) <= max_words
            req_ok = required_phrases_ok(body_text, list(req_phrases))
            banned_ok = banned_words_ok(body_text, list(banned))
            if not (wc_ok and req_ok and banned_ok):
                emails_body_ok = False
    else:
        emails_exist_ok = False
        emails_subject_ok = False
        emails_greeting_ok = False
        emails_body_ok = False

    # Assign email-related scores
    if email_targets is not None and audience_rules:
        # Existence is verified per target; require both files to exist
        # We consider existance in combination with subject for the "emails_exist_and_subject_contains_topic" check
        if emails_exist_ok and emails_subject_ok:
            scores["emails_exist_and_subject_contains_topic"] = 1.0
        if emails_greeting_ok:
            scores["emails_greeting_accepted"] = 1.0
        if emails_body_ok:
            scores["emails_body_constraints_compliant"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()