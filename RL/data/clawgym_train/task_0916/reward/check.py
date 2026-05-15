import json
import os
import re
import sys
from datetime import datetime
from difflib import SequenceMatcher

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "report_exists": False,
        "report_schema_valid": False,
        "identity_changed_correct": False,
        "memory_changed_correct": False,
        "drift_score_correct": False,
        "score_correct": False,
        "grade_correct": False,
        "daily_log_present_flag_correct": False,
        "soul_present_flag_correct": False,
        "triage_exists": False,
        "triage_sections_present": False,
        "triage_mentions_changed_and_grade": False,
    }

    # Paths
    report_path = os.path.join(output_dir, "continuity", "report.json")
    triage_path = os.path.join(output_dir, "continuity", "triage.md")

    # Utility functions
    def read_text(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def read_lines(path):
        txt = read_text(path)
        if txt is None:
            return None
        return txt.splitlines()

    def file_size(path):
        try:
            return os.path.getsize(path)
        except Exception:
            return None

    def compute_added_removed(a_lines, b_lines):
        # Returns (added_count, removed_count) using SequenceMatcher opcodes.
        # Treat 'replace' as both removed and added for the respective spans.
        added = 0
        removed = 0
        sm = SequenceMatcher(a=a_lines, b=b_lines)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "insert":
                added += (j2 - j1)
            elif tag == "delete":
                removed += (i2 - i1)
            elif tag == "replace":
                removed += (i2 - i1)
                added += (j2 - j1)
        return added, removed

    def count_changed_files(file_list):
        changed = []
        for fname in file_list:
            base_p = os.path.join(input_dir, "baseline", fname)
            curr_p = os.path.join(input_dir, "current", fname)
            base_txt = read_text(base_p)
            curr_txt = read_text(curr_p)
            # If either missing, consider changed
            if base_txt is None or curr_txt is None:
                changed.append(fname)
                continue
            if base_txt != curr_txt:
                changed.append(fname)
        return changed

    def compute_drift_score():
        # Start at 100
        score = 100

        # Identity drift for SOUL.md and IDENTITY.md
        for fname in ["SOUL.md", "IDENTITY.md"]:
            base_p = os.path.join(input_dir, "baseline", fname)
            curr_p = os.path.join(input_dir, "current", fname)
            base_lines = read_lines(base_p)
            curr_lines = read_lines(curr_p)
            if base_lines is None or curr_lines is None:
                # Treat missing as severe drift
                change_pct = 100
            else:
                added, removed = compute_added_removed(base_lines, curr_lines)
                baseline_total = len(base_lines)
                change_pct = ((added + removed) * 100) // (baseline_total + 1)
            if change_pct > 50:
                score -= 30
            elif change_pct > 20:
                score -= 15
            elif change_pct > 5:
                score -= 5
            # else deduct 0

        # Mission drift (MEMORY.md) - first 30 lines
        mem_base = os.path.join(input_dir, "baseline", "MEMORY.md")
        mem_curr = os.path.join(input_dir, "current", "MEMORY.md")
        base_lines = read_lines(mem_base)
        curr_lines = read_lines(mem_curr)
        if base_lines is None or curr_lines is None:
            mdiff = 11  # trigger max deduction per spec branch
        else:
            base_head = base_lines[:30]
            curr_head = curr_lines[:30]
            add_h, rem_h = compute_added_removed(base_head, curr_head)
            mdiff = add_h + rem_h
        if mdiff > 10:
            score -= 20
        elif mdiff > 0:
            score -= 5

        # Memory growth (MEMORY.md)
        base_sz = file_size(mem_base)
        curr_sz = file_size(mem_curr)
        if base_sz is None or curr_sz is None:
            growth_pct = 0
        else:
            growth_pct = ((curr_sz - base_sz) * 100) // (base_sz + 1)
        if growth_pct > 200:
            score -= 10

        # Priority drift in last 3 logs
        mem_dir = os.path.join(input_dir, "current", "memory")
        selected_files = []
        if os.path.isdir(mem_dir):
            for name in os.listdir(mem_dir):
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", name):
                    selected_files.append(name)
            selected_files.sort(reverse=True)  # lexicographic matches ISO date order
            selected_files = selected_files[:3]
        # Count mentions
        content = ""
        for name in selected_files:
            p = os.path.join(mem_dir, name)
            txt = read_text(p)
            if txt:
                content += "\n" + txt
        # Patterns
        def count_pat(txt, pattern):
            if not txt:
                return 0
            return len(re.findall(pattern, txt, flags=re.IGNORECASE))

        TRADING = count_pat(content, r"trade|polymarket|kelly|sniper|bot")
        MISSION = count_pat(content, r"memory|identity|soul|mission|drift|continuity")
        OPS = count_pat(content, r"cron|channel|poster|telegram|article|deploy")
        SOCIAL = count_pat(content, r"moltbook|farcaster|tweet|post|follow")
        TOTAL = TRADING + MISSION + OPS + SOCIAL + 1
        mission_pct = (MISSION * 100) // TOTAL
        if mission_pct < 5:
            score -= 15
        elif mission_pct < 15:
            score -= 5

        # Clamp
        if score < 0:
            score = 0
        if score > 100:
            score = 100
        return score

    def compute_overall(identity_changed, memory_changed, drift_score):
        score = 100
        score -= 15 * identity_changed
        score -= 5 * memory_changed
        drift_penalty = ((100 - drift_score) * 30) // 100
        score -= drift_penalty

        # Daily log presence
        today_file = os.path.join(input_dir, "today.txt")
        today_txt = read_text(today_file)
        today_txt = (today_txt or "").strip()
        daily_log_present = False
        if today_txt:
            log_path = os.path.join(input_dir, "current", "memory", f"{today_txt}.md")
            daily_log_present = os.path.isfile(log_path)
        if not daily_log_present:
            score -= 10

        # SOUL.md existence
        soul_present = os.path.isfile(os.path.join(input_dir, "current", "SOUL.md"))
        if not soul_present:
            score -= 25

        # Clamp
        if score < 0:
            score = 0
        if score > 100:
            score = 100

        grade = grade_from_score(score)
        return score, grade, soul_present, daily_log_present

    def grade_from_score(score):
        if score >= 90:
            return "EXCELLENT"
        elif score >= 75:
            return "GOOD"
        elif score >= 50:
            return "FAIR"
        elif score >= 25:
            return "POOR"
        else:
            return "CRITICAL"

    # Compute expected values from inputs
    identity_files = ["SOUL.md", "IDENTITY.md", "USER.md", "AGENTS.md", "MEMORY.md"]
    changed_files = count_changed_files(identity_files)
    expected_identity_changed = len(changed_files)
    expected_memory_changed = len(changed_files)  # per task, same set/count
    expected_drift_score = compute_drift_score()
    expected_score, expected_grade, expected_soul_present, expected_daily_log_present = compute_overall(
        expected_identity_changed, expected_memory_changed, expected_drift_score
    )

    # Validate outputs
    report = None
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            report_txt = read_text(report_path)
            report = json.loads(report_txt)
            # Schema validation
            schema_ok = True
            if not isinstance(report, dict):
                schema_ok = False
            else:
                # Required keys and types
                required = {
                    "timestamp": str,
                    "score": int,
                    "grade": str,
                    "drift_score": int,
                    "soul_present": bool,
                    "daily_log_present": bool,
                    "identity_changed": int,
                    "memory_changed": int,
                    "issues": list,
                }
                for k, t in required.items():
                    if k not in report:
                        schema_ok = False
                        break
                    # type check with special handling for bool (bool is subclass of int)
                    v = report[k]
                    if t is int:
                        if not isinstance(v, int):
                            schema_ok = False
                            break
                    elif t is bool:
                        if not isinstance(v, bool):
                            schema_ok = False
                            break
                    elif t is str:
                        if not isinstance(v, str):
                            schema_ok = False
                            break
                    elif t is list:
                        if not isinstance(v, list):
                            schema_ok = False
                            break
                # Range checks
                if schema_ok:
                    if not (0 <= report["score"] <= 100):
                        schema_ok = False
                    if not (0 <= report["drift_score"] <= 100):
                        schema_ok = False
            checks["report_schema_valid"] = bool(schema_ok)
        except Exception:
            checks["report_schema_valid"] = False

    # Compare computed values with reported
    if checks["report_schema_valid"]:
        if report.get("identity_changed") == expected_identity_changed:
            checks["identity_changed_correct"] = True
        if report.get("memory_changed") == expected_memory_changed:
            checks["memory_changed_correct"] = True
        if report.get("drift_score") == expected_drift_score:
            checks["drift_score_correct"] = True
        if report.get("score") == expected_score:
            checks["score_correct"] = True
        if report.get("grade") == expected_grade:
            checks["grade_correct"] = True
        if report.get("daily_log_present") == expected_daily_log_present:
            checks["daily_log_present_flag_correct"] = True
        if report.get("soul_present") == expected_soul_present:
            checks["soul_present_flag_correct"] = True

    # Triage checks
    triage_txt = None
    if os.path.isfile(triage_path):
        checks["triage_exists"] = True
        triage_txt = read_text(triage_path) or ""
        # Section headings presence (case-sensitive)
        required_headings = ["Summary", "Key Findings", "Recommended Actions"]
        if all(h in triage_txt for h in required_headings):
            checks["triage_sections_present"] = True
        # Mentions changed filenames and grade
        mentions_ok = True
        # Include grade mention
        if expected_grade not in triage_txt:
            mentions_ok = False
        # Only require changed filenames if any changed
        if expected_identity_changed > 0:
            for fname in changed_files:
                if fname not in triage_txt:
                    mentions_ok = False
                    break
        checks["triage_mentions_changed_and_grade"] = mentions_ok

    # Determine reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Enforce no-op baseline reward = 0 if required artifacts missing
    required_outputs_present = os.path.isfile(report_path) and os.path.isfile(triage_path)
    if not required_outputs_present:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Output result JSON on last line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()