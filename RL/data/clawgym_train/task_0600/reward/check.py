import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

def any_line_startswith(text, prefix):
    for line in text.splitlines():
        if line.lstrip().startswith(prefix):
            return True
    return False

def count_bullets(text, bullet_prefix="- "):
    count = 0
    for line in text.splitlines():
        if line.lstrip().startswith(bullet_prefix):
            count += 1
    return count

def has_numbered_findings(text):
    lines = [ln.lstrip() for ln in text.splitlines()]
    has1 = any(ln.startswith("1.") for ln in lines)
    has2 = any(ln.startswith("2.") for ln in lines)
    return has1 and has2

def contains_ci(haystack, needle):
    return needle.lower() in haystack.lower()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    spec_path = os.path.join(output_dir, "shared", "specs", "T-042-spec.md")
    spawn_builder_path = os.path.join(output_dir, "spawn_prompts", "T-042-builder.md")
    spawn_reviewer_path = os.path.join(output_dir, "spawn_prompts", "T-042-reviewer.md")
    csvcut_py_path = os.path.join(output_dir, "shared", "artifacts", "T-042", "csvcut.py")
    readme_path = os.path.join(output_dir, "shared", "artifacts", "T-042", "README.md")
    review_path = os.path.join(output_dir, "shared", "reviews", "T-042-review.md")
    lifecycle_path = os.path.join(output_dir, "logs", "T-042-lifecycle.md")
    decision_path = os.path.join(output_dir, "shared", "decisions", "T-042-decision.md")

    checks = {
        # Spec
        "spec_exists": False,
        "spec_has_required_sections": False,
        # Spawn prompts
        "spawn_builder_exists": False,
        "spawn_builder_has_fields": False,
        "spawn_reviewer_exists": False,
        "spawn_reviewer_has_fields": False,
        # Build artifacts
        "build_csvcut_exists": False,
        "build_readme_exists": False,
        "build_readme_has_usage": False,
        # Review
        "review_exists": False,
        "review_has_reviewer_tag": False,
        "review_has_decision": False,
        "review_has_two_findings": False,
        # Lifecycle
        "lifecycle_exists": False,
        "lifecycle_has_builder_handoff": False,
        "lifecycle_has_reviewer_feedback": False,
        "lifecycle_has_reviewer_approved_or_return": False,
        "lifecycle_has_orchestrator_comment": False,
        # Optional decision note
        "decision_optional_exists": False,
        "decision_optional_has_labels": False,
    }

    # Spec checks
    if os.path.isfile(spec_path):
        checks["spec_exists"] = True
        spec_txt = read_text(spec_path)
        required_strings = [
            "Task ID: T-042",
            "Context",
            "Requirements",
            "Acceptance Criteria",
            "Deliverables",
            "Output Path",
            "Handoff Instructions",
        ]
        checks["spec_has_required_sections"] = all(s in spec_txt for s in required_strings)

    # Spawn prompts - builder
    if os.path.isfile(spawn_builder_path):
        checks["spawn_builder_exists"] = True
        btxt = read_text(spawn_builder_path)
        bl = btxt.lower()
        builder_fields_present = all([
            "task id:" in bl,
            "role:" in bl,
            "priority:" in bl,
            "context" in bl,
            "deliverables" in bl,
            "output path" in bl,
            "handoff" in bl,
        ])
        checks["spawn_builder_has_fields"] = builder_fields_present

    # Spawn prompts - reviewer
    if os.path.isfile(spawn_reviewer_path):
        checks["spawn_reviewer_exists"] = True
        rtxt = read_text(spawn_reviewer_path)
        rl = rtxt.lower()
        reviewer_fields_present = all([
            "task id:" in rl,
            "role:" in rl,
            "priority:" in rl,
            "context" in rl,
            "deliverables" in rl,
            "output path" in rl,
            "handoff" in rl,
        ])
        checks["spawn_reviewer_has_fields"] = reviewer_fields_present

    # Build artifacts
    if os.path.isfile(csvcut_py_path):
        checks["build_csvcut_exists"] = True
    if os.path.isfile(readme_path):
        checks["build_readme_exists"] = True
        readme_txt = read_text(readme_path)
        checks["build_readme_has_usage"] = contains_ci(readme_txt, "usage")

    # Review file
    if os.path.isfile(review_path):
        checks["review_exists"] = True
        review_txt = read_text(review_path)
        checks["review_has_reviewer_tag"] = any_line_startswith(review_txt, "[Reviewer]")
        # decision approved or returned (case-insensitive)
        rl = review_txt.lower()
        checks["review_has_decision"] = ("approved" in rl) or ("returned" in rl)
        # findings: two bullets "- " or numbered "1." and "2."
        bullet_count = count_bullets(review_txt, "- ")
        has_two_bullets = bullet_count >= 2
        has_two_numbered = has_numbered_findings(review_txt)
        checks["review_has_two_findings"] = has_two_bullets or has_two_numbered

    # Lifecycle log
    if os.path.isfile(lifecycle_path):
        checks["lifecycle_exists"] = True
        life_txt = read_text(lifecycle_path)
        checks["lifecycle_has_builder_handoff"] = any_line_startswith(life_txt, "[Builder] Handoff:")
        checks["lifecycle_has_reviewer_feedback"] = any_line_startswith(life_txt, "[Reviewer] Feedback:")
        approved_present = any_line_startswith(life_txt, "[Reviewer] Approved:")
        # consider "Returned" in any [Reviewer] line
        returned_present = False
        for line in life_txt.splitlines():
            ls = line.lstrip()
            if ls.startswith("[Reviewer]") and ("returned" in ls.lower()):
                returned_present = True
                break
        checks["lifecycle_has_reviewer_approved_or_return"] = approved_present or returned_present
        checks["lifecycle_has_orchestrator_comment"] = any_line_startswith(life_txt, "[Orchestrator]")

    # Optional decision note
    if os.path.isfile(decision_path):
        checks["decision_optional_exists"] = True
        dtxt = read_text(decision_path).lower()
        has_decision = "decision" in dtxt
        has_consequences = "consequences" in dtxt
        checks["decision_optional_has_labels"] = has_decision and has_consequences

    # Compute reward over mandatory checks only
    mandatory_keys = [
        "spec_exists",
        "spec_has_required_sections",
        "spawn_builder_exists",
        "spawn_builder_has_fields",
        "spawn_reviewer_exists",
        "spawn_reviewer_has_fields",
        "build_csvcut_exists",
        "build_readme_exists",
        "build_readme_has_usage",
        "review_exists",
        "review_has_reviewer_tag",
        "review_has_decision",
        "review_has_two_findings",
        "lifecycle_exists",
        "lifecycle_has_builder_handoff",
        "lifecycle_has_reviewer_feedback",
        "lifecycle_has_reviewer_approved_or_return",
        "lifecycle_has_orchestrator_comment",
    ]
    passed = sum(1 for k in mandatory_keys if checks.get(k, False))
    total = len(mandatory_keys)
    reward = (passed / total) if total > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()