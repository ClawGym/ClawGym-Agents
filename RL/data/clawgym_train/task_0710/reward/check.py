import json
import os
import re
import sys

def safe_read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def safe_read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def dir_has_files(dir_path):
    if not os.path.isdir(dir_path):
        return False
    for _, _, files in os.walk(dir_path):
        if files:
            return True
    return False

def count_words(text):
    if not text:
        return 0
    tokens = re.findall(r"\S+", text)
    return len(tokens)

def parse_entries(content, tag):
    """
    Parse entries in markdown file by header pattern and return list of segments (text per entry).
    """
    segments = []
    if not content:
        return segments
    pattern = r"^## \[" + re.escape(tag) + r"-\d{8}-[A-Za-z0-9]{3,}\]"
    matches = list(re.finditer(pattern, content, flags=re.MULTILINE))
    if not matches:
        return segments
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        segments.append(content[start:end])
    return segments

def segment_has_logged_and_status(segment):
    return ("**Logged**:" in segment) and ("**Status**:" in segment)

def error_segment_has_error_content(segment):
    # Find "### Error" and ensure at least one non-empty line follows within the segment
    m = re.search(r"^### Error\s*$", segment, flags=re.MULTILINE)
    if not m:
        return False
    post = segment[m.end():]
    # Find first non-empty line
    for line in post.splitlines():
        if line.strip() == "":
            continue
        # Any non-empty line counts as content
        return True
    return False

def feature_segment_has_requested_capability(segment):
    return "### Requested Capability" in segment

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Baseline: if output is empty or missing, reward must be 0.0
    output_has_any_files = dir_has_files(output_dir)

    # 1) Facts checks
    facts_path = os.path.join(output_dir, "memento", "facts.json")
    checks["facts_file_exists"] = False
    checks["facts_valid_json_array"] = False
    checks["facts_min_count"] = False
    checks["facts_fields_valid"] = False
    checks["facts_has_update_field"] = False
    checks["facts_has_secret_fact"] = False

    facts = None
    if os.path.isfile(facts_path):
        checks["facts_file_exists"] = True
        facts = safe_read_json(facts_path)
        if isinstance(facts, list):
            checks["facts_valid_json_array"] = True
            if len(facts) >= 6:
                checks["facts_min_count"] = True
            # Validate fields for all facts
            required_ok_all = True
            has_update_field = False
            has_secret = False
            for fact in facts:
                if not isinstance(fact, dict):
                    required_ok_all = False
                    break
                content = fact.get("content")
                category = fact.get("category")
                visibility = fact.get("visibility")
                confidence = fact.get("confidence")
                occurrence_count = fact.get("occurrence_count")
                first_seen_at = fact.get("first_seen_at")
                last_seen_at = fact.get("last_seen_at")

                content_ok = isinstance(content, str) and len(content) >= 10
                category_ok = category in {"preference", "decision", "person", "action_item"}
                visibility_ok = visibility in {"shared", "private", "secret"}
                confidence_ok = isinstance(confidence, (int, float))
                occ_ok = isinstance(occurrence_count, int) and occurrence_count >= 1
                first_ok = isinstance(first_seen_at, (int, float))
                last_ok = isinstance(last_seen_at, (int, float))

                if not (content_ok and category_ok and visibility_ok and confidence_ok and occ_ok and first_ok and last_ok):
                    required_ok_all = False
                    break

                if isinstance(fact.get("previous_value"), str) and fact.get("previous_value"):
                    has_update_field = True
                if isinstance(fact.get("supersedes"), str) and fact.get("supersedes"):
                    has_update_field = True

                if visibility == "secret":
                    has_secret = True

            if required_ok_all:
                checks["facts_fields_valid"] = True
            if has_update_field:
                checks["facts_has_update_field"] = True
            if has_secret:
                checks["facts_has_secret_fact"] = True

    # 2) Recall checks
    recall_path = os.path.join(output_dir, "memento", "recall.md")
    checks["recall_file_exists"] = False
    checks["recall_length_ok"] = False
    checks["recall_secret_line_present"] = False
    checks["recall_secret_count_matches"] = False
    checks["recall_excludes_secret_content"] = False
    checks["recall_has_causal_keyword"] = False

    recall_text = None
    if os.path.isfile(recall_path):
        checks["recall_file_exists"] = True
        recall_text = safe_read_text(recall_path)
        if recall_text is not None and len(recall_text) >= 200:
            checks["recall_length_ok"] = True
        # Secret line exact prefix and integer
        secret_line_match = None
        if recall_text:
            for line in recall_text.splitlines():
                m = re.match(r"^Secret facts excluded: (\d+)\s*$", line.strip())
                if m:
                    secret_line_match = m
                    break
        if secret_line_match:
            checks["recall_secret_line_present"] = True
            try:
                excluded_count = int(secret_line_match.group(1))
            except Exception:
                excluded_count = None
            # Compare with count of secret facts from facts.json
            if facts and isinstance(facts, list):
                secret_count = sum(1 for f in facts if isinstance(f, dict) and f.get("visibility") == "secret")
                if excluded_count == secret_count:
                    checks["recall_secret_count_matches"] = True
                # Ensure recall does not contain full content of any secret fact (case-insensitive)
                recall_lower = recall_text.lower()
                excludes_all = True
                for f in facts:
                    if isinstance(f, dict) and f.get("visibility") == "secret":
                        sc = f.get("content")
                        if isinstance(sc, str) and sc.strip():
                            if sc.lower() in recall_lower:
                                excludes_all = False
                                break
                if excludes_all:
                    checks["recall_excludes_secret_content"] = True
        # causal keywords
        if recall_text and ("caused_by" in recall_text or "precondition_of" in recall_text):
            checks["recall_has_causal_keyword"] = True

    # 3) Injection checks
    injection_path = os.path.join(output_dir, "config", "injection.json")
    injected_msgs_path = os.path.join(output_dir, "injected", "messages.txt")
    sample_msgs_input_path = os.path.join(input_dir, "sample_user_messages.txt")

    checks["injection_json_valid"] = False
    checks["injection_enabled_true"] = False
    checks["injection_prependText_len_ok"] = False
    checks["injected_messages_file_exists"] = False
    checks["injected_messages_line_count_match"] = False
    checks["injected_lines_prefixed_correctly"] = False

    prepend_text = None
    inj = None
    if os.path.isfile(injection_path):
        inj = safe_read_json(injection_path)
        if isinstance(inj, dict) and "enabled" in inj and "prependText" in inj:
            checks["injection_json_valid"] = True
            if inj.get("enabled") is True:
                checks["injection_enabled_true"] = True
            pt = inj.get("prependText")
            if isinstance(pt, str) and len(pt) >= 40:
                checks["injection_prependText_len_ok"] = True
            if isinstance(pt, str):
                prepend_text = pt

    if os.path.isfile(injected_msgs_path):
        checks["injected_messages_file_exists"] = True
        injected_text = safe_read_text(injected_msgs_path)
        injected_lines = injected_text.splitlines() if injected_text is not None else []
        sample_text = safe_read_text(sample_msgs_input_path)
        sample_lines = sample_text.splitlines() if sample_text is not None else []
        if sample_lines and len(injected_lines) == len(sample_lines):
            checks["injected_messages_line_count_match"] = True
        # All lines must start with exact prependText
        if prepend_text is not None and injected_lines:
            prefix_ok = True
            for line in injected_lines:
                if not line.startswith(prepend_text):
                    prefix_ok = False
                    break
            if prefix_ok:
                checks["injected_lines_prefixed_correctly"] = True

    # 4) Interview checks
    scorecard_path = os.path.join(output_dir, "interview", "scorecard.json")
    thankyou_path = os.path.join(output_dir, "interview", "thank_you_email.md")

    checks["scorecard_json_valid"] = False
    checks["scorecard_overall_score_in_range"] = False
    checks["scorecard_rounds_valid"] = False
    checks["scorecard_strengths_min1"] = False
    checks["scorecard_improvements_min3"] = False
    checks["thankyou_email_exists"] = False
    checks["thankyou_subject_line_present"] = False
    checks["thankyou_word_count_ok"] = False

    scorecard = None
    if os.path.isfile(scorecard_path):
        scorecard = safe_read_json(scorecard_path)
        if isinstance(scorecard, dict):
            checks["scorecard_json_valid"] = True
            overall = scorecard.get("overall_score")
            if isinstance(overall, int) and 0 <= overall <= 100:
                checks["scorecard_overall_score_in_range"] = True
            rounds = scorecard.get("rounds")
            if isinstance(rounds, list) and len(rounds) >= 2:
                rounds_ok = True
                for r in rounds:
                    if not isinstance(r, dict):
                        rounds_ok = False
                        break
                    name = r.get("name")
                    score = r.get("score")
                    if not (isinstance(name, str) and isinstance(score, int) and 0 <= score <= 100):
                        rounds_ok = False
                        break
                if rounds_ok:
                    checks["scorecard_rounds_valid"] = True
            strengths = scorecard.get("strengths")
            if isinstance(strengths, list) and len(strengths) >= 1:
                checks["scorecard_strengths_min1"] = True
            improvements = scorecard.get("improvements")
            if isinstance(improvements, list) and len(improvements) >= 3:
                checks["scorecard_improvements_min3"] = True

    if os.path.isfile(thankyou_path):
        checks["thankyou_email_exists"] = True
        email_text = safe_read_text(thankyou_path) or ""
        # Subject line requirement
        subject_present = any(line.startswith("Subject:") for line in email_text.splitlines())
        if subject_present:
            checks["thankyou_subject_line_present"] = True
        if count_words(email_text) >= 80:
            checks["thankyou_word_count_ok"] = True

    # 5) Self-improvement logs
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    feature_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")

    checks["learnings_file_exists_and_valid_entry"] = False
    checks["errors_file_exists_and_valid_entry"] = False
    checks["feature_file_exists_and_valid_entry"] = False
    checks["errors_has_error_section_content"] = False
    checks["feature_has_requested_capability_section"] = False

    # LEARNINGS
    if os.path.isfile(learnings_path):
        learnings_text = safe_read_text(learnings_path) or ""
        segments = parse_entries(learnings_text, "LRN")
        valid_segment_found = False
        for seg in segments:
            if segment_has_logged_and_status(seg):
                valid_segment_found = True
                break
        if segments and valid_segment_found:
            checks["learnings_file_exists_and_valid_entry"] = True

    # ERRORS
    if os.path.isfile(errors_path):
        errors_text = safe_read_text(errors_path) or ""
        segments = parse_entries(errors_text, "ERR")
        valid_segment_found = False
        error_content_found = False
        for seg in segments:
            if segment_has_logged_and_status(seg):
                valid_segment_found = True
            if error_segment_has_error_content(seg):
                error_content_found = True
        if segments and valid_segment_found:
            checks["errors_file_exists_and_valid_entry"] = True
        if error_content_found:
            checks["errors_has_error_section_content"] = True

    # FEATURE REQUESTS
    if os.path.isfile(feature_path):
        feature_text = safe_read_text(feature_path) or ""
        segments = parse_entries(feature_text, "FEAT")
        valid_segment_found = False
        requested_section_present = False
        for seg in segments:
            if segment_has_logged_and_status(seg):
                valid_segment_found = True
            if feature_segment_has_requested_capability(seg):
                requested_section_present = True
        if segments and valid_segment_found:
            checks["feature_file_exists_and_valid_entry"] = True
        if requested_section_present:
            checks["feature_has_requested_capability_section"] = True

    # Rubric-related presence/format signals (do not contribute to reward)
    checks["rubric_recall_tailored_format"] = False
    checks["rubric_scorecard_rounds_named"] = False
    checks["rubric_thankyou_professional_personalization"] = False

    if recall_text:
        # Tailored format hint: contains words related to interview prep
        lowered = recall_text.lower()
        if any(w in lowered for w in ["interview", "practice", "prep"]):
            checks["rubric_recall_tailored_format"] = True

    if isinstance(scorecard, dict):
        rounds = scorecard.get("rounds")
        if isinstance(rounds, list):
            names = [r.get("name") for r in rounds if isinstance(r, dict) and isinstance(r.get("name"), str)]
            if len(set(names)) >= 2:
                checks["rubric_scorecard_rounds_named"] = True

    if os.path.isfile(thankyou_path):
        email_text = safe_read_text(thankyou_path) or ""
        if ("Subject:" in email_text) and ("[" in email_text or "]" in email_text):
            checks["rubric_thankyou_professional_personalization"] = True

    # Compute reward from objective checks only
    objective_keys = [
        "facts_file_exists",
        "facts_valid_json_array",
        "facts_min_count",
        "facts_fields_valid",
        "facts_has_update_field",
        "facts_has_secret_fact",
        "recall_file_exists",
        "recall_length_ok",
        "recall_secret_line_present",
        "recall_secret_count_matches",
        "recall_excludes_secret_content",
        "recall_has_causal_keyword",
        "injection_json_valid",
        "injection_enabled_true",
        "injection_prependText_len_ok",
        "injected_messages_file_exists",
        "injected_messages_line_count_match",
        "injected_lines_prefixed_correctly",
        "scorecard_json_valid",
        "scorecard_overall_score_in_range",
        "scorecard_rounds_valid",
        "scorecard_strengths_min1",
        "scorecard_improvements_min3",
        "thankyou_email_exists",
        "thankyou_subject_line_present",
        "thankyou_word_count_ok",
        "learnings_file_exists_and_valid_entry",
        "errors_file_exists_and_valid_entry",
        "feature_file_exists_and_valid_entry",
        "errors_has_error_section_content",
        "feature_has_requested_capability_section",
    ]

    passed = sum(1 for k in objective_keys if checks.get(k) is True)
    total = len(objective_keys)

    if not output_has_any_files:
        reward = 0.0
    else:
        reward = (passed / total) if total > 0 else 0.0

    # Clamp reward between 0 and 1
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()