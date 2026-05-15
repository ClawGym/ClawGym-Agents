import json
import os
import sys
import re

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_bcc_playbook": False,
        "headers_present": False,
        "quickstart_steps_present": False,
        "patterns_bullets_present": False,
        "security_items_present": False,
        "performance_strategies_present": False,
        "debugging_steps_present": False,
        "migration_checklist_present": False,
        "cheatsheet_line_present": False,
        "has_traceability": False,
        "traceability_exact_match": False,
        "has_implementation_plan": False,
        "impl_min_actions": False,
        "impl_min_owner_lines": False,
        "impl_min_due_date_lines": False,
    }

    # Helper functions
    def read_lines(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return [line.rstrip("\n") for line in f.readlines()]
        except Exception:
            return []

    def line_equals(expected, line):
        # Compare exact content ignoring surrounding whitespace
        return line.strip() == expected

    def find_exact_lines(lines, expected_list):
        found = set()
        for exp in expected_list:
            for l in lines:
                if line_equals(exp, l):
                    found.add(exp)
                    break
        return len(found) == len(expected_list)

    def performance_item_present(lines, item_word):
        # Accept either a plain line with the word, or a bullet "- <word>" or "* <word>"
        for l in lines:
            s = l.strip()
            content = s
            if s.startswith("- "):
                content = s[2:].strip()
            elif s.startswith("* "):
                content = s[2:].strip()
            if content == item_word:
                return True
        return False

    # 1) Check bcc_playbook.md
    playbook_path = os.path.join(output_dir, "bcc_playbook.md")
    if os.path.isfile(playbook_path):
        checks["has_bcc_playbook"] = True
        lines = read_lines(playbook_path)

        # Structural headers
        header_keywords = ["Overview", "Quickstart", "Patterns", "Security", "Performance", "Debugging", "Migration", "Cheatsheet"]
        found_headers = {k: False for k in header_keywords}
        header_re = re.compile(r"^\s*#{1,6}\s*")
        for l in lines:
            if header_re.match(l):
                lower_line = l.lower()
                for k in header_keywords:
                    if k.lower() in lower_line:
                        found_headers[k] = True
        checks["headers_present"] = all(found_headers.values())

        # Quickstart steps exact lines
        quickstart_expected = [
            "1. Download or clone the bcc package",
            "2. Install dependencies",
            "3. Configure initial settings",
            "4. Verify installation",
        ]
        checks["quickstart_steps_present"] = find_exact_lines(lines, quickstart_expected)

        # Patterns & Best Practices bullets exact lines
        patterns_expected = [
            "- Follow the principle of least privilege",
            "- Implement comprehensive logging",
        ]
        checks["patterns_bullets_present"] = find_exact_lines(lines, patterns_expected)

        # Security Hardening Checklist exact lines
        security_expected = [
            "- Enable multi-factor authentication where possible",
            "- Sanitize inputs to prevent injection",
            "- Encrypt data at rest and in transit",
        ]
        checks["security_items_present"] = find_exact_lines(lines, security_expected)

        # Performance strategies (allow bullet markers, but exact words as content)
        perf_words = ["Caching", "Batching", "Indexing", "Compression", "Parallel Processing"]
        checks["performance_strategies_present"] = all(performance_item_present(lines, w) for w in perf_words)

        # Debugging Runbook steps exact lines
        debugging_expected = [
            "1. Reproduce the issue consistently",
            "2. Check logs for error messages",
            "3. Isolate the failing component",
            "4. Test with minimal configuration",
            "5. Apply fix and verify",
        ]
        checks["debugging_steps_present"] = find_exact_lines(lines, debugging_expected)

        # Migration Pre-Migration Checklist checkbox exact lines
        migration_expected = [
            "- [ ] Current system fully documented",
            "- [ ] Complete backup taken and verified",
            "- [ ] Target environment prepared",
            "- [ ] Rollback plan documented",
            "- [ ] Stakeholders notified",
        ]
        checks["migration_checklist_present"] = find_exact_lines(lines, migration_expected)

        # Cheatsheet Notes exact line
        cheatsheet_expected = "Issue: diagnose → isolate → fix → verify → document"
        checks["cheatsheet_line_present"] = any(line_equals(cheatsheet_expected, l) for l in lines)

    # 2) Check traceability.json exact structure
    trace_path = os.path.join(output_dir, "traceability.json")
    expected_trace = {
        "sections": {
            "Overview": ["intro"],
            "Quickstart": ["quickstart"],
            "Patterns": ["patterns"],
            "Debugging": ["debugging"],
            "Performance": ["performance"],
            "Security": ["security"],
            "Migration": ["migration"],
            "CheatsheetNotes": ["cheatsheet"],
        }
    }
    if os.path.isfile(trace_path):
        checks["has_traceability"] = True
        try:
            with open(trace_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Exact match: no extra keys or differences
            checks["traceability_exact_match"] = data == expected_trace
        except Exception:
            checks["traceability_exact_match"] = False

    # 3) Check implementation_plan.yaml for minimum actions and fields
    impl_path = os.path.join(output_dir, "implementation_plan.yaml")
    if os.path.isfile(impl_path):
        checks["has_implementation_plan"] = True
        impl_lines = read_lines(impl_path)
        # Count occurrences ignoring leading whitespace
        count_name = sum(1 for l in impl_lines if l.lstrip().startswith("- name:"))
        count_owner = sum(1 for l in impl_lines if l.lstrip().startswith("owner:"))
        count_due = sum(1 for l in impl_lines if l.lstrip().startswith("due_date:"))
        checks["impl_min_actions"] = count_name >= 5
        checks["impl_min_owner_lines"] = count_owner >= 5
        checks["impl_min_due_date_lines"] = count_due >= 5

    # Compute reward as ratio of passed checks
    scored_keys = [
        "has_bcc_playbook",
        "headers_present",
        "quickstart_steps_present",
        "patterns_bullets_present",
        "security_items_present",
        "performance_strategies_present",
        "debugging_steps_present",
        "migration_checklist_present",
        "cheatsheet_line_present",
        "has_traceability",
        "traceability_exact_match",
        "has_implementation_plan",
        "impl_min_actions",
        "impl_min_owner_lines",
        "impl_min_due_date_lines",
    ]
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    total = len(scored_keys)
    reward = float(passed) / float(total) if total > 0 else 0.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()