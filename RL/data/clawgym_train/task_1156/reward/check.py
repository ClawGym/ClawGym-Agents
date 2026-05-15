import json
import sys
import re
from pathlib import Path
from typing import Optional, List, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _contains_any(text: str, needles: List[str], case_insensitive: bool = True) -> bool:
    if text is None:
        return False
    t = text.lower() if case_insensitive else text
    for n in needles:
        if not n:
            continue
        nn = n.lower() if case_insensitive else n
        if nn in t:
            return True
    return False


def _sentence_count(text: str) -> int:
    if not text:
        return 0
    # Count sentences by ., !, ? boundaries
    parts = re.split(r"[.!?]+", text)
    return sum(1 for p in parts if p.strip())


def _find_section_bullets(md: str, header_name: str) -> List[str]:
    if not md:
        return []
    lines = md.splitlines()
    header_re = re.compile(rf"^\s{{0,3}}#{1,6}\s*{re.escape(header_name)}\s*$", re.IGNORECASE)
    start_idx = None
    for i, line in enumerate(lines):
        if header_re.match(line.strip()):
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    bullets = []
    for i in range(start_idx, len(lines)):
        line = lines[i]
        if re.match(r"^\s{0,3}#{1,6}\s+\S", line):  # next header starts
            break
        if re.match(r"^\s*[-*]\s+\S", line):
            bullets.append(line.strip())
    return bullets


def _extract_relevant_log_lines(log_text: str) -> List[str]:
    if not log_text:
        return []
    lines = [l.rstrip("\n") for l in log_text.splitlines()]
    relevant = []
    for ln in lines:
        if ("divideByZeroThrows" in ln) or ("AssertionFailedError" in ln) or ("Expected java.lang.IllegalArgumentException" in ln):
            relevant.append(ln)
        if "CalculatorTest.java:12" in ln or "CalculatorTest.divideByZeroThrows:12" in ln:
            relevant.append(ln)
    # Deduplicate preserving order
    seen = set()
    out = []
    for ln in relevant:
        if ln not in seen and ln.strip():
            seen.add(ln)
            out.append(ln)
    return out


def _extract_method_body(java_src: str, signature_regex: str) -> Optional[str]:
    """
    Find the body of a Java method by signature regex and return the text inside { ... }.
    """
    if not java_src:
        return None
    m = re.search(signature_regex, java_src, flags=re.DOTALL)
    if not m:
        # Try to find the start by locating the signature and the opening brace
        sig = re.search(signature_regex.replace("(?:", "("), java_src)
        if not sig:
            return None
        start = sig.end()
    else:
        start = m.end()
    # Find first brace after signature
    brace_idx = java_src.find("{", start)
    if brace_idx == -1:
        return None
    depth = 0
    for i in range(brace_idx, len(java_src)):
        ch = java_src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                # Return inside braces without outer braces
                return java_src[brace_idx + 1:i]
    return None


def _java_divide_checks(java_src: str) -> Tuple[bool, bool, bool]:
    """
    Returns a tuple:
    - throws_on_zero: True if divide method checks b==0 and throws IllegalArgumentException("Division by zero")
    - exact_message: True if message string exactly matches
    - no_return_zero: True if divide method body does NOT contain 'return 0;'
    """
    if not java_src:
        return False, False, False
    # Extract divide method body
    body = _extract_method_body(java_src, r"\bpublic\s+int\s+divide\s*\(\s*int\s+a\s*,\s*int\s+b\s*\)")
    if body is None:
        return False, False, False
    has_b_zero_check = re.search(r"\bif\s*\(\s*b\s*==\s*0\s*\)", body) is not None
    throws_line = 'throw new IllegalArgumentException("Division by zero")'
    throws_present = throws_line in body
    throws_on_zero = has_b_zero_check and throws_present
    exact_message = '"Division by zero"' in body and throws_present
    no_return_zero = 'return 0;' not in body
    return throws_on_zero, exact_message, no_return_zero


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    calc_path = workspace / "input" / "src" / "main" / "java" / "com" / "example" / "Calculator.java"
    readme_path = workspace / "input" / "README.md"
    build_log_path = workspace / "input" / "build.log"
    analysis_path = workspace / "analysis" / "error_analysis.md"
    email_path = workspace / "output" / "help_request_email.txt"

    scores = {
        "calculator_divide_throws_illegalargumentexception_zero": 0.0,
        "calculator_divide_message_exact": 0.0,
        "calculator_divide_no_return_zero": 0.0,
        "readme_updates_behavior_documented": 0.0,
        "readme_removed_known_issues": 0.0,
        "readme_added_what_i_learned_section": 0.0,
        "readme_what_i_learned_bullets_count": 0.0,
        "readme_exception_lesson_present": 0.0,
        "error_analysis_file_exists": 0.0,
        "error_analysis_includes_failing_test_name_and_location": 0.0,
        "error_analysis_includes_error_excerpt_lines": 0.0,
        "error_analysis_explanation_present": 0.0,
        "error_analysis_reproduction_commands_present": 0.0,
        "help_email_exists": 0.0,
        "help_email_subject_present": 0.0,
        "help_email_includes_error_snippet": 0.0,
        "help_email_includes_reproduction_steps": 0.0,
        "help_email_describes_fix": 0.0,
        "help_email_requests_resources": 0.0,
        "help_email_has_friendly_signoff": 0.0,
    }

    # Load files
    calc_src = _read_text(calc_path) or ""
    readme = _read_text(readme_path) or ""
    build_log = _read_text(build_log_path) or ""
    analysis_md = _read_text(analysis_path)
    email_txt = _read_text(email_path)

    # Calculator.java checks (strictly focus on required behavior change)
    if calc_src:
        throws_on_zero, exact_message, no_return_zero = _java_divide_checks(calc_src)
        scores["calculator_divide_throws_illegalargumentexception_zero"] = 1.0 if throws_on_zero else 0.0
        scores["calculator_divide_message_exact"] = 1.0 if exact_message else 0.0
        scores["calculator_divide_no_return_zero"] = 1.0 if no_return_zero else 0.0

    # README checks
    if readme:
        # Must describe divide(a,b) behavior when b == 0: throws IllegalArgumentException with message "Division by zero"
        mentions_divide = ("divide(" in readme) or ("divide(a,b)" in readme) or ("divide a, b" in readme) or ("divide a,b" in readme)
        mentions_exception = "IllegalArgumentException" in readme or _contains_any(readme, ["throws", "throw"])
        mentions_message = "Division by zero" in readme
        does_not_claim_returns_zero = not _contains_any(readme, ["returns 0 when b is 0", "returns 0 when b==0", "returns 0 to avoid crashing"])
        if mentions_divide and mentions_exception and mentions_message and does_not_claim_returns_zero:
            scores["readme_updates_behavior_documented"] = 1.0

        # Known issues removed
        scores["readme_removed_known_issues"] = 1.0 if not re.search(r"\bKnown issues\b", readme, flags=re.IGNORECASE) else 0.0

        # "What I learned" section
        bullets = _find_section_bullets(readme, "What I learned")
        if bullets:
            scores["readme_added_what_i_learned_section"] = 1.0
            if 2 <= len(bullets) <= 4:
                scores["readme_what_i_learned_bullets_count"] = 1.0
            # Exception-handling lesson presence
            if any(_contains_any(b, ["exception", "IllegalArgumentException", "throw", "JUnit", "testing"], case_insensitive=True) for b in bullets):
                scores["readme_exception_lesson_present"] = 1.0

    # error_analysis.md checks
    if analysis_md is not None:
        scores["error_analysis_file_exists"] = 1.0
        analysis_text = analysis_md or ""
        # Failing test name and location
        has_test_name = "divideByZeroThrows" in analysis_text
        has_location = ("CalculatorTest.java:12" in analysis_text) or ("CalculatorTest.divideByZeroThrows:12" in analysis_text)
        if has_test_name and has_location:
            scores["error_analysis_includes_failing_test_name_and_location"] = 1.0

        # Include 3–8 relevant error lines copied from build.log
        relevant_log_lines = _extract_relevant_log_lines(build_log)
        matched_lines = 0
        for ln in relevant_log_lines:
            if ln and ln in analysis_text:
                matched_lines += 1
        if matched_lines >= 3:
            scores["error_analysis_includes_error_excerpt_lines"] = 1.0

        # Explanation presence: 3–5 sentences mentioning cause and fix in general terms
        sent_count = _sentence_count(analysis_text)
        mentions_cause = _contains_any(analysis_text, ["cause", "root", "because", "due to"])
        mentions_fix = _contains_any(analysis_text, ["fix", "fixed", "resolve", "resolved", "change"])
        mentions_topic = _contains_any(analysis_text, ["IllegalArgumentException", "divide", "zero", "0", "throw"])
        if 3 <= sent_count <= 6 and mentions_topic and (mentions_cause or mentions_fix):
            scores["error_analysis_explanation_present"] = 1.0

        # Reproduction commands
        if _contains_any(analysis_text, ["mvn test", "mvn -q test"], True):
            scores["error_analysis_reproduction_commands_present"] = 1.0

    # help_request_email.txt checks
    if email_txt is not None:
        scores["help_email_exists"] = 1.0
        email_text = email_txt or ""
        # Subject line
        if any(line.strip().lower().startswith("subject:") for line in email_text.splitlines()):
            scores["help_email_subject_present"] = 1.0
        # Error snippet from build.log (most relevant line)
        if "Expected java.lang.IllegalArgumentException to be thrown, but nothing was thrown." in email_text:
            scores["help_email_includes_error_snippet"] = 1.0
        # Minimal reproduction steps (any bullet line)
        if any(re.match(r"^\s*[-*]\s+\S", line) for line in email_text.splitlines()):
            scores["help_email_includes_reproduction_steps"] = 1.0
        # Describes fix
        if _contains_any(email_text, ["IllegalArgumentException"]) and _contains_any(email_text, ["Division by zero"]) and _contains_any(email_text, ["throw"]):
            scores["help_email_describes_fix"] = 1.0
        # Requests resources on Java exception handling and JUnit testing
        if _contains_any(email_text, ["exception handling", "exception"]) and _contains_any(email_text, ["junit", "testing"]):
            scores["help_email_requests_resources"] = 1.0
        # Friendly sign-off (in last 5 lines)
        tail_text = "\n".join(email_text.splitlines()[-5:]) if email_text else ""
        if _contains_any(tail_text, ["thanks", "thank you", "best", "cheers", "sincerely", "regards"], True):
            scores["help_email_has_friendly_signoff"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()