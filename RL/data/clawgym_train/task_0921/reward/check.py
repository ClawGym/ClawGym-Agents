import json
import os
import re
import sys

def read_file_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def get_section(lines, heading_line):
    # returns list of lines between heading_line and the next "## " heading (exclusive)
    # matches exact heading text
    indices = [i for i, ln in enumerate(lines) if ln.strip() == heading_line]
    if not indices:
        return []
    start = indices[0] + 1
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return lines[start:end]

def count_prefix_lines(lines, prefix):
    return sum(1 for ln in lines if ln.startswith(prefix))

def validate_primary_framework_line(lines):
    # Find a line that starts with "Primary framework: "
    prefix = "Primary framework: "
    matches = [ln for ln in lines if ln.startswith(prefix)]
    if not matches:
        return False
    # Consider the first match
    rest = matches[0][len(prefix):].strip()
    allowed = {"consequences", "duties", "character"}
    if rest in allowed:
        # ensure exactly one token and no extra content
        return True
    return False

def word_count(text):
    return len(text.split())

def is_int(x):
    return isinstance(x, int) or (isinstance(x, bool) is False and isinstance(x, (int,)) and not isinstance(x, bool))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        # analysis.md
        "analysis_exists": False,
        "analysis_headings_present": False,
        "analysis_primary_framework_valid": False,
        "analysis_thesis_objection_response_present": False,
        "analysis_reversal_phrase_present": False,
        "analysis_empirical_moral_counts_ok": False,
        # ferpa_checklist.md
        "ferpa_exists": False,
        "ferpa_headings_present": False,
        "ferpa_required_phrases_present": False,
        # executive_summary.txt
        "exec_exists": False,
        "exec_word_count_ok": False,
        "exec_has_recommendation_line": False,
        # rubric.json
        "rubric_exists": False,
        "rubric_valid": False,
        # citations.jsonl
        "citations_exists": False,
        "citations_min_lines": False,
        "citations_each_source_present": False,
        "citations_quotes_match_inputs": False,
    }

    # Prepare paths
    analysis_path = os.path.join(output_dir, "analysis.md")
    ferpa_path = os.path.join(output_dir, "ferpa_checklist.md")
    exec_path = os.path.join(output_dir, "executive_summary.txt")
    rubric_path = os.path.join(output_dir, "rubric.json")
    citations_path = os.path.join(output_dir, "citations.jsonl")

    # analysis.md checks
    if os.path.isfile(analysis_path):
        checks["analysis_exists"] = True
        lines = read_file_lines(analysis_path) or []
        # Required headings (exact match)
        required_headings = [
            "## Context",
            "## Defined Terms",
            "## Primary Framework",
            "## Thesis–Objection–Response",
            "## Reversal Test",
            "## Empirical vs Moral",
            "## Risks and Mitigations",
            "## Decision Options",
            "## Recommendation",
            "## Uncertainties",
        ]
        present = all(any(ln.strip() == h for ln in lines) for h in required_headings)
        checks["analysis_headings_present"] = present

        # Primary framework line validation
        if present and validate_primary_framework_line(get_section(lines, "## Primary Framework")):
            checks["analysis_primary_framework_valid"] = True
        else:
            # If not in section, attempt anywhere in file to be lenient but deterministic
            if validate_primary_framework_line(lines):
                checks["analysis_primary_framework_valid"] = True

        # Thesis/Objection/Response within its section
        tor_section = get_section(lines, "## Thesis–Objection–Response") if present else []
        if tor_section:
            has_thesis = any(ln.startswith("Thesis:") for ln in tor_section)
            has_objection = any(ln.startswith("Objection:") for ln in tor_section)
            has_response = any(ln.startswith("Response:") for ln in tor_section)
            if has_thesis and has_objection and has_response:
                checks["analysis_thesis_objection_response_present"] = True
        else:
            # Fallback: look anywhere for lines
            has_thesis = any(ln.startswith("Thesis:") for ln in lines)
            has_objection = any(ln.startswith("Objection:") for ln in lines)
            has_response = any(ln.startswith("Response:") for ln in lines)
            if has_thesis and has_objection and has_response:
                checks["analysis_thesis_objection_response_present"] = True

        # Reversal phrase anywhere
        text = "\n".join(lines)
        if "If I were the affected student" in text:
            checks["analysis_reversal_phrase_present"] = True

        # Empirical vs Moral counts under that section
        evm_section = get_section(lines, "## Empirical vs Moral") if present else []
        if evm_section:
            emp_count = count_prefix_lines(evm_section, "Empirical:")
            moral_count = count_prefix_lines(evm_section, "Moral:")
            if emp_count >= 2 and moral_count >= 2:
                checks["analysis_empirical_moral_counts_ok"] = True
        else:
            # Fallback: count anywhere
            emp_count = count_prefix_lines(lines, "Empirical:")
            moral_count = count_prefix_lines(lines, "Moral:")
            if emp_count >= 2 and moral_count >= 2:
                checks["analysis_empirical_moral_counts_ok"] = True

    # ferpa_checklist.md checks
    if os.path.isfile(ferpa_path):
        checks["ferpa_exists"] = True
        lines = read_file_lines(ferpa_path) or []
        # Exact section headings as exact lines (no hashes per spec)
        ferpa_required_headings = [
            "Education Records",
            "Directory Information",
            "Consent",
            "Exceptions",
            "Checklist",
        ]
        ferpa_present = all(any(ln.strip() == h for ln in lines) for h in ferpa_required_headings)
        checks["ferpa_headings_present"] = ferpa_present

        text = "\n".join(lines)
        # Case-insensitive search for required phrases
        low = text.lower()
        req_phrases_ok = ("legitimate educational interest" in low) and ("opt out" in low) and ("45 days" in low)
        checks["ferpa_required_phrases_present"] = req_phrases_ok

    # executive_summary.txt checks
    if os.path.isfile(exec_path):
        checks["exec_exists"] = True
        text = read_file_text(exec_path) or ""
        wc = word_count(text)
        if 200 <= wc <= 300:
            checks["exec_word_count_ok"] = True
        # Check a line beginning with "Recommendation:"
        lines = text.splitlines()
        if any(ln.startswith("Recommendation:") for ln in lines):
            checks["exec_has_recommendation_line"] = True

    # rubric.json checks
    if os.path.isfile(rubric_path):
        checks["rubric_exists"] = True
        try:
            with open(rubric_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            required_keys = ["structure", "precision", "separation", "reversal_test", "ferpa_coverage", "total"]
            if all(k in data for k in required_keys):
                subs = ["structure", "precision", "separation", "reversal_test", "ferpa_coverage"]
                valid_subs = True
                score_sum = 0
                for k in subs:
                    v = data.get(k)
                    if not isinstance(v, dict):
                        valid_subs = False
                        break
                    score = v.get("score", None)
                    notes = v.get("notes", None)
                    if not isinstance(score, int) or score not in {0, 1, 2}:
                        valid_subs = False
                        break
                    if not isinstance(notes, str) or len(notes) < 20:
                        valid_subs = False
                        break
                    score_sum += score
                total_ok = (data.get("total") == score_sum)
                if valid_subs and total_ok:
                    checks["rubric_valid"] = True
        except Exception:
            pass

    # citations.jsonl checks
    if os.path.isfile(citations_path):
        checks["citations_exists"] = True
        try:
            with open(citations_path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f.readlines()]
            non_empty_lines = [ln for ln in lines if ln.strip() != ""]
            if len(non_empty_lines) >= 3:
                checks["citations_min_lines"] = True
            allowed_sources = {"scenario.md", "interviews.csv", "policy.md"}
            seen_sources = set()
            all_quotes_match = True
            # Load input files for substring checks
            input_texts = {}
            for src in allowed_sources:
                p = os.path.join(input_dir, src)
                input_texts[src] = read_file_text(p) or ""
            for ln in non_empty_lines:
                try:
                    obj = json.loads(ln)
                except Exception:
                    all_quotes_match = False
                    continue
                # Validate keys and types
                if not isinstance(obj, dict):
                    all_quotes_match = False
                    continue
                if set(obj.keys()) != {"source", "quote", "line_start", "line_end"}:
                    all_quotes_match = False
                    continue
                source = obj.get("source")
                quote = obj.get("quote")
                line_start = obj.get("line_start")
                line_end = obj.get("line_end")
                if source not in allowed_sources:
                    all_quotes_match = False
                    continue
                if not isinstance(quote, str) or quote == "":
                    all_quotes_match = False
                    continue
                # Numeric checks
                if not isinstance(line_start, int) or line_start <= 0:
                    all_quotes_match = False
                    continue
                if not isinstance(line_end, int) or line_end < line_start:
                    all_quotes_match = False
                    continue
                # Substring check
                src_text = input_texts.get(source, "")
                if quote not in src_text:
                    all_quotes_match = False
                    continue
                seen_sources.add(source)
            if allowed_sources.issubset(seen_sources):
                checks["citations_each_source_present"] = True
            if all_quotes_match and checks["citations_min_lines"]:
                checks["citations_quotes_match_inputs"] = True
        except Exception:
            pass

    # Compute reward as average of passed checks; if no outputs present, reward is 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if any(v for v in checks.values()):
        reward = passed / total_checks
    else:
        reward = 0.0

    # Print result JSON (reward first)
    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()