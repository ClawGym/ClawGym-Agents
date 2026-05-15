import os
import re
import sys
import json

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "learnings_exists": False,
        "learnings_min_three": False,
        "learnings_has_correction": False,
        "learnings_has_knowledge_gap": False,
        "learnings_has_best_practice": False,
        "learnings_has_see_also": False,
        "learnings_has_recurring_pattern": False,
        "learnings_has_promoted_to_skill": False,
        "errors_exists": False,
        "errors_two_with_code_and_reproducible": False,
        "features_exists": False,
        "features_has_required_entry": False,
        "memory_prevention_rules_present": False,
        "memory_mentions_pattern_key": False,
        "skill_file_valid": False,
        "review_counts_present": False,
    }

    # Helper to read file safely
    def read_text(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return None

    # Parse LEARNINGS.md
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    learnings_text = read_text(learnings_path)
    pattern_key_in_learnings = None

    if learnings_text is not None:
        checks["learnings_exists"] = True

        # Parse entries by headers
        # Header format expected: ## [LRN-YYYYMMDD-XXX] category
        lines = learnings_text.splitlines()
        entry_indices = []
        for i, line in enumerate(lines):
            if re.match(r"^## \[LRN-\d{8}-[A-Z0-9]{3}\]", line.strip()):
                entry_indices.append(i)

        entries = []
        for idx, start_i in enumerate(entry_indices):
            end_i = entry_indices[idx + 1] if idx + 1 < len(entry_indices) else len(lines)
            header_line = lines[start_i].strip()
            content_lines = lines[start_i + 1:end_i]
            content = "\n".join(content_lines)
            # Extract category if present after the header
            m = re.match(r"^## \[(LRN-\d{8}-[A-Z0-9]{3})\]\s*(\w+)?", header_line)
            category = None
            if m:
                category = (m.group(2) or "").strip()
            entries.append({
                "header": header_line,
                "content": content,
                "category": category
            })

        if len(entries) >= 3:
            checks["learnings_min_three"] = True

        # Categories presence
        cats = {e["category"].lower() for e in entries if e["category"]}
        if "correction" in cats:
            checks["learnings_has_correction"] = True
        if "knowledge_gap" in cats:
            checks["learnings_has_knowledge_gap"] = True
        if "best_practice" in cats:
            checks["learnings_has_best_practice"] = True

        # See Also presence
        if re.search(r"See Also:", learnings_text):
            checks["learnings_has_see_also"] = True

        # Promoted to skill & skill path presence
        if re.search(r"\*\*Status\*\*:\s*promoted_to_skill", learnings_text) and re.search(r"Skill-Path:\s*skills/", learnings_text):
            checks["learnings_has_promoted_to_skill"] = True

        # Recurring pattern (Source: simplify-and-harden, Pattern-Key, Recurrence-Count >= 3)
        recurring_ok = False
        pk_found = None
        for e in entries:
            content = e["content"]
            if ("Source: simplify-and-harden" in content) and ("Pattern-Key:" in content) and ("Recurrence-Count:" in content):
                # Extract pattern key
                m_pk = re.search(r"Pattern-Key:\s*([^\n\r]+)", content)
                m_rc = re.search(r"Recurrence-Count:\s*(\d+)", content)
                if m_pk and m_rc:
                    try:
                        rc = int(m_rc.group(1))
                    except ValueError:
                        rc = 0
                    if rc >= 3:
                        pk_found = m_pk.group(1).strip()
                        recurring_ok = True
                        break
        if recurring_ok:
            checks["learnings_has_recurring_pattern"] = True
            pattern_key_in_learnings = pk_found

    # Parse ERRORS.md
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    errors_text = read_text(errors_path)
    if errors_text is not None:
        checks["errors_exists"] = True
        err_lines = errors_text.splitlines()
        err_indices = []
        for i, line in enumerate(err_lines):
            if re.match(r"^## \[ERR-\d{8}-[A-Z0-9]{3}\]", line.strip()):
                err_indices.append(i)

        valid_error_entries = 0
        for idx, start_i in enumerate(err_indices):
            end_i = err_indices[idx + 1] if idx + 1 < len(err_indices) else len(err_lines)
            section = "\n".join(err_lines[start_i:end_i])
            # Must include "### Error" followed by a fenced code block
            has_error_section = "### Error" in section
            code_block_after_error = False
            if has_error_section:
                pos = section.find("### Error")
                after = section[pos + len("### Error"):]
                # Require at least one pair of ``` fences after the Error heading
                fences = len(re.findall(r"```", after))
                if fences >= 2:
                    code_block_after_error = True
            # Must include "Reproducible:" field
            has_repro_field = bool(re.search(r"Reproducible:", section))
            if has_error_section and code_block_after_error and has_repro_field:
                valid_error_entries += 1

        if valid_error_entries >= 2:
            checks["errors_two_with_code_and_reproducible"] = True

    # Parse FEATURE_REQUESTS.md
    feats_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    feats_text = read_text(feats_path)
    if feats_text is not None:
        checks["features_exists"] = True
        flines = feats_text.splitlines()
        feat_indices = []
        for i, line in enumerate(flines):
            if re.match(r"^## \[FEAT-\d{8}-[A-Z0-9]{3}\]", line.strip()):
                feat_indices.append(i)

        has_req_entry = False
        for idx, start_i in enumerate(feat_indices):
            end_i = feat_indices[idx + 1] if idx + 1 < len(feat_indices) else len(flines)
            section = "\n".join(flines[start_i:end_i])
            if ("### Requested Capability" in section) and ("### Complexity Estimate" in section):
                has_req_entry = True
                break
        if has_req_entry:
            checks["features_has_required_entry"] = True

    # Check memory file (CLAUDE.md or AGENTS.md) for Prevention Rules with pattern key
    memory_paths = [
        os.path.join(output_dir, "CLAUDE.md"),
        os.path.join(output_dir, "AGENTS.md"),
    ]
    memory_any_exists = False
    memory_any_has_prevention = False
    memory_any_mentions_pattern = False

    for mp in memory_paths:
        mtext = read_text(mp)
        if mtext is None:
            continue
        memory_any_exists = True
        if re.search(r"prevention rules", mtext, flags=re.IGNORECASE):
            memory_any_has_prevention = True
            if pattern_key_in_learnings:
                if pattern_key_in_learnings in mtext:
                    memory_any_mentions_pattern = True

    if memory_any_exists and memory_any_has_prevention:
        checks["memory_prevention_rules_present"] = True
    # Only pass mentions_pattern if we had pattern key and a memory file mentioning it
    if pattern_key_in_learnings and memory_any_mentions_pattern:
        checks["memory_mentions_pattern_key"] = True

    # Validate skill file at output/skills/<any>/SKILL.md
    skills_root = os.path.join(output_dir, "skills")
    skill_valid = False
    if os.path.isdir(skills_root):
        try:
            for entry in os.listdir(skills_root):
                subdir = os.path.join(skills_root, entry)
                if not os.path.isdir(subdir):
                    continue
                skill_path = os.path.join(subdir, "SKILL.md")
                stext = read_text(skill_path)
                if stext is None:
                    continue
                # Check frontmatter starts at first non-empty line and ends with ---
                # And contains name: and description: in the frontmatter block
                # Also contains "Learning ID"
                # Trim leading newlines
                s_lines = stext.splitlines()
                # Find first non-empty line
                first_idx = 0
                while first_idx < len(s_lines) and s_lines[first_idx].strip() == "":
                    first_idx += 1
                if first_idx >= len(s_lines):
                    continue
                if s_lines[first_idx].strip() != "---":
                    continue
                # Find closing ---
                close_idx = None
                for j in range(first_idx + 1, len(s_lines)):
                    if s_lines[j].strip() == "---":
                        close_idx = j
                        break
                if close_idx is None:
                    continue
                frontmatter = "\n".join(s_lines[first_idx+1:close_idx])
                if not re.search(r"^name\s*:\s*.+", frontmatter, flags=re.MULTILINE):
                    continue
                if not re.search(r"^description\s*:\s*.+", frontmatter, flags=re.MULTILINE):
                    continue
                if not re.search(r"Learning ID", stext):
                    continue
                skill_valid = True
                break
        except Exception:
            skill_valid = False
    if skill_valid:
        checks["skill_file_valid"] = True

    # REVIEW.md counts
    review_path = os.path.join(output_dir, "REVIEW.md")
    review_text = read_text(review_path)
    if review_text is not None:
        def has_count_for(word_variants):
            # Check if any variant appears near a number (both orders)
            for w in word_variants:
                # number before word
                if re.search(rf"(\d+)\s*(?:\w*\s*){{0,3}}{re.escape(w)}", review_text, flags=re.IGNORECASE):
                    return True
                # word before number
                if re.search(rf"{re.escape(w)}\s*(?:\w*\s*){{0,3}}(\d+)", review_text, flags=re.IGNORECASE):
                    return True
            return False

        has_learn = has_count_for(["learning", "learnings"])
        has_error = has_count_for(["error", "errors"])
        # feature requests may be written as 'feature requests' or 'feature'
        has_feat = has_count_for(["feature request", "feature requests", "feature", "features"])
        if has_learn and has_error and has_feat:
            checks["review_counts_present"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output is missing or empty, ensure 0.0
    # If none of the primary artifacts exist, force reward 0.0
    primary_artifacts_exist = any([
        checks["learnings_exists"],
        checks["errors_exists"],
        checks["features_exists"],
        os.path.isfile(os.path.join(output_dir, "CLAUDE.md")),
        os.path.isfile(os.path.join(output_dir, "AGENTS.md")),
        os.path.isdir(os.path.join(output_dir, "skills")),
        os.path.isfile(os.path.join(output_dir, "REVIEW.md")),
    ])
    if not primary_artifacts_exist:
        reward = 0.0

    # Ensure reward is between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    # Preserve insertion order: reward first, then checks
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()