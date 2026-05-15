import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_with_header(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return [], []
        header = rows[0]
        data_rows = []
        for r in rows[1:]:
            # pad or trim to header length
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            elif len(r) > len(header):
                r = r[:len(header)]
            data_rows.append({h: v for h, v in zip(header, r)})
        return data_rows, header
    except Exception:
        return None, None


def _simple_yaml_parse_rules(path: Path) -> Optional[dict]:
    # Minimal parser for the provided rules.yaml structure.
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    result = {}
    in_audiences = False
    current_aud = None
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if re.match(r"^\s*#.*$", line):
            continue
        if re.match(r"^audiences:\s*$", line):
            in_audiences = True
            result["audiences"] = {}
            continue
        if not in_audiences:
            continue
        # audience header, e.g., "  clinic_patient:"
        m_aud = re.match(r"^\s{2}([A-Za-z0-9_]+):\s*$", line)
        if m_aud:
            current_aud = m_aud.group(1)
            result["audiences"][current_aud] = {}
            continue
        if current_aud is None:
            continue
        # key: value or list
        m_kv = re.match(r"^\s{4}([A-Za-z0-9_]+):\s*(.*)\s*$", line)
        if m_kv:
            key = m_kv.group(1)
            val = m_kv.group(2)
            if key == "required_phrases":
                # Expect subsequent lines with "- ..."
                result["audiences"][current_aud][key] = []
                continue
            else:
                # parse int if numeric
                if re.match(r"^-?\d+$", val.strip()):
                    result["audiences"][current_aud][key] = int(val.strip())
                else:
                    # fallback to string
                    result["audiences"][current_aud][key] = val.strip().strip('"').strip("'")
                continue
        # list items under required_phrases
        m_li = re.match(r"^\s{6}-\s*(.*)\s*$", line)
        if m_li and current_aud is not None:
            phrase = m_li.group(1).strip()
            phrase = phrase.strip('"').strip("'")
            lst = result["audiences"].get(current_aud, {}).get("required_phrases")
            if isinstance(lst, list):
                lst.append(phrase)
            continue
    # Basic validation
    if "audiences" not in result:
        return None
    for aud, cfg in result["audiences"].items():
        if "max_words" not in cfg or "reading_ease_min" not in cfg or "required_phrases" not in cfg:
            return None
        if not isinstance(cfg["required_phrases"], list):
            return None
    return result


def _tokenize_words(text: str) -> List[str]:
    # Simple whitespace split; strip punctuation attached to words minimally.
    if not text:
        return []
    # Split on whitespace
    tokens = re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE)
    return tokens


def _count_syllables_in_word(word: str) -> int:
    word = word.lower()
    # Remove non-alpha
    word = re.sub(r"[^a-z]", "", word)
    if not word:
        return 0
    vowels = "aeiouy"
    syllables = 0
    prev_char_was_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_char_was_vowel:
            syllables += 1
        prev_char_was_vowel = is_vowel
    # silent 'e'
    if word.endswith("e") and syllables > 1 and not word.endswith(("le", "ye")):
        syllables -= 1
    if syllables == 0:
        syllables = 1
    return syllables


def _count_syllables(text: str) -> int:
    total = 0
    for w in _tokenize_words(text):
        total += _count_syllables_in_word(w)
    return total


def _count_sentences(text: str) -> int:
    if not text or not text.strip():
        return 1
    # Count sentence enders . ! ?
    enders = re.findall(r"[\.!?]", text)
    count = len(enders)
    return max(count, 1)


def _flesch_reading_ease(text: str) -> float:
    words = len(_tokenize_words(text))
    if words == 0:
        # conventionally, empty text has 0 words and 1 sentence; to avoid division by zero
        words = 1
    sentences = _count_sentences(text)
    syllables = _count_syllables(text)
    fre = 206.835 - 1.015 * (words / sentences) - 84.6 * (syllables / words)
    return float(fre)


def _normalize_yes_no(value: str) -> Optional[str]:
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("yes", "no"):
        return v
    return None


def _present_all_phrases(text: str, phrases: List[str]) -> Tuple[bool, List[str]]:
    lower = text.lower() if text else ""
    missing = []
    for p in phrases:
        if p.lower() not in lower:
            missing.append(p)
    return (len(missing) == 0), missing


def _glossary_check(original: str, rewritten: str, glossary: Dict[str, str]) -> Tuple[bool, List[str], List[str]]:
    # Returns (applied, offending_terms_in_rewritten, missing_replacements_based_on_original)
    offending = []
    missing_replacements = []
    lower_rewritten = rewritten.lower() if rewritten else ""
    lower_original = original.lower() if original else ""
    for bad_term, preferred in glossary.items():
        bad = bad_term.lower()
        pref = preferred.lower()
        if bad in lower_rewritten:
            offending.append(bad_term)
        # If the bad term appears in original, ensure the preferred term appears in rewritten
        if bad in lower_original and pref not in lower_rewritten:
            missing_replacements.append(preferred)
    applied = (len(offending) == 0 and len(missing_replacements) == 0)
    return applied, offending, missing_replacements


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "revised_messages_structure": 0.0,
        "revised_messages_coverage": 0.0,
        "metrics_consistency_word_count": 0.0,
        "metrics_consistency_reading_ease": 0.0,
        "required_phrases_flag_consistency": 0.0,
        "glossary_applied_flag_consistency": 0.0,
        "constraints_met_flag_consistency": 0.0,
        "violations_structure_and_alignment": 0.0,
        "summary_command_line_present": 0.0,
        "summary_counts_by_audience_correct": 0.0,
        "summary_avg_reading_ease_by_audience_correct": 0.0,
        "summary_manual_review_list_present": 0.0,
        "summary_two_update_paragraphs_present": 0.0,
    }

    # Load inputs
    input_msgs_path = workspace / "input" / "messages.csv"
    input_glossary_path = workspace / "input" / "glossary.json"
    input_rules_path = workspace / "input" / "rules.yaml"

    in_rows, in_header = _load_csv_with_header(input_msgs_path)
    glossary = _load_json(input_glossary_path)
    rules = _simple_yaml_parse_rules(input_rules_path)

    if in_rows is None or glossary is None or rules is None:
        # If inputs missing/malformed, we cannot assess; return zeros gracefully
        return scores

    # Build input lookup
    input_by_id = {}
    for r in in_rows:
        mid = str(r.get("message_id", "")).strip()
        input_by_id[mid] = {
            "audience": r.get("audience", "").strip(),
            "subject": r.get("subject", "").strip(),
            "body": r.get("body", "") if r.get("body") is not None else "",
        }

    # Load outputs
    revised_path = workspace / "output" / "revised_messages.csv"
    violations_path = workspace / "output" / "violations.csv"
    summary_path = workspace / "output" / "rewrite_summary.md"

    rev_rows, rev_header = _load_csv_with_header(revised_path)
    viol_rows, viol_header = _load_csv_with_header(violations_path)
    summary_text = _read_text(summary_path)

    # Check revised_messages structure
    required_rev_header = ["message_id", "audience", "subject", "rewritten_body", "word_count", "reading_ease", "required_phrases_present", "glossary_applied", "constraints_met"]
    if rev_rows is not None and rev_header is not None:
        if rev_header == required_rev_header:
            scores["revised_messages_structure"] = 1.0
        else:
            scores["revised_messages_structure"] = 0.0
    else:
        scores["revised_messages_structure"] = 0.0

    # Coverage and metrics checks only if structure ok
    if rev_rows is not None and rev_header == required_rev_header:
        # Coverage
        rev_ids = [str(r.get("message_id", "")).strip() for r in rev_rows]
        input_ids = list(input_by_id.keys())
        if set(rev_ids) == set(input_ids) and len(rev_ids) == len(input_ids):
            # For each id, check audience and subject match input
            coverage_ok = True
            for r in rev_rows:
                mid = str(r.get("message_id", "")).strip()
                aud = r.get("audience", "").strip()
                subj = r.get("subject", "").strip()
                if mid not in input_by_id:
                    coverage_ok = False
                    break
                if input_by_id[mid]["audience"] != aud or input_by_id[mid]["subject"] != subj:
                    coverage_ok = False
                    break
            scores["revised_messages_coverage"] = 1.0 if coverage_ok else 0.0
        else:
            scores["revised_messages_coverage"] = 0.0

        # Prepare metrics verification
        wc_correct = 0
        re_correct = 0
        req_flag_correct = 0
        gloss_flag_correct = 0
        constraints_flag_correct = 0
        total_rows = len(rev_rows)

        # Precompute expected per message results for violations as well
        expected_violations_by_msg = {}  # mid -> set of violation types
        audiences_cfg = rules.get("audiences", {})

        # Also compute computed reading_ease per row for summary validations
        computed_re_by_aud = {}
        counts_by_aud = {}
        pass_counts_by_aud = {}
        fail_counts_by_aud = {}
        for r in rev_rows:
            mid = str(r.get("message_id", "")).strip()
            aud = r.get("audience", "").strip()
            subj = r.get("subject", "").strip()
            rewritten_body = r.get("rewritten_body", "") or ""
            word_count_val = _parse_int(r.get("word_count", ""))
            try:
                re_val = float(str(r.get("reading_ease", "")).strip())
            except Exception:
                re_val = None
            req_flag = _normalize_yes_no(r.get("required_phrases_present", ""))
            gloss_flag = _normalize_yes_no(r.get("glossary_applied", ""))
            constraints_flag = _normalize_yes_no(r.get("constraints_met", ""))

            # Compute expected metrics
            computed_wc = len(_tokenize_words(rewritten_body))
            computed_re = _flesch_reading_ease(rewritten_body)
            # Word count match
            if word_count_val is not None and word_count_val == computed_wc:
                wc_correct += 1
            # Reading ease match within tolerance
            if re_val is not None and abs(re_val - computed_re) <= 1.0:
                re_correct += 1

            # Required phrases
            aud_rules = audiences_cfg.get(aud, {})
            required_phrases = aud_rules.get("required_phrases", []) if isinstance(aud_rules, dict) else []
            req_present, missing_phrases = _present_all_phrases(rewritten_body, required_phrases)
            expected_req_flag = "yes" if req_present else "no"
            if req_flag == expected_req_flag:
                req_flag_correct += 1

            # Glossary
            original_body = input_by_id.get(mid, {}).get("body", "")
            applied, offending_terms, missing_repls = _glossary_check(original_body, rewritten_body, glossary)
            expected_gloss_flag = "yes" if applied else "no"
            if gloss_flag == expected_gloss_flag:
                gloss_flag_correct += 1

            # Constraints
            max_words = aud_rules.get("max_words")
            re_min = aud_rules.get("reading_ease_min")
            wc_pass = (computed_wc <= max_words) if isinstance(max_words, int) else False
            re_pass = (computed_re >= re_min) if isinstance(re_min, int) else False
            all_pass = (wc_pass and re_pass and req_present and applied)
            expected_constraints_flag = "yes" if all_pass else "no"
            if constraints_flag == expected_constraints_flag:
                constraints_flag_correct += 1

            # Expected violations set
            expected_viols = set()
            if not req_present:
                expected_viols.add("missing_required_phrase")
            if isinstance(max_words, int) and computed_wc > max_words:
                expected_viols.add("too_long")
            if isinstance(re_min, int) and computed_re < re_min:
                expected_viols.add("low_readability")
            if not applied:
                expected_viols.add("glossary_not_applied")
            expected_violations_by_msg[(mid, aud)] = expected_viols

            # Aggregate by audience for summary
            re_list = computed_re_by_aud.setdefault(aud, [])
            re_list.append(computed_re)
            counts_by_aud[aud] = counts_by_aud.get(aud, 0) + 1
            if all_pass:
                pass_counts_by_aud[aud] = pass_counts_by_aud.get(aud, 0) + 1
            else:
                fail_counts_by_aud[aud] = fail_counts_by_aud.get(aud, 0) + 1

        if total_rows > 0:
            scores["metrics_consistency_word_count"] = wc_correct / total_rows
            scores["metrics_consistency_reading_ease"] = re_correct / total_rows
            scores["required_phrases_flag_consistency"] = req_flag_correct / total_rows
            scores["glossary_applied_flag_consistency"] = gloss_flag_correct / total_rows
            scores["constraints_met_flag_consistency"] = constraints_flag_correct / total_rows
        else:
            # No rows: leave at 0
            pass

        # Violations CSV checks
        allowed_violation_types = {"missing_required_phrase", "too_long", "low_readability", "glossary_not_applied"}
        if viol_rows is not None and viol_header is not None and viol_header == ["message_id", "audience", "violation_type", "details"]:
            # Build mapping: (mid, aud) -> list of violations rows
            viol_map = {}
            all_types_valid = True
            for vr in viol_rows:
                mid = str(vr.get("message_id", "")).strip()
                aud = vr.get("audience", "").strip()
                vtype = vr.get("violation_type", "").strip()
                det = vr.get("details", "") or ""
                if vtype not in allowed_violation_types:
                    all_types_valid = False
                viol_map.setdefault((mid, aud), []).append((vtype, det))
            aligned_count = 0
            for key, expected_set in expected_violations_by_msg.items():
                present_rows = viol_map.get(key, [])
                present_types = {vt for vt, _ in present_rows}
                # Ensure all expected are present and there are no unexpected extras beyond allowed when expecting none
                if present_types >= expected_set:
                    # Additional validation on details for some types
                    details_ok = True
                    # If missing_required_phrase expected, ensure details mention at least one missing phrase
                    if "missing_required_phrase" in expected_set:
                        # Determine missing phrases again
                        mid, aud = key
                        rewritten_body = ""
                        for r in rev_rows:
                            if str(r.get("message_id", "")).strip() == mid and r.get("audience", "").strip() == aud:
                                rewritten_body = r.get("rewritten_body", "") or ""
                                break
                        aud_rules = audiences_cfg.get(aud, {})
                        required_phrases = aud_rules.get("required_phrases", []) if isinstance(aud_rules, dict) else []
                        req_present, missing_phrases = _present_all_phrases(rewritten_body, required_phrases)
                        has_any = False
                        for vt, det in present_rows:
                            if vt == "missing_required_phrase" and det:
                                for mp in missing_phrases:
                                    if mp.lower() in det.lower():
                                        has_any = True
                                        break
                        if not has_any:
                            details_ok = False
                    if "glossary_not_applied" in expected_set:
                        # Check details mention either offending term or missing replacement
                        mid, aud = key
                        original = input_by_id.get(mid, {}).get("body", "")
                        rewritten = ""
                        for r in rev_rows:
                            if str(r.get("message_id", "")).strip() == mid and r.get("audience", "").strip() == aud:
                                rewritten = r.get("rewritten_body", "") or ""
                                break
                        applied, offending, missing_repls = _glossary_check(original, rewritten, glossary)
                        lower_det_concat = " ".join([d for vt, d in present_rows if vt == "glossary_not_applied"]).lower()
                        ok_any = False
                        for t in offending:
                            if t.lower() in lower_det_concat:
                                ok_any = True
                                break
                        for rep in missing_repls:
                            if rep.lower() in lower_det_concat:
                                ok_any = True
                                break
                        if not ok_any:
                            details_ok = False
                    if details_ok:
                        aligned_count += 1
            # Also ensure there are no violation rows for messages that passed all constraints
            extraneous_ok = True
            for key, vrlist in viol_map.items():
                if key not in expected_violations_by_msg:
                    # Some message not in revised? Already failed coverage likely
                    continue
                expected_set = expected_violations_by_msg[key]
                if len(expected_set) == 0 and len(vrlist) > 0:
                    extraneous_ok = False
                    break
            if all_types_valid and extraneous_ok and len(expected_violations_by_msg) > 0:
                # Score as fraction of messages aligned
                scores["violations_structure_and_alignment"] = aligned_count / len(expected_violations_by_msg)
            elif all_types_valid and extraneous_ok and len(expected_violations_by_msg) == 0:
                # No messages to check violations; if file empty it's okay
                scores["violations_structure_and_alignment"] = 1.0 if len(viol_rows) == 0 else 0.0
            else:
                scores["violations_structure_and_alignment"] = 0.0
        else:
            scores["violations_structure_and_alignment"] = 0.0

        # Summary checks
        if summary_text is not None:
            lines = summary_text.splitlines()

            # Command line first line
            if len(lines) >= 1 and lines[0].startswith("Command: ") and len(lines[0].split("Command: ", 1)[1].strip()) > 0:
                scores["summary_command_line_present"] = 1.0

            # Counts by audience
            counts_ok = True
            for aud in counts_by_aud.keys():
                total = counts_by_aud.get(aud, 0)
                passed = pass_counts_by_aud.get(aud, 0)
                failed = fail_counts_by_aud.get(aud, 0)
                # find a line containing the audience and the three numbers
                found_line = False
                for ln in lines:
                    if aud in ln:
                        nums = re.findall(r"\d+", ln)
                        nums_int = [int(n) for n in nums]
                        if total in nums_int and passed in nums_int and failed in nums_int:
                            found_line = True
                            break
                if not found_line:
                    counts_ok = False
                    break
            scores["summary_counts_by_audience_correct"] = 1.0 if counts_ok and len(counts_by_aud) > 0 else 0.0

            # Average reading ease by audience
            avg_ok = True
            for aud, vals in computed_re_by_aud.items():
                if not vals:
                    continue
                avg_val = sum(vals) / len(vals)
                found_avg = False
                for ln in lines:
                    if aud in ln and ("reading_ease" in ln or "reading ease" in ln or "Readability" in ln or "readability" in ln):
                        floats = re.findall(r"[-+]?\d*\.\d+|\d+", ln)
                        # Parse floats
                        float_vals = []
                        for t in floats:
                            try:
                                float_vals.append(float(t))
                            except Exception:
                                pass
                        for fv in float_vals:
                            if abs(fv - avg_val) <= 1.0:
                                found_avg = True
                                break
                    if found_avg:
                        break
                if not found_avg:
                    avg_ok = False
                    break
            scores["summary_avg_reading_ease_by_audience_correct"] = 1.0 if avg_ok and len(computed_re_by_aud) > 0 else 0.0

            # Manual review list: failing message_ids should be listed
            failing_ids = [mid for (mid, aud) in expected_violations_by_msg.keys() if len(expected_violations_by_msg[(mid, aud)]) > 0]
            manual_ok = True
            if failing_ids:
                for mid in failing_ids:
                    # present anywhere
                    if str(mid) not in summary_text:
                        manual_ok = False
                        break
            else:
                # no failing ids, accept if file mentions none or contains a statement; we'll accept as 1.0
                manual_ok = True
            scores["summary_manual_review_list_present"] = 1.0 if manual_ok else 0.0

            # Two short update paragraphs: at least two paragraphs; one mentions clinic/patient, one professor/academic
            # Define paragraphs as blocks of non-empty lines separated by blank line
            paras = []
            current = []
            for ln in lines[1:]:  # skip command line
                if ln.strip() == "":
                    if current:
                        paras.append("\n".join(current).strip())
                        current = []
                else:
                    current.append(ln)
            if current:
                paras.append("\n".join(current).strip())
            # Look for two paragraphs that include targeted audience
            has_clinic_para = any(("clinic" in p.lower() or "patient" in p.lower()) for p in paras)
            has_prof_para = any(("professor" in p.lower() or "academic" in p.lower()) for p in paras)
            if len(paras) >= 2 and has_clinic_para and has_prof_para:
                scores["summary_two_update_paragraphs_present"] = 1.0
            else:
                scores["summary_two_update_paragraphs_present"] = 0.0
        else:
            # Summary missing
            scores["summary_command_line_present"] = 0.0
            scores["summary_counts_by_audience_correct"] = 0.0
            scores["summary_avg_reading_ease_by_audience_correct"] = 0.0
            scores["summary_manual_review_list_present"] = 0.0
            scores["summary_two_update_paragraphs_present"] = 0.0

    # Return scores
    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()