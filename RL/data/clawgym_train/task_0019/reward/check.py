import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_bytes_safe(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_files_with_sizes(base: Path) -> List[Tuple[str, int]]:
    results: List[Tuple[str, int]] = []
    if not base.exists():
        return results
    for p in sorted(base.rglob("*")):
        if p.is_file():
            try:
                rel = p.relative_to(base).as_posix()
            except Exception:
                rel = str(p).replace(str(base) + "/", "")
            try:
                size = p.stat().st_size
            except Exception:
                size = -1
            results.append((rel, size))
    return results


def parse_inventory_csv(path: Path) -> Optional[List[Tuple[str, int]]]:
    try:
        rows: List[Tuple[str, int]] = []
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.reader(f)
            header = next(rdr, None)
            if header is None:
                return None
            if [h.strip() for h in header] != ["path", "bytes"]:
                return None
            for row in rdr:
                if len(row) != 2:
                    return None
                rpath = row[0].strip()
                try:
                    rbytes = int(row[1].strip())
                except Exception:
                    return None
                rows.append((rpath, rbytes))
        return rows
    except Exception:
        return None


def find_line_number(path: Path, substring: str) -> Optional[int]:
    text = read_text_safe(path)
    if text is None:
        return None
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        if substring in line:
            return idx
    return None


def compute_expected_findings(input_project: Path) -> List[Dict]:
    findings: List[Dict] = []

    cfg_path = input_project / "config" / "test_config.yaml"
    test_login_path = input_project / "tests" / "test_login.py"

    # Accept insecure certs in YAML
    line_accept = find_line_number(cfg_path, "acceptInsecureCerts: true")
    if line_accept:
        findings.append({
            "file": "config/test_config.yaml",
            "line": line_accept,
            "tokens": ["acceptInsecureCerts"],
        })

    # ignore certificate errors option in YAML
    line_ignore = find_line_number(cfg_path, "--ignore-certificate-errors")
    if line_ignore:
        findings.append({
            "file": "config/test_config.yaml",
            "line": line_ignore,
            "tokens": ["ignore-certificate-errors"],
        })

    # HTTP remote WebDriver URL in YAML
    line_http = find_line_number(cfg_path, 'remoteWebDriverUrl: "http://')
    if line_http:
        findings.append({
            "file": "config/test_config.yaml",
            "line": line_http,
            "tokens": ["remoteWebDriverUrl", "http://"],
        })

    # Plaintext username/email in YAML
    line_user = find_line_number(cfg_path, "qa_manager@example.com")
    if line_user:
        findings.append({
            "file": "config/test_config.yaml",
            "line": line_user,
            "tokens": ["username", "email", "@", "credential"],
        })

    # Plaintext password in YAML
    line_pwd = find_line_number(cfg_path, "password:")
    if line_pwd:
        findings.append({
            "file": "config/test_config.yaml",
            "line": line_pwd,
            "tokens": ["password", "secret"],
        })

    # Plaintext apiToken in YAML
    line_token = find_line_number(cfg_path, "apiToken:")
    if line_token:
        findings.append({
            "file": "config/test_config.yaml",
            "line": line_token,
            "tokens": ["apiToken", "token"],
        })

    # DEBUG logging level in YAML
    line_debug = find_line_number(cfg_path, '"DEBUG"')
    if line_debug:
        findings.append({
            "file": "config/test_config.yaml",
            "line": line_debug,
            "tokens": ["DEBUG", "logging"],
        })

    # Printing credentials in test_login.py
    line_print_creds = find_line_number(test_login_path, "Attempting login with credentials")
    if line_print_creds:
        findings.append({
            "file": "tests/test_login.py",
            "line": line_print_creds,
            "tokens": ["print", "credentials", "password", "username"],
        })

    return findings


def inventory_matches(dir_path: Path, csv_path: Path) -> bool:
    actual = list_files_with_sizes(dir_path)
    csv_rows = parse_inventory_csv(csv_path)
    if csv_rows is None:
        return False
    actual_map = {p: s for p, s in actual}
    csv_map = {p: s for p, s in csv_rows}
    return actual_map == csv_map


def check_security_report(report_path: Path, input_project: Path) -> Tuple[float, float, float]:
    present = 0.0
    structure = 0.0
    minimum = 0.0

    if not report_path.exists():
        return present, structure, minimum

    present = 1.0
    data = load_json_safe(report_path)
    if not isinstance(data, dict):
        return present, structure, minimum

    if data.get("project") != "input/selenium_project":
        return present, structure, minimum

    findings = data.get("findings")
    if not isinstance(findings, list):
        return present, structure, minimum

    # Structure validation
    required_keys = {"file", "line", "issue", "severity", "evidence", "recommendation"}
    severities = {"low", "medium", "high"}
    structure_ok = True
    for item in findings:
        if not isinstance(item, dict):
            structure_ok = False
            break
        if not required_keys.issubset(item.keys()):
            structure_ok = False
            break
        if not isinstance(item.get("file"), str):
            structure_ok = False
            break
        if not isinstance(item.get("line"), int):
            structure_ok = False
            break
        if not isinstance(item.get("issue"), str):
            structure_ok = False
            break
        if not isinstance(item.get("evidence"), str):
            structure_ok = False
            break
        if not isinstance(item.get("recommendation"), str):
            structure_ok = False
            break
        sev = item.get("severity")
        if not isinstance(sev, str) or sev.lower() not in severities:
            structure_ok = False
            break
    if not structure_ok:
        return present, structure, minimum
    structure = 1.0

    # Minimum findings present
    expected = compute_expected_findings(input_project)
    if not expected:
        minimum = 1.0 if isinstance(findings, list) and len(findings) > 0 else 0.0
        return present, structure, minimum

    def has_match(exp: Dict) -> bool:
        for it in findings:
            if it.get("file") != exp["file"]:
                continue
            if it.get("line") != exp["line"]:
                continue
            issue = (it.get("issue") or "").lower()
            evidence = (it.get("evidence") or "").lower()
            tokens = [t.lower() for t in exp.get("tokens", [])]
            if any(tok in issue or tok in evidence for tok in tokens):
                return True
        return False

    all_present = all(has_match(e) for e in expected)
    minimum = 1.0 if all_present else 0.0
    return present, structure, minimum


def hardened_mirror_check(input_project: Path, hardened_project: Path) -> float:
    if not hardened_project.exists():
        return 0.0
    if not input_project.exists():
        # Cannot assert mirror integrity without a source to mirror
        return 0.0
    allowed_modified = {
        "config/test_config.yaml",
        "tests/test_login.py",
        "conftest.py",
    }
    input_files = list_files_with_sizes(input_project)
    hardened_files = set(p for p, _ in list_files_with_sizes(hardened_project))

    # All input files should exist in hardened
    for rel_path, _ in input_files:
        if rel_path not in hardened_files:
            return 0.0

    # Compare contents for files not allowed to be modified
    for rel_path, _ in input_files:
        if rel_path in allowed_modified:
            continue
        src = read_bytes_safe(input_project / rel_path)
        dst = read_bytes_safe(hardened_project / rel_path)
        if src is None or dst is None:
            return 0.0
        if src != dst:
            return 0.0

    return 1.0


def hardened_config_checks(hardened_project: Path) -> Dict[str, float]:
    scores = {
        "hardened_config_no_insecure_certs": 0.0,
        "hardened_config_no_ignore_cert_errors": 0.0,
        "hardened_config_no_plaintext_secrets_or_emails": 0.0,
        "hardened_config_remote_url_placeholder": 0.0,
        "hardened_config_logging_not_debug": 0.0,
    }
    cfg_path = hardened_project / "config" / "test_config.yaml"
    text = read_text_safe(cfg_path)
    if text is None:
        return scores

    lines = text.splitlines()

    # No acceptInsecureCerts true
    insecure_true = any("acceptInsecureCerts" in ln and re.search(r":\s*true\b", ln, flags=re.IGNORECASE) for ln in lines)
    if not insecure_true:
        # If key is absent or explicitly not true, it's acceptable
        scores["hardened_config_no_insecure_certs"] = 1.0

    # No '--ignore-certificate-errors'
    if "--ignore-certificate-errors" not in text:
        scores["hardened_config_no_ignore_cert_errors"] = 1.0

    # No plaintext secrets or emails: forbid 'password' or 'apiToken' anywhere and email-like values
    no_password_or_token = ("password" not in text) and ("apiToken" not in text)
    no_email_like = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]+", text) is None
    if no_password_or_token and no_email_like:
        scores["hardened_config_no_plaintext_secrets_or_emails"] = 1.0

    # remoteWebDriverUrl placeholder required (e.g., ${REMOTE_WEBDRIVER_URL})
    placeholder_ok = False
    for ln in lines:
        if "remoteWebDriverUrl" in ln:
            if "${" in ln and "}" in ln:
                placeholder_ok = True
            else:
                placeholder_ok = False
            break
    if placeholder_ok:
        scores["hardened_config_remote_url_placeholder"] = 1.0

    # Logging level not DEBUG (case-insensitive)
    # Strict: ensure no line sets logging level to DEBUG
    debug_level = re.search(r"logging:\s*[\s\S]*?level:\s*\"?debug\"?", text, flags=re.IGNORECASE)
    if debug_level is None:
        scores["hardened_config_logging_not_debug"] = 1.0

    return scores


def hardened_tests_checks(hardened_project: Path) -> Dict[str, float]:
    scores = {
        "hardened_tests_use_env_vars": 0.0,
        "hardened_tests_no_insecure_settings": 0.0,
        "hardened_tests_no_secrets_output": 0.0,
    }
    test_login = hardened_project / "tests" / "test_login.py"
    conftest = hardened_project / "conftest.py"
    if not test_login.exists() or not conftest.exists():
        return scores

    tl_text = read_text_safe(test_login) or ""
    ct_text = read_text_safe(conftest) or ""
    combined = tl_text + "\n" + ct_text

    # Use env vars for credentials/tokens: ensure TEST_USERNAME, TEST_PASSWORD, API_TOKEN referenced and via os.getenv/os.environ
    uses_env = ("os.getenv" in combined) or ("os.environ" in combined)
    has_user = "TEST_USERNAME" in combined
    has_pass = "TEST_PASSWORD" in combined
    has_token = "API_TOKEN" in combined
    if uses_env and has_user and has_pass and has_token:
        scores["hardened_tests_use_env_vars"] = 1.0

    # No insecure settings: no ignore-certificate-errors and no acceptInsecureCerts set to true
    insecure_ignore = ("ignore-certificate-errors" in combined)
    insecure_accept_true = re.search(r"acceptInsecureCerts[^\n]*\b[Tt]rue\b", combined) is not None
    if not insecure_ignore and not insecure_accept_true:
        scores["hardened_tests_no_insecure_settings"] = 1.0

    # No printing/logging secrets: avoid printing username/password/token
    def has_secret_output(txt: str) -> bool:
        # Detect print/log lines with sensitive terms
        sensitive = re.compile(r"(user(name)?|pass(word)?|token)", flags=re.IGNORECASE)
        for ln in txt.splitlines():
            ln_stripped = ln.strip()
            if ln_stripped.startswith("#"):
                continue
            if "print(" in ln_stripped and sensitive.search(ln_stripped):
                return True
            if ("logging." in ln_stripped or "logger." in ln_stripped) and sensitive.search(ln_stripped):
                return True
        return False

    if not has_secret_output(tl_text) and not has_secret_output(ct_text):
        scores["hardened_tests_no_secrets_output"] = 1.0

    return scores


def env_example_check(hardened_project: Path) -> float:
    env_path = hardened_project / ".env.example"
    text = read_text_safe(env_path)
    if text is None:
        return 0.0
    env: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        env[key] = val
    needed = {"REMOTE_WEBDRIVER_URL", "TEST_USERNAME", "TEST_PASSWORD", "API_TOKEN"}
    if not needed.issubset(env.keys()):
        return 0.0
    if not env["REMOTE_WEBDRIVER_URL"].lower().startswith("https://"):
        return 0.0
    return 1.0


def status_update_check(path: Path) -> float:
    text = read_text_safe(path)
    if text is None:
        return 0.0
    # Must mention environment variable usage
    has_env_vars = all(var in text for var in ["TEST_USERNAME", "TEST_PASSWORD", "API_TOKEN", "REMOTE_WEBDRIVER_URL"])
    # Mention risks/severity overview
    has_severity_words = any(w in text.lower() for w in ["high", "medium", "low"])
    # Mention high-impact issues like acceptInsecureCerts / ignore-certificate-errors / HTTP remote
    mentions_issues = any(tok in text for tok in ["acceptInsecureCerts", "ignore-certificate-errors", "HTTP", "remoteWebDriverUrl", "certificate"])
    if has_env_vars and has_severity_words and mentions_issues:
        return 1.0
    return 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    input_project = workspace / "input" / "selenium_project"
    hardened_project = workspace / "output" / "hardened" / "selenium_project"

    scores = {
        "security_report_present": 0.0,
        "security_report_structure_valid": 0.0,
        "security_report_minimum_findings_present": 0.0,
        "hardened_directory_exists": 0.0,
        "hardened_mirror_integrity": 0.0,
        "hardened_config_no_insecure_certs": 0.0,
        "hardened_config_no_ignore_cert_errors": 0.0,
        "hardened_config_no_plaintext_secrets_or_emails": 0.0,
        "hardened_config_remote_url_placeholder": 0.0,
        "hardened_config_logging_not_debug": 0.0,
        "hardened_tests_use_env_vars": 0.0,
        "hardened_tests_no_insecure_settings": 0.0,
        "hardened_tests_no_secrets_output": 0.0,
        "env_example_present_and_secure": 0.0,
        "inventory_input_csv_correct": 0.0,
        "inventory_hardened_csv_correct": 0.0,
        "status_update_mentions_risks_and_env": 0.0,
    }

    # Security report checks
    report_path = workspace / "output" / "security_report.json"
    sr_present, sr_structure, sr_minimum = check_security_report(report_path, input_project)
    scores["security_report_present"] = sr_present
    scores["security_report_structure_valid"] = sr_structure
    scores["security_report_minimum_findings_present"] = sr_minimum

    # Hardened directory exists
    if hardened_project.exists() and hardened_project.is_dir():
        scores["hardened_directory_exists"] = 1.0

    # Hardened mirror integrity
    scores["hardened_mirror_integrity"] = hardened_mirror_check(input_project, hardened_project)

    # Hardened config checks
    cfg_scores = hardened_config_checks(hardened_project)
    for k in [
        "hardened_config_no_insecure_certs",
        "hardened_config_no_ignore_cert_errors",
        "hardened_config_no_plaintext_secrets_or_emails",
        "hardened_config_remote_url_placeholder",
        "hardened_config_logging_not_debug",
    ]:
        scores[k] = cfg_scores.get(k, 0.0)

    # Hardened tests checks
    test_scores = hardened_tests_checks(hardened_project)
    for k in [
        "hardened_tests_use_env_vars",
        "hardened_tests_no_insecure_settings",
        "hardened_tests_no_secrets_output",
    ]:
        scores[k] = test_scores.get(k, 0.0)

    # .env.example check
    scores["env_example_present_and_secure"] = env_example_check(hardened_project)

    # Inventories
    inv_input = workspace / "output" / "file_inventory_input.csv"
    inv_hardened = workspace / "output" / "file_inventory_hardened.csv"
    scores["inventory_input_csv_correct"] = 1.0 if inventory_matches(input_project, inv_input) else 0.0
    scores["inventory_hardened_csv_correct"] = 1.0 if inventory_matches(hardened_project, inv_hardened) else 0.0

    # Status update
    status_md = workspace / "output" / "status_update.md"
    scores["status_update_mentions_risks_and_env"] = status_update_check(status_md)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()