import json
import os
import sys
import re

def safe_read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f.readlines()]
    except Exception:
        return None

def parse_jsonl(path):
    lines = safe_read_lines(path)
    if lines is None:
        return None, None
    objs = []
    for ln in lines:
        if not ln.strip():
            # Treat empty lines as invalid for strict JSONL in this task
            return lines, None
        try:
            obj = json.loads(ln)
        except Exception:
            return lines, None
        if not isinstance(obj, dict):
            return lines, None
        objs.append(obj)
    return lines, objs

def is_bool(v):
    return isinstance(v, bool)

def is_number(v):
    return isinstance(v, (int, float))

def has_continuation(text):
    if not isinstance(text, str):
        return False
    return re.search(r"(resume|previous|last time)", text, flags=re.IGNORECASE) is not None

def has_execution(text):
    if not isinstance(text, str):
        return False
    return re.search(r"(edit|modify|implement|design|change)", text, flags=re.IGNORECASE) is not None

def log_has_pre_execution_true(log_str):
    if not isinstance(log_str, str) or not log_str.strip():
        return False
    s = log_str
    # Case-insensitive check for a key named pre_execution_gate with a true value nearby
    return re.search(r'(?i)pre_execution_gate["\s:]*true', s) is not None

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

conversation_path = os.path.join(input_dir, "conversation.jsonl")
policy_path = os.path.join(input_dir, "policy.yaml")
trace_path = os.path.join(output_dir, "recall_trace.jsonl")
review_path = os.path.join(output_dir, "review.md")

ALLOWED_MODES = {"preflight_query", "continuation_query", "entity_query", "constraint_query"}
ALLOWED_STATUS = {"not_needed", "queried_no_hits", "queried_low_confidence", "queried_success", "query_failed"}

checks = {
    "has_recall_trace_file": False,
    "has_review_file": False,
    "recall_trace_valid_jsonl": False,
    "recall_trace_line_count_matches_input": False,
    "recall_trace_fields_valid": False,
    "compressed_items_limit_ok": False,
    "compressed_count_matches_items_len": False,
    "log_non_empty_all": False,
    "pre_execution_log_true": False,
    "policy_preflight_first_new_session_ok": False,
    "policy_continuation_mode_ok": False,
    "policy_execution_design_mode_ok": False,
    "policy_entity_mode_ok": False,
    "precedence_entity_over_constraint_ok": False,
    "skip_generic_casual_ok": False,
    "status_consistency_needed_false_ok": False,
    "review_word_count_ok": False,
    "review_contains_keywords_ok": False,
    "review_suggestions_count_ok": False,
}

# Existence checks
if os.path.isfile(trace_path):
    checks["has_recall_trace_file"] = True
if os.path.isfile(review_path):
    checks["has_review_file"] = True

# Parse inputs
conv_lines, conv_objs = parse_jsonl(conversation_path)
# Policy file is not required for scoring; read only to respect task context, no credit awarded for it
_ = safe_read_lines(policy_path)

# Parse output trace
trace_lines, trace_objs = parse_jsonl(trace_path) if checks["has_recall_trace_file"] else (None, None)
if checks["has_recall_trace_file"] and trace_lines is not None and trace_objs is not None:
    checks["recall_trace_valid_jsonl"] = True

# Line count match
if conv_lines is not None and trace_lines is not None and checks["recall_trace_valid_jsonl"]:
    if len(trace_lines) == len(conv_lines):
        checks["recall_trace_line_count_matches_input"] = True

# Validate per-line structure and policy conformance
if checks["recall_trace_line_count_matches_input"] and conv_objs is not None and trace_objs is not None:
    n = len(conv_objs)
    fields_valid_all = True
    compressed_limit_all = True
    compressed_count_match_all = True
    log_non_empty_all = True
    pre_exec_log_true_all = True  # evaluated only on turns with pre_execution true
    status_consistency_all = True

    continuation_mode_ok_all = True
    execution_design_mode_ok_all = True
    entity_mode_ok_all = True
    precedence_entity_over_constraint_all = True
    skip_generic_casual_all = True
    preflight_ok = True

    # Identify first new_session=true turn index from input conversation
    first_new_session_idx = None
    for i in range(n):
        inp = conv_objs[i]
        if isinstance(inp, dict) and bool(inp.get("new_session", False)) is True:
            first_new_session_idx = i
            break

    # Iterate and validate
    for i in range(n):
        out = trace_objs[i]
        # Top-level keys
        required_top = ["input", "recallDecision", "recallResult", "compressed", "log"]
        if not all(k in out for k in required_top):
            fields_valid_all = False
            continue  # Cannot validate more on this line

        input_obj = out["input"]
        dec = out["recallDecision"]
        res = out["recallResult"]
        comp = out["compressed"]
        log_str = out["log"]

        # Validate input sub-keys
        text = input_obj.get("text")
        intent_out = input_obj.get("intent", None)
        entities_out = input_obj.get("entities", None)
        pre_exec_out_present = "pre_execution" in input_obj
        pre_exec_out_val = input_obj.get("pre_execution", None)
        if not isinstance(text, str):
            fields_valid_all = False
        if pre_exec_out_present is False or not is_bool(pre_exec_out_val):
            fields_valid_all = False
        if entities_out is not None and not isinstance(entities_out, list):
            fields_valid_all = False
        if intent_out is not None and not isinstance(intent_out, str):
            fields_valid_all = False

        # Validate recallDecision
        needed = dec.get("needed", None)
        mode = dec.get("mode", None)
        reason = dec.get("reason", None)
        if not is_bool(needed) or mode not in ALLOWED_MODES or not isinstance(reason, str):
            fields_valid_all = False

        # Validate recallResult
        status = res.get("status", None)
        res_mode = res.get("mode", None)
        items = res.get("items", None)
        if status not in ALLOWED_STATUS or not isinstance(res_mode, str) or not isinstance(items, list):
            fields_valid_all = False

        # Validate compressed
        total_count = comp.get("totalCount", None)
        compressed_count = comp.get("compressedCount", None)
        comp_items = comp.get("items", None)
        if not is_number(total_count) or not is_number(compressed_count) or not isinstance(comp_items, list):
            fields_valid_all = False
        else:
            # items length <= 5
            if len(comp_items) > 5:
                compressed_limit_all = False
            # compressedCount equals len(items)
            if int(compressed_count) != len(comp_items):
                compressed_count_match_all = False

        # Log non-empty
        if not isinstance(log_str, str) or not log_str.strip():
            log_non_empty_all = False

        # Status consistency when needed == False
        if needed is False:
            if status != "not_needed":
                status_consistency_all = False

        # Policy checks using input conversation fields
        inp_conv = conv_objs[i]
        text_in = inp_conv.get("text", "")
        intent_in = inp_conv.get("intent", None)
        entities_in = inp_conv.get("entities", [])
        pre_exec_in = bool(inp_conv.get("pre_execution", False))

        # Pre-execution gate log check (only for true cases)
        if pre_exec_in:
            if not log_has_pre_execution_true(log_str):
                pre_exec_log_true_all = False

        # Stage 1: first new_session turn must be preflight_query and needed true
        if first_new_session_idx is not None and i == first_new_session_idx:
            if not (needed is True and mode == "preflight_query"):
                preflight_ok = False

        # Trigger detection
        cont = has_continuation(text_in)
        exe = (intent_in in {"design_request", "execution_request"}) or has_execution(text_in)
        ent = isinstance(entities_in, list) and len(entities_in) > 0

        # Stage 2 rules
        # Continuation: must be continuation_query
        if cont:
            if mode != "continuation_query":
                continuation_mode_ok_all = False

        # Execution/design: must be constraint_query when not overridden by higher precedence
        # Apply precedence: continuation > entity > constraint
        if not cont and not ent and exe:
            if mode != "constraint_query":
                execution_design_mode_ok_all = False

        # Entity trigger: when non-empty and no continuation or execution trigger, must be entity_query
        if ent and not cont and not exe:
            if mode != "entity_query":
                entity_mode_ok_all = False

        # Precedence: entity over constraint when both present and no continuation
        if not cont and ent and exe:
            if mode != "entity_query":
                precedence_entity_over_constraint_all = False

        # Skip cases: generic_qa or casual intent with no triggers and not first new_session turn
        if (intent_in in {"generic_qa", "casual"}) and (not cont and not ent and not exe):
            if first_new_session_idx is not None and i == first_new_session_idx:
                # Stage 1 overrides skip; do not enforce skip here
                pass
            else:
                if not (needed is False and status == "not_needed"):
                    skip_generic_casual_all = False

    checks["recall_trace_fields_valid"] = fields_valid_all
    checks["compressed_items_limit_ok"] = compressed_limit_all
    checks["compressed_count_matches_items_len"] = compressed_count_match_all
    checks["log_non_empty_all"] = log_non_empty_all
    checks["status_consistency_needed_false_ok"] = status_consistency_all

    # Only set pre_exec_log_true if there was at least one pre_execution=true turn; else it remains True (vacuous) should not contribute positive reward if no pre-exec turns exist.
    if conv_objs is not None:
        any_pre_exec = any(bool(obj.get("pre_execution", False)) for obj in conv_objs)
        if any_pre_exec:
            checks["pre_execution_log_true"] = pre_exec_log_true_all
        else:
            # Do not award positive credit when check does not depend on output content
            checks["pre_execution_log_true"] = False

    # Policy checks
    # Preflight only contributes if such a turn exists
    if first_new_session_idx is not None:
        checks["policy_preflight_first_new_session_ok"] = preflight_ok
    else:
        checks["policy_preflight_first_new_session_ok"] = False

    checks["policy_continuation_mode_ok"] = continuation_mode_ok_all
    checks["policy_execution_design_mode_ok"] = execution_design_mode_ok_all
    checks["policy_entity_mode_ok"] = entity_mode_ok_all
    checks["precedence_entity_over_constraint_ok"] = precedence_entity_over_constraint_all
    checks["skip_generic_casual_ok"] = skip_generic_casual_all

# Review validations
if checks["has_review_file"]:
    try:
        with open(review_path, "r", encoding="utf-8") as f:
            review_text = f.read()
        # Word count
        words = re.findall(r"\b\w+\b", review_text)
        if len(words) >= 120:
            checks["review_word_count_ok"] = True
        # Keywords
        lower = review_text.lower()
        kw_ok = ("pre-execution" in lower) and ("continuation" in lower) and ("entity" in lower) and (("compression" in lower) or ("compressed" in lower))
        if kw_ok:
            checks["review_contains_keywords_ok"] = True
        # Suggestions: at least two lines starting with bullet or number
        lines = review_text.splitlines()
        suggestion_lines = [ln for ln in lines if re.match(r"^\s*([\-*]|\d+\.)\s+", ln)]
        if len(suggestion_lines) >= 2:
            checks["review_suggestions_count_ok"] = True
    except Exception:
        # Leave review checks as False on error
        pass

# Compute reward
# No-op baseline: if outputs missing or recall trace invalid/empty, reward = 0.0
artifact_required = checks["has_recall_trace_file"] and checks["has_review_file"]
if not artifact_required or not checks["recall_trace_valid_jsonl"]:
    reward = 0.0
else:
    # Count total checks that are scored (booleans in checks)
    total = len(checks)
    passed = sum(1 for v in checks.values() if v is True)
    # Reward as ratio of passed checks
    reward = passed / total if total > 0 else 0.0
    # Bound between 0 and 1
    reward = max(0.0, min(1.0, reward))

# Print single JSON object
print(json.dumps({"reward": reward, **checks}))