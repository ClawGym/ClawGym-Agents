import json
import os
import sys
from typing import List, Tuple

def read_file_lines(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return []

def parse_experiments(entries_lines: List[str]) -> List[dict]:
    # Extract entries where six lines appear consecutively in order
    # - Trigger:
    # - Baseline:
    # - Mutation:
    # - Outcome:
    # - Evidence:
    # - Next move:
    i = 0
    entries = []
    n = len(entries_lines)
    while i < n:
        line = entries_lines[i].strip()
        if line.startswith("- Trigger:"):
            if i + 5 < n:
                l1 = entries_lines[i+0].strip()
                l2 = entries_lines[i+1].strip()
                l3 = entries_lines[i+2].strip()
                l4 = entries_lines[i+3].strip()
                l5 = entries_lines[i+4].strip()
                l6 = entries_lines[i+5].strip()
                if (l1.startswith("- Trigger:") and
                    l2.startswith("- Baseline:") and
                    l3.startswith("- Mutation:") and
                    l4.startswith("- Outcome:") and
                    l5.startswith("- Evidence:") and
                    l6.startswith("- Next move:")):
                    # Extract fields
                    trigger = l1[len("- Trigger:"):].strip()
                    baseline = l2[len("- Baseline:"):].strip()
                    mutation = l3[len("- Mutation:"):].strip()
                    outcome = l4[len("- Outcome:"):].strip()
                    evidence = l5[len("- Evidence:"):].strip()
                    next_move = l6[len("- Next move:"):].strip()
                    entries.append({
                        "trigger": trigger,
                        "baseline": baseline,
                        "mutation": mutation,
                        "outcome": outcome,
                        "evidence": evidence,
                        "next_move": next_move
                    })
                    i += 6
                    continue
        i += 1
    return entries

def get_section(lines: List[str], section_title: str) -> List[str]:
    # Return lines under a "## <section_title>" until next "## "
    sec_lines = []
    in_section = False
    title_lower = section_title.strip().lower()
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("##"):
            header_text = line.lstrip("#").strip().lower()
            if header_text == title_lower:
                in_section = True
                # Start collecting from next lines
                continue
            else:
                if in_section:
                    break
        if in_section:
            sec_lines.append(raw)
    return sec_lines

def find_bullets_with_keyword(lines: List[str], keyword: str) -> List[str]:
    out = []
    k = keyword.lower()
    for raw in lines:
        s = raw.strip()
        if s.startswith("- ") and k in s.lower():
            out.append(s)
    return out

def try_load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "notice_exists": False,
        "notice_has_words": False,

        "experiments_exists": False,
        "experiments_min_entries": False,
        "experiments_entries_in_order": False,
        "experiments_has_promote": False,
        "experiments_has_discard": False,
        "experiments_three_better_for_promoted": False,
        "evidence_lines_quality": False,

        "archive_dir_exists": False,
        "archive_has_md_with_keywords": False,

        "memory_exists": False,
        "memory_has_header": False,
        "memory_has_status_line_under_status": False,
        "memory_guardrails_have_required_phrases": False,
        "memory_stable_winners_bullet_with_checklist": False,
        "memory_stable_winner_bullet_concise": False,

        "summary_exists_and_valid_json": False,
        "summary_has_required_fields": False,
        "summary_field_values_valid": False,
    }

    # 1) local_notes_notice.txt checks
    notice_path = os.path.join(output_dir, "local_notes_notice.txt")
    if os.path.isfile(notice_path):
        checks["notice_exists"] = True
        try:
            with open(notice_path, "r", encoding="utf-8") as f:
                content = f.read().lower()
            if ("concise" in content) and ("local notes" in content):
                checks["notice_has_words"] = True
        except Exception:
            pass

    # 2) experiments.md checks
    experiments_path = os.path.join(output_dir, "experiments.md")
    entries = []
    if os.path.isfile(experiments_path):
        checks["experiments_exists"] = True
        lines = read_file_lines(experiments_path)
        entries = parse_experiments(lines)
        if len(entries) >= 2:
            checks["experiments_min_entries"] = True
            # By construction, parsed entries have the six lines in order
            checks["experiments_entries_in_order"] = True

            # Has promote / discard in next move
            has_promote = any("promote" in e["next_move"].lower() for e in entries)
            has_discard = any("discard" in e["next_move"].lower() for e in entries)
            if has_promote:
                checks["experiments_has_promote"] = True
            if has_discard:
                checks["experiments_has_discard"] = True

            # Evidence quality: each Evidence line >= 10 chars and not a single word
            evidence_ok = True
            for e in entries:
                ev = e.get("evidence", "").strip()
                if len(ev) < 10:
                    evidence_ok = False
                    break
                # Not just a single word
                words = ev.split()
                if len(words) <= 1:
                    evidence_ok = False
                    break
            if evidence_ok:
                checks["evidence_lines_quality"] = True

            # Count triple better for promoted mutation(s)
            triple_better = False
            # Find promoted mutations
            promoted_mutations = [e["mutation"] for e in entries if "promote" in e["next_move"].lower()]
            if promoted_mutations:
                for mut in promoted_mutations:
                    count_better = 0
                    for e in entries:
                        if e["mutation"] == mut and ("better" in e["outcome"].lower()):
                            count_better += 1
                    if count_better >= 3:
                        triple_better = True
                        break
            if triple_better:
                checks["experiments_three_better_for_promoted"] = True

    # 3) archive existence and content check
    archive_dir = os.path.join(output_dir, "archive")
    if os.path.isdir(archive_dir):
        checks["archive_dir_exists"] = True
        md_files = [f for f in os.listdir(archive_dir) if f.lower().endswith(".md")]
        found_match = False
        for fname in md_files:
            fpath = os.path.join(archive_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    c = f.read().lower()
                if (("retired" in c) or ("discard" in c)) and (("aggressive" in c) or ("worse" in c)):
                    found_match = True
                    break
            except Exception:
                continue
        if found_match:
            checks["archive_has_md_with_keywords"] = True

    # 4) memory.md checks
    memory_path = os.path.join(output_dir, "memory.md")
    if os.path.isfile(memory_path):
        checks["memory_exists"] = True
        mem_lines = read_file_lines(memory_path)
        mem_text = "\n".join(mem_lines)

        if "self-evolving memory" in mem_text.lower():
            checks["memory_has_header"] = True

        # Status section: find "## Status" then a line containing "status:"
        status_section = get_section(mem_lines, "Status")
        if status_section:
            sec_text_lower = "\n".join(status_section).lower()
            if "status:" in sec_text_lower:
                checks["memory_has_status_line_under_status"] = True

        # Guardrails section must include required phrases
        guard_section = get_section(mem_lines, "Guardrails")
        if guard_section:
            guard_text = "\n".join(guard_section).lower()
            if ("never modify the installed skill" in guard_text and
                "never promote a rule after a single success" in guard_text):
                checks["memory_guardrails_have_required_phrases"] = True

        # Stable Winners section with bullet containing "checklist"
        winners_section = get_section(mem_lines, "Stable Winners")
        bullet_with_checklist = None
        if winners_section:
            bullets = find_bullets_with_keyword(winners_section, "checklist")
            if bullets:
                checks["memory_stable_winners_bullet_with_checklist"] = True
                # Conciseness rubric: length <= 200 characters
                # Measure bullet text length (excluding leading "- ")
                bullet_text = bullets[0]
                # Remove leading "- " if present
                if bullet_text.startswith("- "):
                    bullet_text = bullet_text[2:].strip()
                if len(bullet_text) <= 200:
                    checks["memory_stable_winner_bullet_concise"] = True

    # 5) summary.json checks
    summary_path = os.path.join(output_dir, "summary.json")
    summary = None
    if os.path.isfile(summary_path):
        summary = try_load_json(summary_path)
        if isinstance(summary, dict):
            checks["summary_exists_and_valid_json"] = True
            # Required keys exist
            required_keys_present = all(k in summary for k in ["promoted_mutation", "runs_count", "average_speed_delta_sec", "total_error_reduction"])
            if required_keys_present and isinstance(summary.get("promoted_mutation"), str):
                checks["summary_has_required_fields"] = True
                # Validate field values
                pm = summary.get("promoted_mutation", "")
                rc = summary.get("runs_count", None)
                avg = summary.get("average_speed_delta_sec", None)
                ter = summary.get("total_error_reduction", None)
                valid = True
                # promoted_mutation contains "checklist"
                if "checklist" not in (pm or "").lower():
                    valid = False
                # runs_count integer >= 3
                if not isinstance(rc, int) or rc < 3:
                    valid = False
                # average_speed_delta_sec number < 0
                if not isinstance(avg, (int, float)) or not (avg < 0):
                    valid = False
                # total_error_reduction number >= 1
                if not isinstance(ter, (int, float)) or ter < 1:
                    valid = False
                if valid:
                    checks["summary_field_values_valid"] = True

    # Compute reward as average of booleans
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure 0.0 if no artifacts created (no-op baseline)
    # If output directory missing or empty, reward should be 0.0
    # We consider it no-op if none of the file-dependent checks passed
    # However reward computed already follows passes; if none passed, it's 0.0.

    result = {"reward": round(reward, 6)}
    # Maintain order: reward first, then checks
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()