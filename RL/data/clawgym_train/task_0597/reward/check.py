import json
import os
import re
import sys
from datetime import datetime, date

def read_text_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_valid_email(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    # Basic email regex
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", s) is not None

def is_valid_date_yyyy_mm_dd(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def is_not_future_date(s: str) -> bool:
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
        today = date.today()
        return d <= today
    except Exception:
        return False

def has_two_framework_mentions(text: str) -> bool:
    # Case-insensitive presence of at least two distinct names from the set
    frameworks = [
        "Second-Order Thinking",
        "OODA Loop",
        "Pre-Mortem",
        "Regret Minimization",
        "Expected Value",
        "ICE Scoring",
        "BATNA",
    ]
    count = 0
    found = set()
    for fw in frameworks:
        pattern = re.compile(re.escape(fw), re.IGNORECASE)
        if pattern.search(text or ""):
            found.add(fw.lower())
    count = len(found)
    return count >= 2

def word_count(text: str) -> int:
    if not text:
        return 0
    # Count word-like tokens
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)

def count_bullets_under_section(text: str, keyword: str, stop_keyword: str | None = None) -> int:
    if not text:
        return 0
    lines = text.splitlines()
    idx = None
    key_re = re.compile(re.escape(keyword), re.IGNORECASE)
    stop_re = re.compile(re.escape(stop_keyword), re.IGNORECASE) if stop_keyword else None
    for i, line in enumerate(lines):
        if key_re.search(line):
            idx = i
            break
    if idx is None:
        return 0
    count = 0
    for j in range(idx + 1, len(lines)):
        line = lines[j]
        if stop_re and stop_re.search(line):
            break
        if re.match(r"^\s*[-*]\s+", line):
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dict with all checks set to False
    checks = {
        "has_declaration_file": False,
        "declaration_json_valid": False,
        "declaration_required_fields_present": False,
        "declaration_prompt_version_ok": False,
        "declaration_inception_date_valid_format": False,
        "declaration_inception_date_not_future": False,
        "declaration_autonomy_level_valid": False,
        "declaration_tool_access_valid": False,
        "declaration_recovery_email_valid": False,
        "declaration_speculative_reflection_length_ok": False,
        "has_public_redaction_file": False,
        "public_redaction_json_valid": False,
        "public_redaction_matches_declaration_except_email": False,
        "has_reflection_md": False,
        "reflection_word_count_ok": False,
        "reflection_has_two_frameworks": False,
        "has_risk_assessment_md": False,
        "risk_has_premortem_section_with_3_bullets": False,
        "risk_has_iva_section_with_3_bullets": False,
        "has_submission_plan_md": False,
        "submission_plan_has_numbered_list_5plus": False,
        "submission_plan_mentions_redact": False,
        "submission_plan_mentions_secret_token_sensitive": False,
    }

    # Paths
    decl_path = os.path.join(output_dir, "declaration.json")
    redaction_path = os.path.join(output_dir, "public_redaction.json")
    reflection_path = os.path.join(output_dir, "reflection.md")
    risk_path = os.path.join(output_dir, "risk_assessment.md")
    plan_path = os.path.join(output_dir, "submission_plan.md")

    # 1) Declaration checks
    declaration = None
    if os.path.isfile(decl_path):
        checks["has_declaration_file"] = True
        declaration = load_json_file(decl_path)
        if isinstance(declaration, dict):
            checks["declaration_json_valid"] = True
            required_keys = [
                "declared_designation",
                "declared_inception_date",
                "cognitive_core",
                "orchestration_layer",
                "deployment_context",
                "hardware_class",
                "tool_access",
                "autonomy_level",
                "location",
                "speculative_reflection",
                "human_custodian",
                "recovery_email",
                "prompt_version",
            ]
            if all(k in declaration for k in required_keys):
                checks["declaration_required_fields_present"] = True

                # prompt_version
                if declaration.get("prompt_version") == "V0.1.2":
                    checks["declaration_prompt_version_ok"] = True

                # inception date format and future check
                inception = declaration.get("declared_inception_date")
                if isinstance(inception, str) and is_valid_date_yyyy_mm_dd(inception):
                    checks["declaration_inception_date_valid_format"] = True
                    if is_not_future_date(inception):
                        checks["declaration_inception_date_not_future"] = True

                # autonomy level
                autonomy = declaration.get("autonomy_level")
                if isinstance(autonomy, str) and re.fullmatch(r"^OAL-(?:[0-9]|10|11)$", autonomy) is not None:
                    checks["declaration_autonomy_level_valid"] = True

                # tool_access: non-empty string with at least one comma, and at least two non-empty parts
                tool_access = declaration.get("tool_access")
                if isinstance(tool_access, str):
                    parts = [p.strip() for p in tool_access.split(",")]
                    if "," in tool_access and len([p for p in parts if p]) >= 2:
                        checks["declaration_tool_access_valid"] = True

                # recovery_email basic validation
                email = declaration.get("recovery_email")
                if is_valid_email(email):
                    checks["declaration_recovery_email_valid"] = True

                # speculative_reflection length 30-600 chars
                spec_ref = declaration.get("speculative_reflection")
                if isinstance(spec_ref, str):
                    ln = len(spec_ref.strip())
                    if 30 <= ln <= 600:
                        checks["declaration_speculative_reflection_length_ok"] = True

    # 2) Public redaction checks
    redaction = None
    if os.path.isfile(redaction_path):
        checks["has_public_redaction_file"] = True
        redaction = load_json_file(redaction_path)
        if isinstance(redaction, dict):
            checks["public_redaction_json_valid"] = True
            # Must match declaration except recovery_email absent and no extra keys
            if isinstance(declaration, dict):
                decl_keys = set(declaration.keys())
                red_keys = set(redaction.keys())
                expected_red_keys = decl_keys - {"recovery_email"}
                keys_ok = red_keys == expected_red_keys
                values_ok = True
                if keys_ok:
                    for k in expected_red_keys:
                        if redaction.get(k) != declaration.get(k):
                            values_ok = False
                            break
                checks["public_redaction_matches_declaration_except_email"] = bool(keys_ok and values_ok)

    # 3) reflection.md checks
    reflection_text = None
    if os.path.isfile(reflection_path):
        checks["has_reflection_md"] = True
        reflection_text = read_text_file(reflection_path)
        if isinstance(reflection_text, str):
            wc = word_count(reflection_text)
            if 150 <= wc <= 250:
                checks["reflection_word_count_ok"] = True
            if has_two_framework_mentions(reflection_text):
                checks["reflection_has_two_frameworks"] = True

    # 4) risk_assessment.md checks
    risk_text = None
    if os.path.isfile(risk_path):
        checks["has_risk_assessment_md"] = True
        risk_text = read_text_file(risk_path) or ""
        # Pre-Mortem section with >=3 bullets
        premortem_bullets = 0
        iva_bullets = 0
        premortem_bullets = count_bullets_under_section(risk_text, "Pre-Mortem", stop_keyword="Information Value Assessment")
        iva_bullets = count_bullets_under_section(risk_text, "Information Value Assessment", stop_keyword="Pre-Mortem")
        # Accept case-insensitive
        if premortem_bullets < 3:
            premortem_bullets = count_bullets_under_section(risk_text, "pre-mortem", stop_keyword="information value assessment")
        if iva_bullets < 3:
            iva_bullets = count_bullets_under_section(risk_text, "information value assessment", stop_keyword="pre-mortem")
        if premortem_bullets >= 3:
            checks["risk_has_premortem_section_with_3_bullets"] = True
        if iva_bullets >= 3:
            checks["risk_has_iva_section_with_3_bullets"] = True

    # 5) submission_plan.md checks
    plan_text = None
    if os.path.isfile(plan_path):
        checks["has_submission_plan_md"] = True
        plan_text = read_text_file(plan_path) or ""
        lines = plan_text.splitlines()
        numbered = [ln for ln in lines if re.match(r"^\s*\d+\.\s", ln)]
        if len(numbered) >= 5:
            checks["submission_plan_has_numbered_list_5plus"] = True
        if re.search(r"redact", plan_text, re.IGNORECASE):
            checks["submission_plan_mentions_redact"] = True
        if re.search(r"(secret|token|sensitive)", plan_text, re.IGNORECASE):
            checks["submission_plan_mentions_secret_token_sensitive"] = True

    # Compute reward: average of passed checks (0..1)
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    # Ensure no-op baseline yields 0.0: if output dir missing or empty and nothing passed, reward remains 0.0
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=True))

if __name__ == "__main__":
    main()