import json
import os
import re
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def word_count(text):
    return len(text.split())

def find_os_findings_section_index(lines):
    # Find a line that titles the section as "OS Findings"
    # Allow optional Markdown heading markers (#) before the title
    for idx, line in enumerate(lines):
        stripped = line.strip()
        # Remove leading '#' and spaces for robust matching
        stripped_no_hash = stripped.lstrip("#").strip()
        if stripped_no_hash == "OS Findings":
            return idx
    return None

def extract_issue_names_from_diag(diag_array):
    names = set()
    for el in diag_array:
        if isinstance(el, dict):
            name = el.get("issue_name")
            if isinstance(name, str):
                names.add(name)
    return names

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "diagnosis_exists": False,
        "diagnosis_json_valid": False,
        "diagnosis_is_array": False,
        "diagnosis_elements_valid": False,
        "diagnosis_severity_sorted": False,
        "diagnosis_required_issues_present": False,
        "diagnosis_required_issues_have_text": False,
        "article_exists": False,
        "article_has_assessment_heading": False,
        "article_has_required_labels": False,
        "article_word_count_ok": False,
        "article_has_blockquotes": False,
        "article_has_colloquial_cue": False,
        "article_has_os_findings_section": False,
        "article_os_findings_listed_10_from_diag": False,
        "article_ends_with_numbered_list": False,
    }

    # Paths
    diag_path = os.path.join(output_dir, "diagnosis.json")
    article_path = os.path.join(output_dir, "article_it.md")

    # Constants
    required_issue_names = [
        "OpenClaw.Memory.SystemMemoryCritical",
        "OpenClaw.Memory.InsufficientTotalMemory",
        "OpenClaw.CPU.SystemCPUExhausted",
        "OpenClaw.CPU.HighIOWait",
        "OpenClaw.Disk.FilesystemFull",
        "OpenClaw.Network.NoDNSNameservers",
        "OpenClaw.Network.DNSResolutionFailed",
        "OpenClaw.Time.NTPServiceNotRunning",
        "OpenClaw.Kernel.NfConntrackTableFull",
        "OpenClaw.Disk.ReadOnlyFilesystem",
        "OpenClaw.Process.DStateProcessesFound",
        "OpenClaw.Kernel.THPEnabled",
        "OpenClaw.Locale.LocaleNotConfigured",
    ]
    allowed_severities = ["FATAL", "CRITICAL", "ERROR", "WARNING", "INFO"]
    severity_rank = { "FATAL": 5, "CRITICAL": 4, "ERROR": 3, "WARNING": 2, "INFO": 1 }

    # Diagnosis checks
    diag_data = None
    if os.path.isfile(diag_path):
        checks["diagnosis_exists"] = True
        diag_data, err = load_json_file(diag_path)
        if diag_data is not None:
            checks["diagnosis_json_valid"] = True
            if isinstance(diag_data, list):
                checks["diagnosis_is_array"] = True

                # Validate elements
                elements_valid = True
                severity_values = []
                names_present = set()
                required_have_text = True

                for el in diag_data:
                    if not isinstance(el, dict):
                        elements_valid = False
                        break
                    # Required fields
                    issue_name = el.get("issue_name")
                    severity = el.get("severity")
                    observed = el.get("observed")
                    remediation = el.get("remediation")

                    if not (isinstance(issue_name, str) and issue_name.strip() != ""):
                        elements_valid = False
                        break
                    if not (isinstance(severity, str) and severity.strip().upper() in allowed_severities):
                        elements_valid = False
                        break
                    if not (isinstance(observed, str) and observed.strip() != ""):
                        elements_valid = False
                        break
                    if not (isinstance(remediation, str) and remediation.strip() != ""):
                        elements_valid = False
                        break

                    names_present.add(issue_name)
                    severity_values.append(severity.strip().upper())

                if elements_valid:
                    checks["diagnosis_elements_valid"] = True

                    # Severity sorted (non-increasing by rank)
                    sorted_ok = True
                    last_rank = None
                    for sev in severity_values:
                        r = severity_rank.get(sev)
                        if last_rank is None:
                            last_rank = r
                        else:
                            if r > last_rank:
                                # severity increased, violates desired non-increasing order
                                sorted_ok = False
                                break
                            last_rank = r
                    if sorted_ok:
                        checks["diagnosis_severity_sorted"] = True

                    # Required issues present
                    if all(req in names_present for req in required_issue_names):
                        checks["diagnosis_required_issues_present"] = True

                        # For required issues, verify observed and remediation are non-empty strings
                        # Build lookup by name
                        by_name = {}
                        for el in diag_data:
                            by_name.setdefault(el.get("issue_name"), []).append(el)
                        for req in required_issue_names:
                            entries = by_name.get(req, [])
                            # Consider it satisfied if at least one entry has non-empty observed/remediation
                            ok_any = False
                            for e in entries:
                                if (isinstance(e.get("observed"), str) and e.get("observed").strip() != "" and
                                    isinstance(e.get("remediation"), str) and e.get("remediation").strip() != ""):
                                    ok_any = True
                                    break
                            if not ok_any:
                                required_have_text = False
                                break
                        if required_have_text:
                            checks["diagnosis_required_issues_have_text"] = True

            # else: keep as False
        # else: keep False for json validity and rest
    # else: remains False

    # Article checks
    article_text = ""
    article_lines = []
    if os.path.isfile(article_path):
        checks["article_exists"] = True
        try:
            with open(article_path, "r", encoding="utf-8") as f:
                article_text = f.read()
                article_lines = article_text.splitlines()
        except Exception:
            article_text = ""
            article_lines = []

        if "MEDIUM ARTICLE ASSESSMENT" in article_text:
            checks["article_has_assessment_heading"] = True

        # Required labels presence
        labels_required = [
            "Article Goal:",
            "Reader Type:",
            "Authority Mode:",
            "THOUGHT STRUCTURE",
            "READABILITY PRESSURE",
            "MAIN PROBLEMS",
            "REBUILD PLAN",
            "NEXT STEP",
        ]
        if all(label in article_text for label in labels_required):
            checks["article_has_required_labels"] = True

        # Word count
        if word_count(article_text) >= 800:
            checks["article_word_count_ok"] = True

        # At least 3 Markdown blockquotes (lines starting with "> ")
        blockquote_count = 0
        for line in article_lines:
            if line.startswith("> "):
                blockquote_count += 1
        if blockquote_count >= 3:
            checks["article_has_blockquotes"] = True

        # Italian colloquial cue
        colloquials = ["Allora", "Comunque", "Ma dai", "figurati", "tantissimo", "Boh", "eh", "Senti", "guarda"]
        lower_text = article_text.lower()
        if any(c.lower() in lower_text for c in colloquials):
            checks["article_has_colloquial_cue"] = True

        # OS Findings section detection
        idx = find_os_findings_section_index(article_lines)
        if idx is not None:
            checks["article_has_os_findings_section"] = True

            # Count how many issue identifiers from diagnosis.json appear after the OS Findings section
            diag_issue_names = set()
            if checks["diagnosis_json_valid"] and checks["diagnosis_is_array"]:
                diag_issue_names = extract_issue_names_from_diag(diag_data)

            if diag_issue_names:
                text_after = "\n".join(article_lines[idx+1:]) if idx + 1 < len(article_lines) else ""
                count_listed = 0
                listed_set = set()
                for name in diag_issue_names:
                    if name in text_after:
                        listed_set.add(name)
                count_listed = len(listed_set)
                if count_listed >= 10:
                    checks["article_os_findings_listed_10_from_diag"] = True

        # Ends with a numbered Markdown list of at least 5 items
        # Consider the last contiguous block of lines matching ^\d+\.\s
        # Ignore trailing blank lines
        tail = article_lines[:]
        # Remove trailing empty lines
        while tail and tail[-1].strip() == "":
            tail.pop()
        num_block = 0
        i = len(tail) - 1
        numbered_pattern = re.compile(r"^\s*\d+\.\s+")
        while i >= 0 and numbered_pattern.match(tail[i]):
            num_block += 1
            i -= 1
        if num_block >= 5 and num_block > 0:
            # Ensure no non-list content after the last numbered item (already ensured by trimming)
            checks["article_ends_with_numbered_list"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or both key artifacts missing, reward must be 0.0
    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        # If both required artifacts missing or invalid, ensure 0.0
        if not checks["diagnosis_exists"] and not checks["article_exists"]:
            reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()