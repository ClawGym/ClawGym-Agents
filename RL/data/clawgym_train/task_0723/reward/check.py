import json
import os
import re
import sys
from datetime import datetime

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def detect_word_range(constraints_text):
    if not constraints_text or not isinstance(constraints_text, str):
        return None
    txt = constraints_text.lower()
    # Patterns like "600-1000 words"
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*words", txt)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a < b:
            return (a, b)
    # Patterns like "between 600 and 1000 words" or "600 to 1000 words"
    m = re.search(r"(between\s+)?(\d+)\s*(?:and|to)\s*(\d+)\s*words", txt)
    if m:
        a, b = int(m.group(2)), int(m.group(3))
        if a < b:
            return (a, b)
    return None

def parse_sections(text):
    # Expect exact headings in order: Final Answer, Key Improvements from Critique, Uncertainties, Next Steps (optional)
    lines = text.splitlines()
    headers = ["Final Answer", "Key Improvements from Critique", "Uncertainties", "Next Steps"]
    positions = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped in headers and stripped not in positions:
            positions[stripped] = idx
    # Must have first three in order
    required = ["Final Answer", "Key Improvements from Critique", "Uncertainties"]
    for i, h in enumerate(required):
        if h not in positions:
            return None
    if not (positions["Final Answer"] < positions["Key Improvements from Critique"] < positions["Uncertainties"]):
        return None
    # If Next Steps present, it must be after Uncertainties
    if "Next Steps" in positions:
        if not (positions["Uncertainties"] < positions["Next Steps"]):
            return None
    # Extract bodies
    def body_between(start_idx, end_idx):
        segment = lines[start_idx+1:end_idx]
        return "\n".join(segment).strip()
    end_after_final = positions["Key Improvements from Critique"]
    end_after_improvements = positions["Uncertainties"]
    end_after_uncertainties = positions["Next Steps"] if "Next Steps" in positions else len(lines)
    final_answer_body = body_between(positions["Final Answer"], end_after_final)
    improvements_body = body_between(positions["Key Improvements from Critique"], end_after_improvements)
    uncertainties_body = body_between(positions["Uncertainties"], end_after_uncertainties if "Next Steps" not in positions else positions["Next Steps"])
    next_steps_body = ""
    if "Next Steps" in positions:
        next_steps_body = "\n".join(lines[positions["Next Steps"]+1:]).strip()
    return {
        "final": final_answer_body,
        "improvements": improvements_body,
        "uncertainties": uncertainties_body,
        "next_steps": next_steps_body,
        "has_next_steps": "Next Steps" in positions,
    }

def count_bullets(text, min_len=1):
    if not text:
        return 0
    count = 0
    for line in text.splitlines():
        s = line.strip()
        if (s.startswith("-") or s.startswith("*")) and len(s.strip("-* ").strip()) >= min_len:
            count += 1
    return count

def word_count(text):
    # Count words with alphabetic tokens
    tokens = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)
    return len(tokens)

def is_englishish(text):
    if not text:
        return False
    total = len(text)
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    ascii_ratio = ascii_chars / max(1, total)
    alpha_words = len(re.findall(r"[A-Za-z]+", text))
    return ascii_ratio >= 0.5 and alpha_words >= 100

def iso_like(s):
    if not isinstance(s, str):
        return False
    # Basic ISO-8601-like pattern YYYY-MM-DDThh:mm
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", s))

def float_close(a, b, tol=0.02):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_final_txt": False,
        "has_run_json": False,
        "final_sections_ok": False,
        "final_word_count_ok": False,
        "final_english_ok": False,
        "improvements_bullets_ok": False,
        "uncertainties_bullets_ok": False,
        "improvements_mentions_critique": False,
        "run_schema_fields_ok": False,
        "question_match": False,
        "models_count_ok": False,
        "models_schema_ok": False,
        "weighted_scores_ok": False,
        "final_obj_ok": False,
        "ops_ok": False,
        "timestamps_ok": False,
        "status_failure_noted": False,
        "rubric_weighting_present": False,
    }

    # Load input for reference (question, constraints, models, ops)
    request_path = os.path.join(input_dir, "request.json")
    request = load_json(request_path) or {}
    input_question = request.get("question")
    input_constraints = request.get("constraints", "")
    input_models = request.get("models", [])
    input_complex = request.get("complex", None)
    # Determine expected word range for Final Answer
    detected_range = detect_word_range(input_constraints)
    if detected_range is None:
        # Default range when not specified
        min_words, max_words = 400, 1500
    else:
        min_words, max_words = detected_range

    # Check files existence
    final_txt_path = os.path.join(output_dir, "final.txt")
    run_json_path = os.path.join(output_dir, "run.json")

    final_txt = None
    if os.path.isfile(final_txt_path):
        checks["has_final_txt"] = True
        final_txt = read_text(final_txt_path)

    run_obj = None
    run_raw = None
    if os.path.isfile(run_json_path):
        run_raw = read_text(run_json_path)
        if run_raw is not None:
            run_obj = load_json(run_json_path)
            if run_obj is not None:
                checks["has_run_json"] = True

    # If either file missing, reward must be 0.0
    if not (checks["has_final_txt"] and checks["has_run_json"]):
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Parse final.txt sections
    sections = parse_sections(final_txt) if isinstance(final_txt, str) else None
    if sections is not None:
        checks["final_sections_ok"] = True
        # Word count check for Final Answer
        fa_words = word_count(sections.get("final", ""))
        if min_words <= fa_words <= max_words:
            checks["final_word_count_ok"] = True
        # English-ish check
        if is_englishish(sections.get("final", "")):
            checks["final_english_ok"] = True
        # Bullets count
        if count_bullets(sections.get("improvements", ""), min_len=1) >= 3:
            checks["improvements_bullets_ok"] = True
        if count_bullets(sections.get("uncertainties", ""), min_len=1) >= 2:
            checks["uncertainties_bullets_ok"] = True
        # Cross-critique references
        imp_lower = sections.get("improvements", "").lower()
        critique_terms = ["critique", "peer", "feedback", "revision", "synthesis", "cross-critique"]
        if any(term in imp_lower for term in critique_terms):
            checks["improvements_mentions_critique"] = True

    # Validate run.json schema presence
    # Top-level fields
    top_ok = (
        isinstance(run_obj, dict)
        and isinstance(run_obj.get("schemaVersion"), str)
        and isinstance(run_obj.get("question"), str)
        and isinstance(run_obj.get("models"), list)
        and isinstance(run_obj.get("final"), dict)
        and isinstance(run_obj.get("ops"), dict)
        and isinstance(run_obj.get("timestamps"), dict)
    )
    if top_ok:
        checks["run_schema_fields_ok"] = True

    # Question match
    if isinstance(input_question, str) and run_obj and run_obj.get("question") == input_question:
        checks["question_match"] = True

    # Models count and schema
    models = run_obj.get("models") if isinstance(run_obj, dict) else []
    # Determine required minimum count
    declared_models_count = len(input_models) if isinstance(input_models, list) else 0
    if input_complex is True:
        required_min = min(3, declared_models_count) if declared_models_count > 0 else 3
    else:
        # If not complex true, allow any count (including zero) for the abort case
        required_min = 0
    if isinstance(models, list) and len(models) >= required_min:
        checks["models_count_ok"] = True

    models_schema_ok = True
    weighted_scores_ok = True
    any_failed = False

    if isinstance(models, list):
        for m in models:
            # Validate per-model schema
            if not isinstance(m, dict):
                models_schema_ok = False
                break
            agentId = m.get("agentId")
            status = m.get("status")
            scores = m.get("scores")
            if not isinstance(agentId, str) or not agentId:
                models_schema_ok = False
                break
            if status not in ("ok", "failed"):
                models_schema_ok = False
                break
            if status == "ok":
                # Require draft, critique, revised non-empty strings
                if not (isinstance(m.get("draft"), str) and m.get("draft").strip()):
                    models_schema_ok = False
                    break
                if not (isinstance(m.get("critique"), str) and m.get("critique").strip()):
                    models_schema_ok = False
                    break
                if not (isinstance(m.get("revised"), str) and m.get("revised").strip()):
                    models_schema_ok = False
                    break
            else:
                any_failed = True
                if not (isinstance(m.get("error"), str) and m.get("error").strip()):
                    models_schema_ok = False
                    break
            # Scores check
            if not isinstance(scores, dict):
                models_schema_ok = False
                break
            ints_ok = True
            for k in ["accuracy", "coverage", "evidence", "actionability"]:
                v = scores.get(k)
                if not (isinstance(v, int) and 1 <= v <= 5):
                    ints_ok = False
                    break
            if not ints_ok:
                models_schema_ok = False
                break
            weighted = scores.get("weighted")
            try:
                weighted_val = float(weighted)
            except Exception:
                weighted_scores_ok = False
                continue
            a = scores.get("accuracy")
            c = scores.get("coverage")
            e = scores.get("evidence")
            act = scores.get("actionability")
            expected = 0.40 * a + 0.25 * c + 0.20 * e + 0.15 * act
            if not float_close(weighted_val, expected, tol=0.02):
                weighted_scores_ok = False

    if models_schema_ok:
        checks["models_schema_ok"] = True
    if weighted_scores_ok:
        checks["weighted_scores_ok"] = True

    # final object checks
    final_obj = run_obj.get("final", {}) if isinstance(run_obj, dict) else {}
    final_ok = (
        isinstance(final_obj, dict)
        and isinstance(final_obj.get("answer"), str)
        and isinstance(final_obj.get("keyImprovements"), list)
        and len(final_obj.get("keyImprovements")) >= 3
        and isinstance(final_obj.get("uncertainties"), list)
        and len(final_obj.get("uncertainties")) >= 2
        and (final_obj.get("nextSteps") is None or isinstance(final_obj.get("nextSteps"), list))
        and final_obj.get("confidence") in ("low", "medium", "high")
    )
    if final_ok:
        checks["final_obj_ok"] = True

    # ops checks
    ops = run_obj.get("ops", {}) if isinstance(run_obj, dict) else {}
    ops_ok = (
        isinstance(ops, dict)
        and isinstance(ops.get("timeoutSec"), int)
        and isinstance(ops.get("maxRetries"), int)
        and ops.get("maxRounds") == 4
        and (ops.get("budgetUsd") is None or isinstance(ops.get("budgetUsd"), (int, float)))
    )
    if ops_ok:
        checks["ops_ok"] = True

    # timestamps checks
    timestamps = run_obj.get("timestamps", {}) if isinstance(run_obj, dict) else {}
    ts_ok = (
        isinstance(timestamps, dict)
        and iso_like(timestamps.get("startedAt"))
        and iso_like(timestamps.get("finishedAt"))
    )
    if ts_ok:
        checks["timestamps_ok"] = True

    # Failure noted in final.txt if any model failed
    if any_failed:
        lower_final = final_txt.lower() if isinstance(final_txt, str) else ""
        if any(term in lower_final for term in ["failed", "reduced", "fewer"]):
            checks["status_failure_noted"] = True
    else:
        # If no failures, consider this check as not required. Leave as False but not penalize extra?
        # It will be part of the overall fraction; lack of failures means we cannot require a note.
        # To avoid penalizing, mark as True when no failures.
        checks["status_failure_noted"] = True

    # Rubric weighting presence: either weights mentioned in files or formula validated for all models
    mentioned = False
    weights_terms = ["0.40", "0.25", "0.20", "0.15"]
    combined_text = (final_txt or "") + "\n" + (run_raw or "")
    if all(w in combined_text for w in weights_terms):
        mentioned = True
    if mentioned or checks["weighted_scores_ok"]:
        checks["rubric_weighting_present"] = True

    # Compute reward: if missing required outputs, already returned 0. Else average of checks.
    # Exclude has_final_txt and has_run_json from denominator? Include them; they're already True here.
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0
    # Clamp
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()