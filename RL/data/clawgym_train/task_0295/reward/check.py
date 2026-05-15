import csv
import json
import re
import sys
import ast
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def compute_login_stats(rows: List[Dict[str, str]]) -> Tuple[int, int, int, float, Optional[str], Dict[str, int], Dict[str, int]]:
    total = 0
    successes = 0
    failures = 0
    dates = []
    # Parse total stats
    for r in rows:
        total += 1
        s = r.get("success", "").strip()
        if s.lower() == "true":
            successes += 1
        elif s.lower() == "false":
            failures += 1
        else:
            # treat unknown as failure to be strict? We'll count as neither
            pass
        ts = r.get("timestamp", "").strip()
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", ts)
        if m:
            dates.append(m.group(1))
    failure_rate_percent = round((failures / total) * 100.0, 2) if total > 0 else 0.0
    latest_date = max(dates) if dates else None

    failed_by_ip_latest: Dict[str, int] = {}
    failed_by_user_latest: Dict[str, int] = {}
    if latest_date:
        for r in rows:
            ts = r.get("timestamp", "").strip()
            m = re.match(r"^(\d{4}-\d{2}-\d{2})", ts)
            if not m or m.group(1) != latest_date:
                continue
            s = r.get("success", "").strip().lower()
            if s == "false":
                ip = r.get("ip", "").strip()
                user = r.get("user", "").strip()
                if ip:
                    failed_by_ip_latest[ip] = failed_by_ip_latest.get(ip, 0) + 1
                if user:
                    failed_by_user_latest[user] = failed_by_user_latest.get(user, 0) + 1
    return total, successes, failures, failure_rate_percent, latest_date, failed_by_ip_latest, failed_by_user_latest


def parse_markdown_items(markdown: str) -> List[str]:
    # Split by "Action:" headings, keeping the first empty part if any out
    parts = re.split(r"(?im)^\s*Action\s*:\s*", markdown)
    # First part before the first "Action:" is not an item
    return [p.strip() for p in parts[1:]]


def has_all_fields(block: str) -> bool:
    required = ["Rationale", "Priority", "Owner", "Next Step"]
    return all(re.search(rf"(?im)^\s*{field}\s*:\s*", block) for field in required)


def check_non_increasing_by_count(rows: List[Dict[str, str]], key_field: str, count_field: str) -> bool:
    prev = None
    for r in rows:
        try:
            c = int(r[count_field])
        except Exception:
            return False
        if prev is not None and c > prev:
            return False
        prev = c
    return True


def read_auth_and_config(input_dir: Path) -> Tuple[Optional[str], Optional[str]]:
    auth_path = input_dir / "app" / "auth.py"
    cfg_path = input_dir / "app" / "config.yaml"
    return safe_read_text(auth_path), safe_read_text(cfg_path)


def verify_refactor_password_compare_constant_time(code: str) -> float:
    # Check that verify_login uses compare_digest
    # Heuristic: presence of "compare_digest(" in file and import or qualification with hmac
    has_compare = "compare_digest(" in code
    has_hmac = re.search(r"\bimport\s+hmac\b", code) or re.search(r"\bfrom\s+hmac\s+import\s+compare_digest\b", code)
    # Stronger: ensure that in verify_login function, compare_digest is used
    try:
        tree = ast.parse(code)
        ok_in_func = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "verify_login":
                # look for Call to compare_digest in this function
                for n in ast.walk(node):
                    if isinstance(n, ast.Call):
                        # func can be Name(compare_digest) or Attribute(hmac, compare_digest)
                        if isinstance(n.func, ast.Name) and n.func.id == "compare_digest":
                            ok_in_func = True
                        if isinstance(n.func, ast.Attribute) and n.func.attr == "compare_digest":
                            ok_in_func = True
        return 1.0 if ok_in_func and has_compare and has_hmac else 0.0
    except Exception:
        return 1.0 if has_compare and has_hmac else 0.0


def verify_refactor_reset_token_secure(code: str) -> float:
    # Must use secrets.token_urlsafe(32)
    return 1.0 if re.search(r"secrets\.token_urlsafe\(\s*32\s*\)", code) else 0.0


def verify_refactor_sql_parameterized(code: str) -> float:
    # Must change raw SQL to parameterized form with ?
    # Look for a call execute("... ? ...", (username,)) inside get_user_role
    try:
        tree = ast.parse(code)
        ok = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_user_role":
                for n in ast.walk(node):
                    if isinstance(n, ast.Call):
                        # function attribute name 'execute'
                        if isinstance(n.func, ast.Attribute) and n.func.attr == "execute":
                            # args length 2
                            if len(n.args) >= 1:
                                first_arg = n.args[0]
                                sql_text = None
                                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                                    sql_text = first_arg.value
                                # Do not allow f-strings
                                if isinstance(first_arg, ast.JoinedStr):
                                    return 0.0
                                if sql_text and "?" in sql_text and "username" in sql_text.lower():
                                    # check parameters supplied
                                    if len(n.args) >= 2:
                                        ok = True
        if not ok:
            # Fallback regex on code
            if re.search(r"execute\(\s*[\"'].*\?.*[\"']\s*,\s*\(", code, re.DOTALL):
                ok = True
        # Ensure the original insecure pattern is not still present
        insecure = re.search(r"execute\(\s*f?[\"']\s*SELECT\s+role\s+FROM\s+users\s+WHERE\s+username\s*=\s*['\{]", code, re.IGNORECASE)
        return 1.0 if ok and not insecure else 0.0
    except Exception:
        # Fallback to regex only
        ok = re.search(r"execute\(\s*[\"'].*\?.*[\"']\s*,\s*\(", code, re.DOTALL)
        insecure = re.search(r"execute\(\s*f?[\"']\s*SELECT\s+role\s+FROM\s+users\s+WHERE\s+username\s*=\s*['\{]", code, re.IGNORECASE)
        return 1.0 if ok and not insecure else 0.0


def verify_refactor_functions_present(code: str) -> float:
    required = {"verify_login", "get_user_role", "generate_reset_token"}
    try:
        tree = ast.parse(code)
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        missing = required - names
        return 1.0 if not missing else 0.0
    except Exception:
        # Fallback to regex presence of def signatures
        present = 0
        for fn in required:
            if re.search(rf"def\s+{re.escape(fn)}\s*\(", code):
                present += 1
        return 1.0 if present == len(required) else present / len(required)


def check_security_review_topics(report: str) -> float:
    # Mandatory topics:
    # predictable token generation
    tok = bool(re.search(r"(predictable|random\.random|token_urlsafe|reset[-\s]*token)", report, re.IGNORECASE))
    # non-constant-time password comparison
    const = bool(re.search(r"(constant[-\s]*time|compare_digest|timing\s+attack)", report, re.IGNORECASE))
    # unsafe SQL query construction
    sql = bool(re.search(r"(sql).*(injection|parameteriz|prepared)|injection", report, re.IGNORECASE | re.DOTALL))
    # weak/overly permissive config (debug, cookies, IP whitelist)
    weak_cfg = bool(re.search(r"(debug\s*:\s*true|cookie_secure\s*:\s*false|cookie_httponly\s*:\s*false|allowed_ips\s*:\s*[\*]|whitelist)", report, re.IGNORECASE))
    # password hashing choices
    hash_ch = bool(re.search(r"\bmd5\b|\bhash\b.*(weak|md5)|password\s+hash", report, re.IGNORECASE))
    covered = [tok, const, sql, weak_cfg, hash_ch]
    return sum(1.0 for c in covered if c) / len(covered)


def check_security_review_issues_count(report: str) -> float:
    # Count distinct issues via a set of canonical issue keys detected by keywords.
    issue_map = {
        "predictable_token": r"(random\.random|predictable token|token_urlsafe|reset[-\s]*token)",
        "non_constant_time": r"(compare_digest|constant[-\s]*time|timing\s+attack)",
        "sql_injection": r"(sql).*(injection|string\s+interpolation|concatenation)|parameteriz|prepared",
        "debug_mode": r"debug\s*:\s*true|debug\s+mode",
        "cookie_flags": r"cookie_secure\s*:\s*false|cookie_httponly\s*:\s*false|httponly|secure\s+cookie",
        "ip_whitelist": r"allowed_ips\s*:\s*\*|whitelist|allow\s+all\s+ips",
        "weak_hash": r"\bmd5\b|weak\s+hash|password\s+hashing",
        "secret_key": r"secret_key.*changeme|weak\s+secret\s+key",
        "password_policy": r"min_length\s*:\s*6|require_numbers\s*:\s*false|weak\s+password\s+policy",
    }
    found = set()
    for key, pattern in issue_map.items():
        if re.search(pattern, report, re.IGNORECASE | re.DOTALL):
            found.add(key)
    # At least 5 distinct issues
    count = len(found)
    return min(1.0, count / 5.0)


def check_security_review_evidence(report: str, auth_code: Optional[str], cfg_code: Optional[str]) -> float:
    # Expect references to files and line numbers or snippets.
    refs_files = bool(re.search(r"auth\.py", report)) and bool(re.search(r"config\.yaml", report))
    # Snippet presence: look for known snippets from source files
    snippets = [
        "hashlib.md5(",
        "cur.execute(f\"SELECT role FROM users WHERE username",
        "random.random()",
        "if whitelist == \"*\"",
        "debug: true",
        "cookie_secure: false",
        "cookie_httponly: false",
        "allowed_ips: \"*\"",
        "secret_key: \"changeme\"",
    ]
    snippet_hits = sum(1 for s in snippets if s in report)
    has_line_number = bool(re.search(r"\bline\s+\d+\b", report, re.IGNORECASE)) or bool(re.search(r"\bL\d+\b", report))
    # Require both file references and either >=2 snippets or line numbers
    if refs_files and (snippet_hits >= 2 or has_line_number):
        return 1.0
    return 0.0


def check_security_review_cross_ref(report: str, totals: Tuple[int, int, int, float, Optional[str], Dict[str, int], Dict[str, int]]) -> float:
    total, successes, failures, fail_rate, latest_date, failed_by_ip, failed_by_user = totals
    tokens = set()
    if latest_date:
        tokens.add(latest_date)
    # common IPs or users to look for
    for ip in failed_by_ip.keys():
        tokens.add(ip)
    for user in failed_by_user.keys():
        tokens.add(user)
    # counts that might be cited
    tokens.add(str(total))
    tokens.add(str(successes))
    tokens.add(str(failures))
    # failure rate could be shown as 75.00 or 75.0 or 75%
    tokens.add(f"{fail_rate:.2f}")
    tokens.add(f"{int(fail_rate)}")
    # Check presence alongside context words
    context = bool(re.search(r"(login|attempt|failure|failed|success)", report, re.IGNORECASE))
    present_token = any(tok in report for tok in tokens)
    return 1.0 if present_token and context else 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    input_dir = workspace / "input"
    output_dir = workspace / "output"

    # Prepare scores dict with defaults
    scores = {
        "failure_overall_exists": 0.0,
        "failure_overall_values_correct": 0.0,
        "failed_by_ip_latest_exists": 0.0,
        "failed_by_ip_latest_content_correct": 0.0,
        "failed_by_user_latest_exists": 0.0,
        "failed_by_user_latest_content_correct": 0.0,
        "refactored_module_exists": 0.0,
        "refactor_password_compare_constant_time": 0.0,
        "refactor_reset_token_secure": 0.0,
        "refactor_sql_parameterized": 0.0,
        "refactor_core_functions_present": 0.0,
        "security_review_exists": 0.0,
        "security_review_mandatory_topics_covered": 0.0,
        "security_review_issue_count_at_least_five": 0.0,
        "security_review_evidence_citations": 0.0,
        "security_review_cross_reference_stats": 0.0,
        "action_items_exists": 0.0,
        "action_items_min_count": 0.0,
        "action_items_fields_coverage": 0.0,
    }

    # Load inputs
    login_csv_path = input_dir / "logs" / "login_attempts.csv"
    login_rows = safe_parse_csv(login_csv_path)
    # Compute expected stats if possible
    expected_stats = None
    if login_rows is not None:
        try:
            expected_stats = compute_login_stats(login_rows)
        except Exception:
            expected_stats = None

    # 3) Check login failure statistics outputs
    failure_overall_path = output_dir / "failure_overall.json"
    failed_ip_path = output_dir / "failed_by_ip_latest.csv"
    failed_user_path = output_dir / "failed_by_user_latest.csv"

    # failure_overall.json
    fo = safe_load_json(failure_overall_path)
    if fo is not None:
        scores["failure_overall_exists"] = 1.0
        if expected_stats is not None:
            total, successes, failures, fail_rate, latest_date, failed_by_ip, failed_by_user = expected_stats
            # strict key presence and numeric comparison
            keys_ok = all(k in fo for k in ["total_attempts", "total_successes", "total_failures", "failure_rate_percent"])
            types_ok = isinstance(fo.get("total_attempts"), int) and isinstance(fo.get("total_successes"), int) and isinstance(fo.get("total_failures"), int) and isinstance(fo.get("failure_rate_percent"), (int, float))
            values_ok = keys_ok and types_ok and fo["total_attempts"] == total and fo["total_successes"] == successes and fo["total_failures"] == failures and abs(float(fo["failure_rate_percent"]) - float(fail_rate)) < 1e-6
            scores["failure_overall_values_correct"] = 1.0 if values_ok else 0.0
    else:
        scores["failure_overall_exists"] = 0.0
        scores["failure_overall_values_correct"] = 0.0

    # failed_by_ip_latest.csv
    fip_rows = safe_parse_csv(failed_ip_path)
    if fip_rows is not None:
        scores["failed_by_ip_latest_exists"] = 1.0
        if expected_stats is not None:
            _, _, _, _, latest_date, failed_by_ip, _ = expected_stats
            # Check header
            header_ok = False
            try:
                with failed_ip_path.open("r", encoding="utf-8") as f:
                    header_line = f.readline().strip()
                header_ok = header_line == "ip,failed_count"
            except Exception:
                header_ok = False
            # Count match
            counts_ok = True
            seen = {}
            for r in fip_rows:
                if "ip" not in r or "failed_count" not in r:
                    counts_ok = False
                    break
                ip = r["ip"].strip()
                try:
                    c = int(r["failed_count"])
                except Exception:
                    counts_ok = False
                    break
                seen[ip] = c
            counts_ok = counts_ok and seen == failed_by_ip
            sort_ok = check_non_increasing_by_count(fip_rows, "ip", "failed_count")
            scores["failed_by_ip_latest_content_correct"] = 1.0 if (header_ok and counts_ok and sort_ok) else 0.0
    else:
        scores["failed_by_ip_latest_exists"] = 0.0
        scores["failed_by_ip_latest_content_correct"] = 0.0

    # failed_by_user_latest.csv
    fu_rows = safe_parse_csv(failed_user_path)
    if fu_rows is not None:
        scores["failed_by_user_latest_exists"] = 1.0
        if expected_stats is not None:
            _, _, _, _, latest_date, _, failed_by_user = expected_stats
            header_ok = False
            try:
                with failed_user_path.open("r", encoding="utf-8") as f:
                    header_line = f.readline().strip()
                header_ok = header_line == "user,failed_count"
            except Exception:
                header_ok = False
            counts_ok = True
            seen = {}
            for r in fu_rows:
                if "user" not in r or "failed_count" not in r:
                    counts_ok = False
                    break
                user = r["user"].strip()
                try:
                    c = int(r["failed_count"])
                except Exception:
                    counts_ok = False
                    break
                seen[user] = c
            counts_ok = counts_ok and seen == failed_by_user
            sort_ok = check_non_increasing_by_count(fu_rows, "user", "failed_count")
            scores["failed_by_user_latest_content_correct"] = 1.0 if (header_ok and counts_ok and sort_ok) else 0.0
    else:
        scores["failed_by_user_latest_exists"] = 0.0
        scores["failed_by_user_latest_content_correct"] = 0.0

    # 2) Refactored authentication module checks
    refactored_path = output_dir / "auth_refactored.py"
    ref_code = safe_read_text(refactored_path)
    if ref_code is not None:
        scores["refactored_module_exists"] = 1.0
        scores["refactor_password_compare_constant_time"] = verify_refactor_password_compare_constant_time(ref_code)
        scores["refactor_reset_token_secure"] = verify_refactor_reset_token_secure(ref_code)
        scores["refactor_sql_parameterized"] = verify_refactor_sql_parameterized(ref_code)
        scores["refactor_core_functions_present"] = verify_refactor_functions_present(ref_code)
    else:
        scores["refactored_module_exists"] = 0.0
        scores["refactor_password_compare_constant_time"] = 0.0
        scores["refactor_reset_token_secure"] = 0.0
        scores["refactor_sql_parameterized"] = 0.0
        scores["refactor_core_functions_present"] = 0.0

    # 1) Security review report checks
    review_path = output_dir / "security_review.md"
    review_text = safe_read_text(review_path)
    auth_code, cfg_code = read_auth_and_config(input_dir)
    if review_text is not None:
        scores["security_review_exists"] = 1.0
        scores["security_review_mandatory_topics_covered"] = check_security_review_topics(review_text)
        scores["security_review_issue_count_at_least_five"] = check_security_review_issues_count(review_text)
        scores["security_review_evidence_citations"] = check_security_review_evidence(review_text, auth_code, cfg_code)
        if expected_stats is not None:
            scores["security_review_cross_reference_stats"] = check_security_review_cross_ref(review_text, expected_stats)
        else:
            scores["security_review_cross_reference_stats"] = 0.0
    else:
        scores["security_review_exists"] = 0.0
        scores["security_review_mandatory_topics_covered"] = 0.0
        scores["security_review_issue_count_at_least_five"] = 0.0
        scores["security_review_evidence_citations"] = 0.0
        scores["security_review_cross_reference_stats"] = 0.0

    # 4) Action plan notes checks
    actions_path = output_dir / "security_action_items.md"
    actions_text = safe_read_text(actions_path)
    if actions_text is not None:
        scores["action_items_exists"] = 1.0
        items = parse_markdown_items(actions_text)
        count = len(items)
        scores["action_items_min_count"] = 1.0 if count >= 5 else (count / 5.0)
        if count > 0:
            fields_ok_count = sum(1 for it in items if has_all_fields(it))
            # coverage proportional to at least 5 items
            denom = min(5, count)
            scores["action_items_fields_coverage"] = min(1.0, fields_ok_count / max(1, denom))
        else:
            scores["action_items_fields_coverage"] = 0.0
    else:
        scores["action_items_exists"] = 0.0
        scores["action_items_min_count"] = 0.0
        scores["action_items_fields_coverage"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()