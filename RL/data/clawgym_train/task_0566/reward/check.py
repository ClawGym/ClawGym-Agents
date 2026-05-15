import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_results_tsv(text):
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    return lines

def is_hex_commit(s):
    return bool(re.fullmatch(r"[0-9a-f]{7,40}", s))

def parse_float(s):
    try:
        return float(s.strip())
    except Exception:
        return None

def parse_int(s):
    try:
        v = int(s.strip())
        return v
    except Exception:
        return None

def extract_print_val_bpb(text):
    # Find all print statements of the exact form print("val_bpb:", <float>) or with single quotes
    # Capture the float as group 1. Allow optional spaces.
    pattern = re.compile(r'print\(\s*[\'"]val_bpb:[\'"]\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*\)')
    matches = pattern.findall(text)
    return matches  # list of strings

def word_count(s):
    return len(re.findall(r"\b\w+\b", s))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Existence checks
        "has_plan_md": False,
        "has_results_tsv": False,
        "has_target_py": False,
        "has_learned_md": False,
        # Plan content checks
        "plan_has_required_lines_exact": False,
        "plan_mentions_verification_gates": False,
        "plan_mentions_git_branch_isolation": False,
        "plan_mentions_reputation_threshold": False,
        # Results TSV structural checks
        "results_header_ok": False,
        "results_rows_count_ok": False,
        "results_iteration0_baseline_keep_ok": False,
        "results_commit_hex_all_ok": False,
        "results_status_values_ok": False,
        "results_fields_types_ok": False,
        "results_at_least_two_keeps": False,
        "results_keep_strictly_decreasing": False,
        "results_has_discard_or_crash": False,
        # Target file checks
        "target_first_line_commit_format_ok": False,
        "target_contains_metric_parser_literal": False,
        "target_print_val_bpb_singleton_ok": False,
        # Cross-file consistency
        "cross_commit_matches_best_keep": False,
        "cross_metric_matches_best_keep": False,
        # Learnings checks
        "learned_word_count_ok": False,
        "learned_contains_required_terms": False,
    }

    # Paths
    plan_path = os.path.join(output_dir, "plan.md")
    results_path = os.path.join(output_dir, "results.tsv")
    target_path = os.path.join(output_dir, "target", "target.py")
    learned_path = os.path.join(output_dir, ".state", "learnings", "learned.md")

    # Read files if present
    plan_text = None
    if os.path.isfile(plan_path):
        checks["has_plan_md"] = True
        plan_text = read_text(plan_path)

    results_text = None
    if os.path.isfile(results_path):
        checks["has_results_tsv"] = True
        results_text = read_text(results_path)

    target_text = None
    if os.path.isfile(target_path):
        checks["has_target_py"] = True
        target_text = read_text(target_path)

    learned_text = None
    if os.path.isfile(learned_path):
        checks["has_learned_md"] = True
        learned_text = read_text(learned_path)

    # Plan checks
    if checks["has_plan_md"] and isinstance(plan_text, str):
        # Required lines (case-insensitive on keys; we compare full line lowercased)
        lines = [ln.strip().lower() for ln in plan_text.splitlines()]
        req1 = "metric_command: python output/target/target.py"
        req2 = "metric_parser: val_bpb"
        req3 = "minimize: true"
        has_req = (req1 in lines) and (req2 in lines) and (req3 in lines)
        checks["plan_has_required_lines_exact"] = has_req

        # Verification gates mentions: words 'file', 'syntax', 'tests', 'lint' anywhere
        lower_plan = plan_text.lower()
        gates = all(w in lower_plan for w in ["file", "syntax", "tests", "lint"])
        checks["plan_mentions_verification_gates"] = gates

        # Git branch isolation: look for 'git' and ('branch' or 'isolation')
        has_git = "git" in lower_plan
        has_branch_or_isolation = ("branch" in lower_plan) or ("isolation" in lower_plan)
        checks["plan_mentions_git_branch_isolation"] = has_git and has_branch_or_isolation

        # Reputation suspension threshold 0.2 present
        checks["plan_mentions_reputation_threshold"] = "0.2" in lower_plan

    # Results TSV checks
    best_keep = None  # tuple (metric_value: float, commit: str)
    keep_values = []
    keep_commits = []
    if checks["has_results_tsv"] and isinstance(results_text, str):
        lines = parse_results_tsv(results_text)
        if len(lines) >= 1:
            header_expected = "iteration\tcommit\tmetric_value\tstatus\thypothesis\tduration_s\treputation"
            if lines[0] == header_expected:
                checks["results_header_ok"] = True

        # Parse rows
        rows = []
        for i, ln in enumerate(lines[1:], start=1):
            if not ln.strip():
                continue
            parts = ln.split("\t")
            if len(parts) != 7:
                rows.append(None)
                continue
            iteration_s, commit_s, metric_s, status_s, hypothesis_s, duration_s, reputation_s = parts
            rows.append((iteration_s.strip(), commit_s.strip(), metric_s.strip(), status_s.strip(), hypothesis_s.strip(), duration_s.strip(), reputation_s.strip()))

        if len(rows) >= 6:
            checks["results_rows_count_ok"] = True

        # Validate each row fields
        all_commits_ok = True
        all_status_ok = True
        all_types_ok = True
        statuses_allowed = {"keep", "discard", "crash"}
        baseline_ok = False
        total_keeps = 0
        any_discard_or_crash = False
        keeps_in_order = []
        for r in rows:
            if r is None:
                all_types_ok = False
                continue
            iteration_s, commit_s, metric_s, status_s, hypothesis_s, duration_s, reputation_s = r
            # commit pattern
            if not is_hex_commit(commit_s):
                all_commits_ok = False
            # status
            status_l = status_s.lower()
            if status_l not in statuses_allowed:
                all_status_ok = False
            # types
            metric_v = parse_float(metric_s)
            duration_v = parse_int(duration_s)
            reputation_v = parse_float(reputation_s)
            if metric_v is None or duration_v is None or reputation_v is None:
                all_types_ok = False
            else:
                if duration_v <= 0 or not (0.0 <= reputation_v <= 1.0):
                    all_types_ok = False

            # Baseline check
            if iteration_s.strip() == "0" and status_l == "keep" and hypothesis_s.strip().lower() == "baseline":
                baseline_ok = True

            # Keep counting
            if status_l == "keep":
                total_keeps += 1
                if metric_v is not None:
                    keeps_in_order.append((metric_v, commit_s))
            if status_l in ("discard", "crash"):
                any_discard_or_crash = True

        checks["results_commit_hex_all_ok"] = all_commits_ok and len(rows) > 0
        checks["results_status_values_ok"] = all_status_ok and len(rows) > 0
        checks["results_fields_types_ok"] = all_types_ok and len(rows) > 0
        checks["results_iteration0_baseline_keep_ok"] = baseline_ok
        checks["results_at_least_two_keeps"] = total_keeps >= 2
        checks["results_has_discard_or_crash"] = any_discard_or_crash

        # Strictly decreasing among keeps
        strictly_decreasing = True
        prev = None
        for metric_v, commit_s in keeps_in_order:
            if prev is not None and not (metric_v < prev):
                strictly_decreasing = False
                break
            prev = metric_v
        checks["results_keep_strictly_decreasing"] = strictly_decreasing and len(keeps_in_order) >= 2

        # Determine best keep (lowest metric)
        if keeps_in_order:
            best = min(keeps_in_order, key=lambda t: t[0])
            best_keep = (best[0], best[1])
            keep_values = [kv for kv, _ in keeps_in_order]
            keep_commits = [kc for _, kc in keeps_in_order]

    # Target file checks + cross-file consistency
    printed_val = None
    printed_val_ok_singleton = False
    first_line_commit = None
    if checks["has_target_py"] and isinstance(target_text, str):
        lines = target_text.splitlines()
        if len(lines) >= 1:
            first_line = lines[0].strip()
            # Expect a comment line beginning with '#'
            # Accept patterns like "# final_version_commit: <hex>"
            m = re.fullmatch(r"#\s*final_version_commit:\s*([0-9a-f]{7,40})\s*", first_line)
            if m:
                first_line_commit = m.group(1)
                checks["target_first_line_commit_format_ok"] = True

        # metric_parser literal
        if "metric_parser=val_bpb" in target_text:
            checks["target_contains_metric_parser_literal"] = True

        # print("val_bpb:", <float>) singleton
        prints = extract_print_val_bpb(target_text)
        if len(prints) == 1:
            try:
                printed_val = float(prints[0])
                printed_val_ok_singleton = True
            except Exception:
                printed_val_ok_singleton = False
        checks["target_print_val_bpb_singleton_ok"] = printed_val_ok_singleton

        # Cross checks only if we have best_keep and parsed values
        if best_keep is not None and first_line_commit is not None:
            checks["cross_commit_matches_best_keep"] = (first_line_commit == best_keep[1])

        if best_keep is not None and printed_val is not None:
            # Tolerance 1e-9
            checks["cross_metric_matches_best_keep"] = abs(printed_val - best_keep[0]) <= 1e-9

    # Learnings checks
    if checks["has_learned_md"] and isinstance(learned_text, str):
        wc_ok = word_count(learned_text) >= 150
        checks["learned_word_count_ok"] = wc_ok
        lt = learned_text.lower()
        required_terms = ["pattern", "verification", "reputation", "plateau", "hallucination"]
        checks["learned_contains_required_terms"] = all(term in lt for term in required_terms)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or none of the required files exist, ensure reward is 0.0
    required_files_exist = checks["has_plan_md"] or checks["has_results_tsv"] or checks["has_target_py"] or checks["has_learned_md"]
    if not required_files_exist:
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()