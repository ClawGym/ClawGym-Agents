import json
import os
import sys
import csv
import re
import math

def read_text(path):
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

def parse_csv_with_header(path, expected_header=None):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_rows = rows[1:]
        if expected_header is not None and header != expected_header:
            return header, data_rows
        return header, data_rows
    except Exception:
        return None, None

def is_all_digits(s):
    return bool(re.fullmatch(r"\d+", s))

def has_lower(s):
    return any('a' <= c <= 'z' for c in s)

def has_upper(s):
    return any('A' <= c <= 'Z' for c in s)

def has_digit(s):
    return any('0' <= c <= '9' for c in s)

def has_symbol(s):
    return any(not c.isalnum() for c in s)

def compute_entropy_pool(has_l, has_u, has_d, has_s):
    pool = 0
    if has_l:
        pool += 26
    if has_u:
        pool += 26
    if has_d:
        pool += 10
    if has_s:
        pool += 32
    return max(pool, 1)

def round2(x):
    # Return to two decimals as float by formatting, to control representation
    return float(f"{x:.2f}")

def strength_score(pw):
    score = 0
    length = len(pw)
    # Length points
    if length >= 16:
        score += 30
    elif length >= 12:
        score += 20
    elif length >= 8:
        score += 10
    else:
        score += 0

    # Char class points
    if has_lower(pw):
        score += 10
    if has_upper(pw):
        score += 15
    if has_digit(pw):
        score += 10
    if has_symbol(pw):
        score += 20

    # Bonus
    if length >= 20:
        score += 10

    # Unique-character ratio
    unique_chars = len(set(pw))
    if length > 0:
        ratio = (unique_chars * 100) // length
        if ratio < 40:
            score -= 15
        elif ratio >= 80:
            score += 5

    # Common pattern penalties
    pw_lower = pw.lower()
    patterns = ["password", "123456", "qwerty", "abc123", "admin", "letmein", "welcome", "monkey"]
    for pat in patterns:
        if pat in pw_lower:
            score -= 20

    # Repetition penalty: 3+ same char in a row
    if re.search(r"(.)\1{2,}", pw):
        score -= 10

    # Clamp
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return int(score)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "policies_applied_json_ok": False,
        "credentials_csv_header_ok": False,
        "credentials_row_count_ok": False,
        "passwords_unique": False,
        "accountingportal_policy_ok": False,
        "devwiki_policy_ok": False,
        "metrics_line_count_ok": False,
        "metrics_values_ok": False,
        "passphrase_requirements_ok": False,
        "passphrases_json_ok": False,
        "pin_requirements_ok": False,
        "pins_csv_ok": False,
        "summary_counts_ok": False,
    }

    # Expected constants from task
    expected_policies = {
        "AccountingPortal": {
            "min_length": 20,
            "require_upper": True,
            "require_digits": True,
            "require_symbols": True,
            "forbid_upper": False,
            "forbid_digits": False,
            "forbid_symbols": False
        },
        "DevWiki": {
            "min_length": 16,
            "require_upper": False,
            "require_digits": True,
            "require_symbols": False,
            "forbid_upper": True,
            "forbid_digits": False,
            "forbid_symbols": True
        }
    }
    expected_passphrase_requirements = {"ops": 7, "dev": 5, "marketing": 6}
    expected_pin_requirements = {
        "devices": [
            {"device": "DoorPanel-A", "length": 6},
            {"device": "Locker-12", "length": 4},
            {"device": "Tablet-X5", "length": 8},
        ]
    }
    required_devices = {d["device"]: d["length"] for d in expected_pin_requirements["devices"]}

    # 1) policies_applied.json
    policies_path = os.path.join(output_dir, "policies_applied.json")
    policies_data = load_json(policies_path)
    if isinstance(policies_data, dict):
        # Compare dict equality
        if policies_data == expected_policies:
            checks["policies_applied_json_ok"] = True

    # 2) credentials.csv
    credentials_path = os.path.join(output_dir, "credentials.csv")
    creds_header, creds_rows = parse_csv_with_header(credentials_path, expected_header=["account_id", "service", "username", "password_index", "password"])
    if creds_header is not None:
        if creds_header == ["account_id", "service", "username", "password_index", "password"]:
            checks["credentials_csv_header_ok"] = True

    credentials = []
    if creds_rows is not None:
        # Validate row count
        if len(creds_rows) == 8:
            checks["credentials_row_count_ok"] = True
        # Parse rows
        for r in creds_rows or []:
            if len(r) != 5:
                continue
            account_id, service, username, password_index, password = r
            credentials.append({
                "account_id": account_id,
                "service": service,
                "username": username,
                "password_index": password_index,
                "password": password
            })

        # Uniqueness of passwords
        pw_list = [c["password"] for c in credentials]
        if len(pw_list) == 8 and len(set(pw_list)) == 8:
            checks["passwords_unique"] = True

        # Service-specific policy checks
        # AccountingPortal
        acc_ok = True
        dev_ok = True
        for c in credentials:
            pw = c["password"]
            svc = c["service"]
            if svc == "AccountingPortal":
                if len(pw) < 20:
                    acc_ok = False
                    continue
                if not has_lower(pw):
                    acc_ok = False
                    continue
                if not has_upper(pw):
                    acc_ok = False
                    continue
                if not has_digit(pw):
                    acc_ok = False
                    continue
                if not has_symbol(pw):
                    acc_ok = False
                    continue
                # No explicit forbids needed for this policy
            elif svc == "DevWiki":
                if len(pw) < 16:
                    dev_ok = False
                    continue
                # must include lower and digit
                if not has_lower(pw) or not has_digit(pw):
                    dev_ok = False
                    continue
                # must not include uppercase or symbol
                if has_upper(pw) or has_symbol(pw):
                    dev_ok = False
                    continue
            else:
                # Unknown service should fail checks
                acc_ok = False
                dev_ok = False
        # Only mark true if at least one row exists for each service and all those rows comply
        if any(c["service"] == "AccountingPortal" for c in credentials) and acc_ok:
            checks["accountingportal_policy_ok"] = True
        if any(c["service"] == "DevWiki" for c in credentials) and dev_ok:
            checks["devwiki_policy_ok"] = True

    # 3) metrics.jsonl
    metrics_path = os.path.join(output_dir, "metrics.jsonl")
    metrics_lines = []
    if os.path.isfile(metrics_path):
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_stripped = line.strip()
                    if line_stripped == "":
                        continue
                    metrics_lines.append(line_stripped)
        except Exception:
            metrics_lines = []
    if len(metrics_lines) == 8:
        checks["metrics_line_count_ok"] = True

    metrics_ok = True
    if metrics_lines and credentials:
        # Build password lookup by (account_id, password_index)
        cred_map = {}
        for c in credentials:
            key = (str(c["account_id"]), str(c["password_index"]))
            cred_map[key] = c["password"]

        # Parse and validate each metrics line
        seen_pairs = set()
        for line in metrics_lines:
            try:
                obj = json.loads(line)
            except Exception:
                metrics_ok = False
                break

            # Required fields
            required_fields = ["account_id", "password_index", "length", "has_lower", "has_upper", "has_digit", "has_symbol", "max_entropy_bits", "strength_score"]
            if not all(k in obj for k in required_fields):
                metrics_ok = False
                break

            account_id = str(obj["account_id"])
            password_index = str(obj["password_index"])
            key = (account_id, password_index)
            if key in seen_pairs:
                metrics_ok = False
                break
            seen_pairs.add(key)

            if key not in cred_map:
                metrics_ok = False
                break
            pw = cred_map[key]

            # Recompute
            length = len(pw)
            hl = has_lower(pw)
            hu = has_upper(pw)
            hd = has_digit(pw)
            hs = has_symbol(pw)
            pool = compute_entropy_pool(hl, hu, hd, hs)
            max_entropy_bits = round2(length * (math.log2(pool) if pool > 0 else 0.0))
            score = strength_score(pw)

            # Compare
            # Exact comparisons (booleans, int, two-decimal float)
            if obj["length"] != length:
                metrics_ok = False
                break
            if not isinstance(obj["has_lower"], bool) or obj["has_lower"] != hl:
                metrics_ok = False
                break
            if not isinstance(obj["has_upper"], bool) or obj["has_upper"] != hu:
                metrics_ok = False
                break
            if not isinstance(obj["has_digit"], bool) or obj["has_digit"] != hd:
                metrics_ok = False
                break
            if not isinstance(obj["has_symbol"], bool) or obj["has_symbol"] != hs:
                metrics_ok = False
                break
            # Compare max_entropy_bits by two-dec string to avoid float artifacts
            try:
                reported_meb = float(obj["max_entropy_bits"])
            except Exception:
                metrics_ok = False
                break
            if f"{reported_meb:.2f}" != f"{max_entropy_bits:.2f}":
                metrics_ok = False
                break
            if obj["strength_score"] != score:
                metrics_ok = False
                break

        # Ensure metrics cover all credentials exactly
        if metrics_ok:
            if len(seen_pairs) != len(credentials):
                metrics_ok = False

    if metrics_ok and checks["metrics_line_count_ok"]:
        checks["metrics_values_ok"] = True

    # 4) passphrase_requirements.json
    ppr_path = os.path.join(output_dir, "passphrase_requirements.json")
    ppr_data = load_json(ppr_path)
    if isinstance(ppr_data, dict) and ppr_data == expected_passphrase_requirements:
        checks["passphrase_requirements_ok"] = True

    # 5) passphrases.json
    passphrases_path = os.path.join(output_dir, "passphrases.json")
    passphrases_data = load_json(passphrases_path)
    if isinstance(passphrases_data, dict):
        keys_ok = set(passphrases_data.keys()) == set(expected_passphrase_requirements.keys())
        format_ok = True
        if keys_ok:
            for role, count in expected_passphrase_requirements.items():
                val = passphrases_data.get(role)
                if not isinstance(val, str):
                    format_ok = False
                    break
                # Validate hyphen-separated lowercase words, only letters
                parts = val.split("-")
                if len(parts) != count:
                    format_ok = False
                    break
                for w in parts:
                    if not re.fullmatch(r"[a-z]+", w):
                        format_ok = False
                        break
                if not format_ok:
                    break
        else:
            format_ok = False
        if keys_ok and format_ok:
            checks["passphrases_json_ok"] = True

    # 6) pin_requirements.json
    pinreq_path = os.path.join(output_dir, "pin_requirements.json")
    pinreq_data = load_json(pinreq_path)
    if isinstance(pinreq_data, dict) and "devices" in pinreq_data and isinstance(pinreq_data["devices"], list):
        # Compare as set ignoring order
        def norm_list(lst):
            return sorted(lst, key=lambda x: (x.get("device", ""), x.get("length", 0)))
        if norm_list(pinreq_data["devices"]) == norm_list(expected_pin_requirements["devices"]):
            checks["pin_requirements_ok"] = True

    # 7) pins.csv
    pins_csv_path = os.path.join(output_dir, "pins.csv")
    pins_header, pins_rows = parse_csv_with_header(pins_csv_path, expected_header=["device", "pin"])
    pins_ok = False
    if pins_header is not None and pins_rows is not None and pins_header == ["device", "pin"]:
        # Must contain exactly 3 rows for the required devices
        if len(pins_rows) == 3:
            devices_in_csv = set()
            per_device_ok = True
            for r in pins_rows:
                if len(r) != 2:
                    per_device_ok = False
                    break
                device, pin = r
                devices_in_csv.add(device)
                if device not in required_devices:
                    per_device_ok = False
                    break
                req_len = required_devices[device]
                if not is_all_digits(pin) or len(pin) != req_len:
                    per_device_ok = False
                    break
            if per_device_ok and devices_in_csv == set(required_devices.keys()):
                pins_ok = True
    if pins_ok:
        checks["pins_csv_ok"] = True

    # 8) summary.md
    summary_path = os.path.join(output_dir, "summary.md")
    summary_text = read_text(summary_path)
    if summary_text is not None:
        # Parse integers from lines
        m_total = re.search(r"Total passwords:\s*(\d+)", summary_text)
        m_unique = re.search(r"Unique passwords:\s*(\d+)", summary_text)
        if m_total and m_unique:
            try:
                total_val = int(m_total.group(1))
                unique_val = int(m_unique.group(1))
            except Exception:
                total_val = None
                unique_val = None
            # Compute from credentials.csv
            total_expected = len(credentials) if creds_rows is not None else 0
            unique_expected = len(set([c["password"] for c in credentials])) if creds_rows is not None else 0
            if total_val == total_expected and unique_val == unique_expected and total_val == 8 and unique_val == 8:
                checks["summary_counts_ok"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Explicitly ensure no-op baseline: if output dir missing or empty, set reward 0.0
    if not os.path.isdir(output_dir) or not any(os.scandir(output_dir)):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()