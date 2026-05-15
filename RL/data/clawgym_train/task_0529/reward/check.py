import json
import os
import sys
import csv
import re

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_required_endpoint(endpoints, required):
    # Find an endpoint object that has at least all key-value pairs in 'required'
    for ep in endpoints:
        if not isinstance(ep, dict):
            continue
        ok = True
        for k, v in required.items():
            if k not in ep:
                ok = False
                break
            # For list values like required_permissions, compare as sets
            if isinstance(v, list):
                if not isinstance(ep.get(k), list):
                    ok = False
                    break
                if set(ep.get(k)) != set(v):
                    ok = False
                    break
            else:
                if ep.get(k) != v:
                    ok = False
                    break
        if ok:
            return True
    return False

def near(text, a, b, window=150):
    # Case-insensitive proximity: any occurrence of a is within window chars of any occurrence of b
    t = text.lower()
    a_l = a.lower()
    b_l = b.lower()
    idx = 0
    found = False
    while True:
        i = t.find(a_l, idx)
        if i == -1:
            break
        start = max(0, i - window)
        end = min(len(t), i + len(a_l) + window)
        if b_l in t[start:end]:
            found = True
            break
        idx = i + 1
    return found

def check_security_design(text):
    checks = {
        "design_access_token_lifetime": False,
        "design_refresh_token_lifetime": False,
        "design_password_policy": False,
        "design_cookie_flags": False,
        "design_rate_limits": False,
        "design_ownership": False,
        "design_storage_logging": False,
    }
    if text is None:
        return checks

    low = text.lower()

    # Access token near 15 minutes or 15m
    access_near_15m = near(text, "access token", "15m") or near(text, "access token", "15 minutes")
    checks["design_access_token_lifetime"] = access_near_15m

    # Refresh token near 7 days or 7d
    refresh_near_7d = near(text, "refresh token", "7d") or near(text, "refresh token", "7 days")
    checks["design_refresh_token_lifetime"] = refresh_near_7d

    # Password policy: presence of password, 12+ rounds (cost factor), and complexity requirements
    has_password_word = "password" in low
    # Hashing cost patterns
    cost_patterns = [
        r"\b12\s*rounds\b",
        r"\bcost\s*factor\s*12\b",
        r"\b12\+\b",
        r"\b12\s*or\s*more\b",
        r"\b>=\s*12\b",
    ]
    has_cost = any(re.search(p, low) for p in cost_patterns)
    # Complexity
    has_upper = "uppercase" in low
    has_lower = "lowercase" in low
    has_number = "number" in low
    has_special = "special character" in low or "special characters" in low
    has_min_12 = "12" in low and ("minimum" in low or "at least" in low)
    checks["design_password_policy"] = (has_password_word and has_cost and has_upper and has_lower and has_number and has_special and has_min_12)

    # Cookie flags
    has_httponly = "httponly" in low
    has_secure = "secure" in low
    has_samesite = "samesite" in low
    checks["design_cookie_flags"] = has_httponly and has_secure and has_samesite

    # Rate limits: must mention rate limit(ing), login with 5 and 15, and api with 100 and 1
    has_rate_word = ("rate limit" in low) or ("rate limiting" in low)
    login_ok = False
    api_ok = False
    # Check windows around "login"
    for m in re.finditer(r"login", low):
        start = max(0, m.start() - 120)
        end = min(len(low), m.end() + 120)
        win = low[start:end]
        if "5" in win and "15" in win:
            login_ok = True
            break
    # API context checks: look around "api" or phrases with "per minute"
    for m in re.finditer(r"api", low):
        start = max(0, m.start() - 120)
        end = min(len(low), m.end() + 120)
        win = low[start:end]
        if "100" in win and (" 1 " in win or " 1m" in win or "per minute" in win or "1 minute" in win or "one minute" in win):
            api_ok = True
            break
    # Additional heuristic: exact phrase "100 requests per minute"
    if not api_ok and "100 requests per minute" in low:
        api_ok = True
    # Fallback: any line containing both 100 and per minute
    if not api_ok:
        for line in low.splitlines():
            if "100" in line and "per minute" in line:
                api_ok = True
                break
    checks["design_rate_limits"] = has_rate_word and login_ok and api_ok

    # Ownership enforcement: users can modify only their own posts unless elevated role overrides
    ownership_ok = ("own posts" in low or "only their own posts" in low or "own post" in low) and ("unless" in low or "override" in low or "admin" in low or "elevated" in low)
    checks["design_ownership"] = ownership_ok

    # Storage and logging: advise against localStorage and recommend httpOnly cookies; mention logging security events
    mentions_localstorage = "localstorage" in low
    mentions_httponly_cookie = "httponly" in low or "cookie" in low
    mentions_logging = ("log" in low or "logging" in low) and ("security event" in low or "security events" in low or "security" in low)
    checks["design_storage_logging"] = mentions_localstorage and mentions_httponly_cookie and mentions_logging

    return checks

def parse_csv(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = list(csv.reader(f))
        return reader
    except Exception:
        return None

def check_test_plan(rows):
    checks = {
        "test_headers_ok": False,
        "test_min_rows": False,
        "test_keywords_coverage": False,
    }
    if rows is None or len(rows) == 0:
        return checks
    header = rows[0]
    expected_header = ["case_id", "title", "endpoint", "method", "preconditions", "steps", "expected_result"]
    checks["test_headers_ok"] = header == expected_header

    data_rows = rows[1:]
    non_empty = [r for r in data_rows if any(cell.strip() for cell in r)]
    checks["test_min_rows"] = len(non_empty) >= 12

    # Collect coverage across title and expected_result columns
    required_substrings = [
        "invalid password",
        "rate limit",
        "expired access token",
        "token refresh",
        "reuse",
        "rbac allow",
        "rbac deny",
        "permission allow",
        "permission deny",
        "ownership allow",
        "ownership deny",
        "admin delete allowed",
        "moderator delete denied",
    ]
    found = {k: False for k in required_substrings}
    # Identify indices for title and expected_result
    try:
        title_idx = header.index("title")
        result_idx = header.index("expected_result")
    except ValueError:
        title_idx = 1
        result_idx = 6 if len(header) > 6 else -1
    for r in non_empty:
        title = (r[title_idx] if title_idx < len(r) else "").lower()
        result = (r[result_idx] if result_idx >= 0 and result_idx < len(r) else "").lower()
        combined = title + " " + result
        for key in required_substrings:
            if key in combined:
                found[key] = True
    checks["test_keywords_coverage"] = all(found.values())

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}
    total_points = 0
    points_earned = 0

    # 1) api_spec.json checks
    api_spec_path = os.path.join(output_dir, "api_spec.json")
    checks["api_spec_exists"] = os.path.isfile(api_spec_path)
    total_points += 1
    if checks["api_spec_exists"]:
        api_spec = load_json(api_spec_path)
        checks["api_spec_valid_json"] = api_spec is not None and isinstance(api_spec, dict)
        total_points += 1
        if checks["api_spec_valid_json"]:
            # Top-level keys
            tl_ok = all(k in api_spec for k in ["tokens", "rate_limits", "endpoints"])
            checks["api_spec_top_keys"] = tl_ok
            total_points += 1

            # Tokens TTL
            tokens = api_spec.get("tokens", {})
            checks["api_spec_tokens_ttl"] = isinstance(tokens, dict) and tokens.get("access_ttl") == "15m" and tokens.get("refresh_ttl") == "7d"
            total_points += 1

            # Rate limits
            rl = api_spec.get("rate_limits", {})
            login_ok = isinstance(rl, dict) and isinstance(rl.get("login"), dict) and rl["login"].get("max") == 5 and rl["login"].get("window") == "15m"
            api_ok = isinstance(rl, dict) and isinstance(rl.get("api"), dict) and rl["api"].get("max") == 100 and rl["api"].get("window") == "1m"
            checks["api_spec_rate_limits"] = login_ok and api_ok
            total_points += 1

            # Endpoints inclusion
            endpoints = api_spec.get("endpoints")
            required_eps = [
                {"path": "/api/auth/register", "method": "POST", "auth": False},
                {"path": "/api/auth/login", "method": "POST", "auth": False},
                {"path": "/api/auth/refresh", "method": "POST", "auth": False},
                {"path": "/api/users", "method": "GET", "auth": True, "required_permissions": ["read:users"]},
                {"path": "/api/users/{id}", "method": "DELETE", "auth": True, "required_permissions": ["delete:users"]},
                {"path": "/api/posts", "method": "POST", "auth": True, "required_permissions": ["write:posts"]},
                {"path": "/api/posts/{id}", "method": "PUT", "auth": True, "required_permissions": ["write:posts"], "ownership": "owner_only"},
            ]
            eps_ok = isinstance(endpoints, list) and all(find_required_endpoint(endpoints, req) for req in required_eps)
            checks["api_spec_required_endpoints_present"] = eps_ok
            total_points += 1
        else:
            # Ensure keys exist; add placeholders to keep consistent structure
            checks["api_spec_top_keys"] = False
            checks["api_spec_tokens_ttl"] = False
            checks["api_spec_rate_limits"] = False
            checks["api_spec_required_endpoints_present"] = False
            total_points += 4
    else:
        # Missing file -> add expected check keys as False and count points
        checks["api_spec_valid_json"] = False
        checks["api_spec_top_keys"] = False
        checks["api_spec_tokens_ttl"] = False
        checks["api_spec_rate_limits"] = False
        checks["api_spec_required_endpoints_present"] = False
        total_points += 5

    # 2) rbac.json checks
    rbac_path = os.path.join(output_dir, "rbac.json")
    checks["rbac_exists"] = os.path.isfile(rbac_path)
    total_points += 1
    if checks["rbac_exists"]:
        rbac = load_json(rbac_path)
        checks["rbac_valid_json"] = rbac is not None and isinstance(rbac, dict)
        total_points += 1
        if checks["rbac_valid_json"]:
            roles = rbac.get("roles", {})
            roles_ok = False
            if isinstance(roles, dict):
                user_perms = set(roles.get("user", []) if isinstance(roles.get("user"), list) else [])
                mod_perms = set(roles.get("moderator", []) if isinstance(roles.get("moderator"), list) else [])
                admin_perms = set(roles.get("admin", []) if isinstance(roles.get("admin"), list) else [])
                user_req = {"read:posts", "write:posts"}
                mod_req = user_req | {"read:users"}
                admin_req = mod_req | {"write:users", "delete:users"}
                roles_ok = user_req.issubset(user_perms) and mod_req.issubset(mod_perms) and admin_req.issubset(admin_perms)
            checks["rbac_roles_baseline"] = roles_ok
            total_points += 1

            hierarchy = rbac.get("hierarchy", {})
            h_ok = False
            if isinstance(hierarchy, dict):
                h_ok = (
                    hierarchy.get("admin") == ["admin", "moderator", "user"] and
                    hierarchy.get("moderator") == ["moderator", "user"] and
                    hierarchy.get("user") == ["user"]
                )
            checks["rbac_hierarchy_baseline"] = h_ok
            total_points += 1
        else:
            checks["rbac_roles_baseline"] = False
            checks["rbac_hierarchy_baseline"] = False
            total_points += 2
    else:
        checks["rbac_valid_json"] = False
        checks["rbac_roles_baseline"] = False
        checks["rbac_hierarchy_baseline"] = False
        total_points += 3

    # 3) security_design.md checks
    design_path = os.path.join(output_dir, "security_design.md")
    checks["security_design_exists"] = os.path.isfile(design_path)
    total_points += 1
    if checks["security_design_exists"]:
        text = load_text(design_path)
        sd_checks = check_security_design(text)
        checks.update(sd_checks)
        total_points += len(sd_checks)
    else:
        sd_checks = {
            "design_access_token_lifetime": False,
            "design_refresh_token_lifetime": False,
            "design_password_policy": False,
            "design_cookie_flags": False,
            "design_rate_limits": False,
            "design_ownership": False,
            "design_storage_logging": False,
        }
        checks.update(sd_checks)
        total_points += len(sd_checks)

    # 4) test_plan.csv checks
    test_path = os.path.join(output_dir, "test_plan.csv")
    checks["test_plan_exists"] = os.path.isfile(test_path)
    total_points += 1
    if checks["test_plan_exists"]:
        rows = parse_csv(test_path)
        tp_checks = check_test_plan(rows)
        checks.update(tp_checks)
        total_points += len(tp_checks)
    else:
        tp_checks = {
            "test_headers_ok": False,
            "test_min_rows": False,
            "test_keywords_coverage": False,
        }
        checks.update(tp_checks)
        total_points += len(tp_checks)

    # Accumulate points
    for key, val in checks.items():
        if isinstance(val, bool) and val:
            points_earned += 1

    # No-op baseline: if output/ missing or empty, reward must be 0.0
    output_exists = os.path.isdir(output_dir)
    output_has_files = False
    if output_exists:
        try:
            output_has_files = any(os.path.isfile(os.path.join(output_dir, p)) for p in os.listdir(output_dir))
        except Exception:
            output_has_files = False
    if not output_has_files:
        reward = 0.0
    else:
        reward = points_earned / total_points if total_points > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    # Append boolean checks
    for k, v in checks.items():
        result[k] = bool(v)

    # Print exactly one JSON object as the last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()