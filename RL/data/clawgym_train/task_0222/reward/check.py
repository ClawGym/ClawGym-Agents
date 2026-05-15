import json
import sys
import subprocess
from pathlib import Path


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_bullets(md_path: Path):
    try:
        skills = set()
        with md_path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("- "):
                    skills.add(s[2:].strip())
        return skills
    except Exception:
        return None


def load_roles(json_path: Path):
    data = safe_load_json(json_path)
    if not isinstance(data, dict):
        return None, None
    roles = data.get("roles", [])
    if not isinstance(roles, list):
        return None, None
    titles = []
    must_haves = set()
    for r in roles:
        if isinstance(r, dict):
            t = r.get("title", "")
            if isinstance(t, str):
                titles.append(t)
            mh = r.get("must_have", [])
            if isinstance(mh, list):
                for m in mh:
                    if isinstance(m, str):
                        must_haves.add(m)
    return titles, must_haves


def compute_gap_skills(workspace: Path):
    input_curr = workspace / "input" / "bootcamp_curriculum.md"
    input_bg = workspace / "input" / "customer_background.md"
    input_roles = workspace / "input" / "target_roles.json"

    if not input_curr.exists() or not input_bg.exists() or not input_roles.exists():
        return None, None, None

    curriculum_skills = read_bullets(input_curr)
    background_skills = read_bullets(input_bg)
    role_titles, role_musts = load_roles(input_roles)

    if curriculum_skills is None or background_skills is None or role_titles is None or role_musts is None:
        return None, None, None

    covered = curriculum_skills.union(background_skills)
    gap_skills = sorted([s for s in role_musts if s not in covered])
    return role_titles, gap_skills, covered


def run_validator(workspace: Path, plan_path: Path, msg_path: Path):
    validator = workspace / "tools" / "validate_plan.py"
    if not validator.exists() or not plan_path.exists() or not msg_path.exists():
        return False, "", None
    try:
        proc = subprocess.run(
            [sys.executable, str(validator), str(plan_path), str(msg_path)],
            capture_output=True,
            text=True,
            cwd=str(workspace),
        )
        stdout = proc.stdout
        # Normalize newlines to '\n'
        stdout = stdout.replace("\r\n", "\n")
        success = (proc.returncode == 0) and ("ALL CHECKS PASSED" in stdout.splitlines()[-1] if stdout.splitlines() else False)
        return success, stdout, proc.returncode
    except Exception:
        return False, "", None


def text_last_nonempty_line(text: str) -> str:
    if text is None:
        return ""
    lines = text.replace("\r\n", "\n").split("\n")
    for line in reversed(lines):
        if line.strip() != "":
            return line
    return ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    plan_path = workspace / "outputs" / "study_plan.md"
    msg_path = workspace / "outputs" / "mentor_message.txt"
    report_path = workspace / "outputs" / "validation_report.txt"

    scores = {
        "outputs_present": 0.0,
        "weeks_sections_present": 0.0,
        "references_all_role_titles": 0.0,
        "all_gap_skills_in_plan": 0.0,
        "mentor_message_requirements": 0.0,
        "ran_validator_success": 0.0,
        "validation_report_exists_and_passed": 0.0,
        "validation_report_matches_validator": 0.0,
    }

    # Outputs presence
    if plan_path.exists() and msg_path.exists():
        scores["outputs_present"] = 1.0

    plan_text = safe_read_text(plan_path) if plan_path.exists() else None
    msg_text = safe_read_text(msg_path) if msg_path.exists() else None

    # Weeks sections present
    if isinstance(plan_text, str):
        weeks_ok = all(w in plan_text for w in ["Week 1", "Week 2", "Week 3", "Week 4"])
        scores["weeks_sections_present"] = 1.0 if weeks_ok else 0.0

    # Compute gap skills and role titles
    role_titles, gap_skills, _covered = compute_gap_skills(workspace)

    # References to all role titles in plan
    if isinstance(plan_text, str) and isinstance(role_titles, list):
        if all((isinstance(t, str) and t in plan_text) for t in role_titles if t):
            scores["references_all_role_titles"] = 1.0

    # All gap skills included in plan
    if isinstance(plan_text, str) and isinstance(gap_skills, list):
        gaps_ok = all((g in plan_text) for g in gap_skills)
        scores["all_gap_skills_in_plan"] = 1.0 if gaps_ok else 0.0

    # Mentor message requirements
    if isinstance(msg_text, str) and isinstance(gap_skills, list):
        msg_lower = msg_text.lower()
        asks_feedback = "feedback" in msg_lower
        asks_resources = ("resource" in msg_lower) or ("recommendation" in msg_lower)
        gap_mentions = [g for g in gap_skills if g in msg_text]
        msg_ok = asks_feedback and asks_resources and (len(gap_mentions) >= 2)
        scores["mentor_message_requirements"] = 1.0 if msg_ok else 0.0

    # Run validator
    success, stdout, returncode = run_validator(workspace, plan_path, msg_path)
    if success:
        scores["ran_validator_success"] = 1.0

    # Validation report exists and ends with ALL CHECKS PASSED
    report_text = safe_read_text(report_path) if report_path.exists() else None
    if isinstance(report_text, str):
        last_line = text_last_nonempty_line(report_text)
        if last_line == "ALL CHECKS PASSED":
            scores["validation_report_exists_and_passed"] = 1.0

    # Validation report matches our validator run output (full console output)
    if isinstance(report_text, str) and isinstance(stdout, str) and returncode is not None:
        # Normalize both texts for comparison
        rep_norm = report_text.replace("\r\n", "\n")
        out_norm = stdout.replace("\r\n", "\n")
        if rep_norm == out_norm:
            scores["validation_report_matches_validator"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()