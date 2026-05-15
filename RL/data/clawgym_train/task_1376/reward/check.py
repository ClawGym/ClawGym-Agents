import os
import sys
import json
import csv
import re

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_questions_count(path):
    data = load_json(path)
    if data is None:
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        # try common key
        q = data.get("questions")
        if isinstance(q, list):
            return len(q)
    return 0

def get_trace_ids_from_obj(obj):
    ids = []
    if isinstance(obj, dict):
        if "trace_ids" in obj and isinstance(obj["trace_ids"], list):
            ids.extend([t for t in obj["trace_ids"] if isinstance(t, str) and t.strip() != ""])
        if "trace_id" in obj and isinstance(obj["trace_id"], str) and obj["trace_id"].strip() != "":
            ids.append(obj["trace_id"])
    return ids

def contains_snippet(file_text, snippet):
    if not isinstance(snippet, str):
        return False
    s = snippet.strip()
    if not s:
        return False
    # direct
    if s in file_text:
        return True
    # strip surrounding quotes
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s2 = s[1:-1]
        if s2 and s2 in file_text:
            return True
        s = s2
    # normalize whitespace
    def norm(x):
        return re.sub(r"\s+", " ", x)
    if norm(s) in norm(file_text):
        return True
    # case-insensitive
    if s.lower() in file_text.lower():
        return True
    return False

def read_csv_rows(path):
    rows = []
    header = None
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0:
                    header = row
                else:
                    rows.append(row)
    except Exception:
        return None, None
    return header, rows

def split_sections_by_gaps(md_text):
    # Returns list of sections; each section is list of lines for that gap
    lines = md_text.splitlines()
    sections = []
    current = None
    for line in lines:
        if line.startswith("Gap: "):
            if current is not None:
                sections.append(current)
            current = [line]
        else:
            if current is not None:
                current.append(line)
    if current is not None:
        sections.append(current)
    return sections

def end_with_exact_disclaimer(md_text, disclaimer):
    lines = [ln.rstrip() for ln in md_text.splitlines()]
    # find last non-empty line
    i = len(lines) - 1
    while i >= 0 and lines[i].strip() == "":
        i -= 1
    if i < 0:
        return False
    return lines[i].strip() == disclaimer

def collect_trace_ids_from_text(text, known_ids):
    # Return set of known ids found as whole tokens in text
    found = set()
    if not text:
        return found
    # We detect any substring that equals to a known id; to avoid heavy regex, we scan
    for tid in known_ids:
        if tid in text:
            found.add(tid)
    return found

def validate_trace_jsonl(trace_path, input_dir):
    """
    Returns:
      ok_structure (bool),
      ok_tags (bool),
      ok_unique_ids (bool),
      ok_sources_snippets (bool),
      traces (list of dict),
      id_map (dict: id->trace)
    """
    allowed_tags = {"coverage", "exclusion", "deductible", "premium", "limit", "waiting_period", "endorsement", "definition", "ambiguity"}
    ok_structure = True
    ok_tags = True
    ok_unique_ids = True
    ok_sources_snippets = True
    traces = []
    id_map = {}
    seen_ids = set()
    try:
        with open(trace_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    ok_structure = False
                    continue
                # structure
                keys_ok = all(k in obj for k in ["trace_id", "source_file", "section_title", "line_index", "snippet", "tag"])
                if not keys_ok:
                    ok_structure = False
                # type checks
                if not isinstance(obj.get("trace_id"), str) or obj.get("trace_id", "").strip() == "":
                    ok_structure = False
                if not isinstance(obj.get("source_file"), str) or not obj.get("source_file", "").startswith("input/"):
                    ok_structure = False
                if not isinstance(obj.get("section_title"), str):
                    ok_structure = False
                if not isinstance(obj.get("line_index"), int):
                    ok_structure = False
                if not isinstance(obj.get("snippet"), str):
                    ok_structure = False
                if not isinstance(obj.get("tag"), str) or obj.get("tag") not in allowed_tags:
                    ok_tags = False
                # unique ids
                tid = obj.get("trace_id")
                if isinstance(tid, str):
                    if tid in seen_ids:
                        ok_unique_ids = False
                    else:
                        seen_ids.add(tid)
                traces.append(obj)
                # source and snippet validation
                src_rel = obj.get("source_file")
                src_abs = os.path.join(input_dir, os.path.relpath(src_rel, "input"))
                if not os.path.isfile(src_abs):
                    ok_sources_snippets = False
                else:
                    text = load_text(src_abs) or ""
                    if not contains_snippet(text, obj.get("snippet", "")):
                        ok_sources_snippets = False
                id_map[obj.get("trace_id")] = obj
    except Exception:
        return False, False, False, False, [], {}
    return ok_structure, ok_tags, ok_unique_ids, ok_sources_snippets, traces, id_map

def validate_summary_json(summary_path, trace_id_map):
    checks = {
        "summary_structure_valid": False,
        "summary_coverage_entries_valid": False,
        "summary_min_coverage_items": False,
        "summary_exclusions_entries_valid": False,
        "summary_min_exclusions_count": False,
        "summary_glossary_entries_valid": False,
        "summary_premiums_type_valid": False,
        "summary_claim_limits_type_valid": False,
        "summary_waiting_periods_type_valid": False,
        "summary_endorsements_type_valid": False,
        "summary_effective_dates_valid": False,
        "summary_policy_names_valid": False,
        "summary_trace_ids_exist": False,
    }
    data = load_json(summary_path)
    if not isinstance(data, dict):
        return checks
    required_keys = ["policy_names", "effective_dates", "coverage", "exclusions", "premiums", "claim_limits", "waiting_periods", "endorsements", "glossary", "notes"]
    if all(k in data for k in required_keys):
        # type checks
        types_ok = True
        types_ok = types_ok and isinstance(data.get("policy_names"), list)
        types_ok = types_ok and isinstance(data.get("effective_dates"), dict)
        types_ok = types_ok and isinstance(data.get("coverage"), list)
        types_ok = types_ok and isinstance(data.get("exclusions"), list)
        types_ok = types_ok and (isinstance(data.get("premiums"), list) or isinstance(data.get("premiums"), dict))
        types_ok = types_ok and isinstance(data.get("claim_limits"), list)
        types_ok = types_ok and isinstance(data.get("waiting_periods"), list)
        types_ok = types_ok and isinstance(data.get("endorsements"), list)
        types_ok = types_ok and isinstance(data.get("glossary"), list)
        types_ok = types_ok and isinstance(data.get("notes"), dict)
        if types_ok:
            checks["summary_structure_valid"] = True
    # coverage entries
    cov_valid = True
    cov_ids_exist = True
    coverage = data.get("coverage") if isinstance(data, dict) else None
    cov_count = 0
    if isinstance(coverage, list) and len(coverage) > 0:
        for item in coverage:
            if not isinstance(item, dict):
                cov_valid = False
                continue
            if "item" not in item or "limit" not in item or "deductible" not in item:
                cov_valid = False
            else:
                if not isinstance(item.get("item"), str):
                    cov_valid = False
            tids = get_trace_ids_from_obj(item)
            if len(tids) == 0:
                cov_valid = False
            else:
                for tid in tids:
                    if tid not in trace_id_map:
                        cov_ids_exist = False
            cov_count += 1
        if cov_valid:
            checks["summary_coverage_entries_valid"] = True
        if cov_count >= 1:
            checks["summary_min_coverage_items"] = True
    else:
        cov_valid = False
    # exclusions
    exc_valid = True
    exc_ids_exist = True
    exclusions = data.get("exclusions") if isinstance(data, dict) else None
    exc_count = 0
    if isinstance(exclusions, list) and len(exclusions) > 0:
        for ex in exclusions:
            if not isinstance(ex, dict):
                exc_valid = False
                continue
            if "item" not in ex:
                exc_valid = False
            tids = get_trace_ids_from_obj(ex)
            if len(tids) == 0:
                exc_valid = False
            else:
                for tid in tids:
                    if tid not in trace_id_map:
                        exc_ids_exist = False
            exc_count += 1
        if exc_valid:
            checks["summary_exclusions_entries_valid"] = True
        if exc_count >= 5:
            checks["summary_min_exclusions_count"] = True
    else:
        exc_valid = False
    # glossary
    glossary = data.get("glossary") if isinstance(data, dict) else None
    gl_valid = True
    gl_ids_exist = True
    if isinstance(glossary, list) and len(glossary) > 0:
        for gl in glossary:
            if not isinstance(gl, dict):
                gl_valid = False
                continue
            if "term" not in gl or "definition" not in gl:
                gl_valid = False
            tids = get_trace_ids_from_obj(gl)
            if len(tids) == 0:
                gl_valid = False
            else:
                for tid in tids:
                    if tid not in trace_id_map:
                        gl_ids_exist = False
        if gl_valid:
            checks["summary_glossary_entries_valid"] = True
    else:
        gl_valid = False
    # premiums type already checked as part of structure, but set explicit flag
    if isinstance(data.get("premiums"), list) or isinstance(data.get("premiums"), dict):
        checks["summary_premiums_type_valid"] = True
    # claim_limits type
    if isinstance(data.get("claim_limits"), list):
        checks["summary_claim_limits_type_valid"] = True
    # waiting periods type
    if isinstance(data.get("waiting_periods"), list):
        checks["summary_waiting_periods_type_valid"] = True
    # endorsements type
    if isinstance(data.get("endorsements"), list):
        checks["summary_endorsements_type_valid"] = True
    # effective dates
    eff = data.get("effective_dates") if isinstance(data, dict) else None
    if isinstance(eff, dict) and "start" in eff and "end" in eff and isinstance(eff.get("start"), str) and isinstance(eff.get("end"), str):
        checks["summary_effective_dates_valid"] = True
    # policy names
    pn = data.get("policy_names") if isinstance(data, dict) else None
    if isinstance(pn, list) and len(pn) > 0:
        checks["summary_policy_names_valid"] = True
    # trace ids existence
    checks["summary_trace_ids_exist"] = cov_ids_exist and exc_ids_exist and gl_ids_exist and cov_valid and exc_valid and gl_valid
    return checks

def validate_answers_csv(answers_path, questions_path, trace_id_map):
    checks = {
        "answers_header_valid": False,
        "answers_row_count_sufficient": False,
        "answers_rows_valid": False,
    }
    header, rows = read_csv_rows(answers_path)
    if header is None or rows is None:
        return checks
    expected_header = ["question_id", "question_text", "answer", "explanation", "confidence", "clause_refs"]
    if header == expected_header:
        checks["answers_header_valid"] = True
    # row count
    question_count = parse_questions_count(questions_path)
    if len(rows) >= question_count and question_count > 0:
        checks["answers_row_count_sufficient"] = True
    # row validations
    valid = True
    allowed_answers = {"Yes", "No", "Depends"}
    allowed_conf = {"High", "Medium", "Low"}
    for row in rows:
        if len(row) != 6:
            valid = False
            break
        qid, qtext, ans, expl, conf, refs = row
        if ans not in allowed_answers:
            valid = False
            break
        if not isinstance(expl, str) or expl.strip() == "":
            valid = False
            break
        if conf not in allowed_conf:
            valid = False
            break
        if not isinstance(refs, str) or refs.strip() == "":
            valid = False
            break
        ids = [x.strip() for x in refs.split(";") if x.strip() != ""]
        if len(ids) == 0:
            valid = False
            break
        for tid in ids:
            if tid not in trace_id_map:
                valid = False
                break
        if not valid:
            break
    if valid and len(rows) > 0:
        checks["answers_rows_valid"] = True
    return checks

def validate_gaps_md(gaps_path, trace_id_map):
    checks = {
        "gaps_has_three": False,
        "gaps_evidence_with_trace_and_quote": False,
        "gaps_actions_present": False,
        "gaps_disclaimer_present": False,
    }
    text = load_text(gaps_path)
    if text is None:
        return checks
    sections = split_sections_by_gaps(text)
    if len(sections) >= 3:
        checks["gaps_has_three"] = True
    # evidence and action per section
    all_have_evidence = True
    all_have_action = True
    for sec in sections:
        evidence_lines = [ln for ln in sec if ln.strip().startswith("Evidence:")]
        if len(evidence_lines) == 0:
            all_have_evidence = False
        else:
            # must list one or more trace_ids and include a quoted snippet
            ev_ok = False
            for ln in evidence_lines:
                # check quoted snippet
                has_quote = '"' in ln
                # check at least one known trace id in the line
                found_ids = collect_trace_ids_from_text(ln, set(trace_id_map.keys()))
                if has_quote and len(found_ids) > 0:
                    ev_ok = True
                    break
            if not ev_ok:
                all_have_evidence = False
        action_lines = [ln for ln in sec if ln.strip().startswith("Action:")]
        if len(action_lines) == 0:
            all_have_action = False
        else:
            # require some content after colon
            content_ok = any(len(ln.split(":", 1)[1].strip()) >= 5 for ln in action_lines if ":" in ln)
            if not content_ok:
                all_have_action = False
    if sections and all_have_evidence:
        checks["gaps_evidence_with_trace_and_quote"] = True
    if sections and all_have_action:
        checks["gaps_actions_present"] = True
    # disclaimer
    if end_with_exact_disclaimer(text, "This is not legal advice."):
        checks["gaps_disclaimer_present"] = True
    return checks

def validate_broker_md(broker_path):
    checks = {
        "broker_sections_present": False,
        "broker_questions_at_least_eight": False,
        "broker_disclaimer_present": False,
    }
    text = load_text(broker_path)
    if text is None:
        return checks
    has_cov = "## Coverage Clarifications" in text
    has_changes = "## Policy Changes" in text
    if has_cov and has_changes:
        checks["broker_sections_present"] = True
    # questions count: lines ending with '?'
    q_lines = set()
    for ln in text.splitlines():
        s = ln.strip()
        if s.endswith("?"):
            q_lines.add(s)
    if len(q_lines) >= 8:
        checks["broker_questions_at_least_eight"] = True
    if end_with_exact_disclaimer(text, "This is not legal advice."):
        checks["broker_disclaimer_present"] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    summary_path = os.path.join(output_dir, "summary.json")
    answers_path = os.path.join(output_dir, "answers.csv")
    gaps_path = os.path.join(output_dir, "gaps.md")
    broker_path = os.path.join(output_dir, "broker_followup.md")
    trace_path = os.path.join(output_dir, "trace.jsonl")
    questions_path = os.path.join(input_dir, "questions.json")

    checks = {}

    checks["has_summary_json"] = os.path.isfile(summary_path)
    checks["has_answers_csv"] = os.path.isfile(answers_path)
    checks["has_gaps_md"] = os.path.isfile(gaps_path)
    checks["has_broker_followup_md"] = os.path.isfile(broker_path)
    checks["has_trace_jsonl"] = os.path.isfile(trace_path)
    checks["all_outputs_present"] = all([checks["has_summary_json"], checks["has_answers_csv"], checks["has_gaps_md"], checks["has_broker_followup_md"], checks["has_trace_jsonl"]])

    # Initialize artifact-dependent checks to False
    summary_checks_defaults = {
        "summary_structure_valid": False,
        "summary_coverage_entries_valid": False,
        "summary_min_coverage_items": False,
        "summary_exclusions_entries_valid": False,
        "summary_min_exclusions_count": False,
        "summary_glossary_entries_valid": False,
        "summary_premiums_type_valid": False,
        "summary_claim_limits_type_valid": False,
        "summary_waiting_periods_type_valid": False,
        "summary_endorsements_type_valid": False,
        "summary_effective_dates_valid": False,
        "summary_policy_names_valid": False,
        "summary_trace_ids_exist": False,
    }
    checks.update(summary_checks_defaults)

    answers_checks_defaults = {
        "answers_header_valid": False,
        "answers_row_count_sufficient": False,
        "answers_rows_valid": False,
    }
    checks.update(answers_checks_defaults)

    gaps_checks_defaults = {
        "gaps_has_three": False,
        "gaps_evidence_with_trace_and_quote": False,
        "gaps_actions_present": False,
        "gaps_disclaimer_present": False,
    }
    checks.update(gaps_checks_defaults)

    broker_checks_defaults = {
        "broker_sections_present": False,
        "broker_questions_at_least_eight": False,
        "broker_disclaimer_present": False,
    }
    checks.update(broker_checks_defaults)

    trace_checks_defaults = {
        "trace_lines_structure_valid": False,
        "trace_tags_valid": False,
        "trace_ids_unique": False,
        "trace_source_and_snippet_valid": False,
    }
    checks.update(trace_checks_defaults)

    trace_struct_ok = False
    trace_tags_ok = False
    trace_unique_ok = False
    trace_src_snip_ok = False
    trace_id_map = {}

    # Validate trace.jsonl first if present
    if checks["has_trace_jsonl"]:
        t_struct, t_tags, t_uniq, t_src_snip, traces, id_map = validate_trace_jsonl(trace_path, input_dir)
        checks["trace_lines_structure_valid"] = t_struct
        checks["trace_tags_valid"] = t_tags
        checks["trace_ids_unique"] = t_uniq
        checks["trace_source_and_snippet_valid"] = t_src_snip
        trace_struct_ok = t_struct
        trace_tags_ok = t_tags
        trace_unique_ok = t_uniq
        trace_src_snip_ok = t_src_snip
        trace_id_map = id_map

    # summary.json validation (depends on summary file existing)
    if checks["has_summary_json"]:
        s_checks = validate_summary_json(summary_path, trace_id_map)
        checks.update(s_checks)

    # answers.csv validation
    if checks["has_answers_csv"]:
        a_checks = validate_answers_csv(answers_path, questions_path, trace_id_map)
        checks.update(a_checks)

    # gaps.md validation
    if checks["has_gaps_md"]:
        g_checks = validate_gaps_md(gaps_path, trace_id_map)
        checks.update(g_checks)

    # broker_followup.md validation
    if checks["has_broker_followup_md"]:
        b_checks = validate_broker_md(broker_path)
        checks.update(b_checks)

    # Compute reward
    # Enforce no-op baseline: if any required output is missing, reward must be exactly 0.0
    if not checks["all_outputs_present"]:
        reward = 0.0
    else:
        # Calculate fraction of passed checks
        total = len(checks)
        passed = sum(1 for v in checks.values() if v is True)
        reward = passed / total if total > 0 else 0.0
        # Bound [0,1]
        reward = max(0.0, min(1.0, float(reward)))

    # Print JSON result
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()