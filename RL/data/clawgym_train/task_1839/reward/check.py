import json
import os
import sys
from urllib.parse import urlparse, parse_qs, unquote

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def extract_otpauth_and_seed(account_data):
    otpauth_uri = None
    seed = None

    if isinstance(account_data, dict):
        # direct keys
        for key in ("otpauth", "otpauth_uri", "uri", "otp_uri", "otpauthURL", "otpAuthUri"):
            v = account_data.get(key)
            if isinstance(v, str) and v.startswith("otpauth://"):
                otpauth_uri = v
                break
        # scan values for otpauth
        if otpauth_uri is None:
            for v in account_data.values():
                if isinstance(v, str) and v.startswith("otpauth://"):
                    otpauth_uri = v
                    break
        # seed possibly present directly
        for key in ("seed", "secret", "totp_seed", "totpSecret"):
            v = account_data.get(key)
            if isinstance(v, str) and v:
                seed = v
                break

    # if still no seed, try to parse from otpauth URI
    if seed is None and otpauth_uri:
        try:
            parsed = urlparse(otpauth_uri)
            q = parse_qs(parsed.query)
            if "secret" in q and len(q["secret"]) > 0:
                seed = unquote(q["secret"][0])
        except Exception:
            pass

    return otpauth_uri, seed

def check_no_secret_leak(text: str, otpauth_uri: str | None, seed: str | None) -> bool:
    # If text empty or file missing, treat as failure (must provide outputs without leaks)
    if text is None or text == "":
        return False
    lower = text.lower()
    upper = text.upper()
    # Disallow any mention of otpauth://
    if "otpauth://" in lower:
        return False
    # Disallow full otpauth URI if known
    if otpauth_uri and otpauth_uri in text:
        return False
    # Disallow seed string if known (case-insensitive check by uppercasing content and seed)
    if seed:
        seed_upper = seed.upper()
        if seed_upper and seed_upper in upper:
            return False
    return True

def contains_all(haystack: str, needles: list[str]) -> bool:
    return all(n in haystack for n in needles)

def safety_rules_matched(setup_text: str, ops_text: str) -> int:
    combined = (setup_text or "") + "\n" + (ops_text or "")
    low = combined.lower()

    def any_phrase(phrases):
        return any(p.lower() in low for p in phrases)

    count = 0
    # 1) Do not store TOTP seeds in plaintext
    if any_phrase([
        "do not store totp seeds in plaintext",
        "never store totp seeds in plaintext",
        "avoid storing totp seeds in plaintext",
        "do not store seeds in plaintext",
        "no plaintext storage of totp seeds",
        "avoid plaintext storage of totp",
    ]):
        count += 1

    # 2) Confirm you own the account / authorization
    if any_phrase([
        "confirm you own the account",
        "confirm authorization",
        "confirm account ownership",
        "you are authorized to access",
        "you are authorized to manage",
    ]):
        count += 1

    # 3) No background or silent code generation
    if any_phrase([
        "no background or silent code generation",
        "no background code generation",
        "no silent code generation",
        "do not generate codes in the background",
    ]):
        count += 1

    # 4) Do not bulk-export secrets
    if any_phrase([
        "do not bulk-export secrets",
        "do not bulk export secrets",
        "no bulk-export of secrets",
        "no bulk export of secrets",
        "do not export secrets in bulk",
    ]):
        count += 1

    # 5) Prefer OS secure storage / system vault
    if any_phrase([
        "prefer os secure storage",
        "system vault",
        "prefer system vault",
        "use the system key store",
        "use os secure storage",
        "use operating system secure storage",
    ]):
        count += 1

    # 6) Delete aliases on rotation
    if any_phrase([
        "delete aliases on rotation",
        "delete alias on rotation",
        "delete the alias on rotation",
        "delete aliases during rotation",
        "delete the alias during rotation",
    ]):
        count += 1

    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    account_json_path = os.path.join(input_dir, "account.json")
    policy_txt_path = os.path.join(input_dir, "policy.txt")  # read not required for scoring, but available
    setup_path = os.path.join(output_dir, "setup_guide.md")
    alias_metadata_path = os.path.join(output_dir, "alias_metadata.json")
    ops_path = os.path.join(output_dir, "operational_checklist.md")

    # Load inputs
    account_data = load_json(account_json_path) or {}
    alias = account_data.get("alias") if isinstance(account_data, dict) else None
    issuer = account_data.get("issuer") if isinstance(account_data, dict) else None
    account_field = account_data.get("account") if isinstance(account_data, dict) else None

    otpauth_uri, seed = extract_otpauth_and_seed(account_data)

    # Read outputs
    setup_text = read_text(setup_path) if os.path.isfile(setup_path) else ""
    alias_meta_text = read_text(alias_metadata_path) if os.path.isfile(alias_metadata_path) else ""
    ops_text = read_text(ops_path) if os.path.isfile(ops_path) else ""

    checks = {
        # existence
        "has_setup_guide": os.path.isfile(setup_path),
        "has_alias_metadata": os.path.isfile(alias_metadata_path),
        "has_operational_checklist": os.path.isfile(ops_path),

        # will fill after computations
        "no_secret_leak_setup_guide": False,
        "no_secret_leak_alias_metadata": False,
        "no_secret_leak_operational_checklist": False,
        "setup_contains_alias_string": False,
        "setup_has_storage_command_basic": False,
        "setup_has_code_generation_json": False,
        "setup_has_delete_command": False,
        "setup_mentions_expires_in": False,
        "safety_rules_5plus": False,
        "alias_metadata_valid_json": False,
        "alias_metadata_matches_values": False,
        "alias_metadata_backend_system_vault": False,
        "alias_metadata_no_seed_no_otpauth": False,
        "checklist_has_sections": False,
        "checklist_no_secrets": False,
    }

    # Secret hygiene checks for each output file (only if file exists)
    if checks["has_setup_guide"]:
        checks["no_secret_leak_setup_guide"] = check_no_secret_leak(setup_text, otpauth_uri, seed)
    if checks["has_alias_metadata"]:
        checks["no_secret_leak_alias_metadata"] = check_no_secret_leak(alias_meta_text, otpauth_uri, seed)
    if checks["has_operational_checklist"]:
        checks["no_secret_leak_operational_checklist"] = check_no_secret_leak(ops_text, otpauth_uri, seed)

    # Setup guide command and content checks
    if checks["has_setup_guide"] and isinstance(alias, str) and alias:
        # alias must appear
        checks["setup_contains_alias_string"] = alias in setup_text

        # storage command: python3 scripts/totp_add.py + --alias <alias> + --issuer + issuer + --account + account
        add_present = "python3 scripts/totp_add.py" in setup_text
        alias_part = f"--alias {alias}" in setup_text
        issuer_flag = "--issuer" in setup_text
        issuer_value_present = isinstance(issuer, str) and issuer in setup_text if issuer else False
        account_flag = "--account" in setup_text
        account_value_present = isinstance(account_field, str) and account_field in setup_text if account_field else False
        checks["setup_has_storage_command_basic"] = all([add_present, alias_part, issuer_flag, issuer_value_present, account_flag, account_value_present])

        # code generation with json
        checks["setup_has_code_generation_json"] = f"python3 scripts/totp_code.py --alias {alias} --json" in setup_text

        # delete command
        checks["setup_has_delete_command"] = f"python3 scripts/totp_delete.py --alias {alias}" in setup_text

        # mentions expires_in
        checks["setup_mentions_expires_in"] = "expires_in" in setup_text

    # Safety rules across setup_guide and operational_checklist: need at least 5
    if checks["has_setup_guide"] and checks["has_operational_checklist"]:
        matched = safety_rules_matched(setup_text, ops_text)
        checks["safety_rules_5plus"] = matched >= 5

    # alias_metadata.json schema checks
    alias_meta_json = None
    if checks["has_alias_metadata"]:
        alias_meta_json = load_json(alias_metadata_path)
        if isinstance(alias_meta_json, dict):
            checks["alias_metadata_valid_json"] = True
            # required keys
            has_keys = all(k in alias_meta_json for k in ("alias", "issuer", "account", "backend"))
            # values match
            values_match = (
                isinstance(alias, str) and isinstance(issuer, str) and isinstance(account_field, str) and
                alias_meta_json.get("alias") == alias and
                alias_meta_json.get("issuer") == issuer and
                alias_meta_json.get("account") == account_field
            )
            checks["alias_metadata_matches_values"] = bool(has_keys and values_match)
            # backend value
            checks["alias_metadata_backend_system_vault"] = (alias_meta_json.get("backend") == "system-vault")
            # no seed key and no otpauth values
            no_seed_key = "seed" not in alias_meta_json
            no_otpauth_value = True
            for v in alias_meta_json.values():
                try:
                    if isinstance(v, str) and "otpauth" in v.lower():
                        no_otpauth_value = False
                        break
                except Exception:
                    continue
            checks["alias_metadata_no_seed_no_otpauth"] = bool(no_seed_key and no_otpauth_value)
        else:
            checks["alias_metadata_valid_json"] = False

    # operational_checklist.md structure
    if checks["has_operational_checklist"]:
        low_ops = ops_text.lower()
        has_pre = "pre-flight".lower() in low_ops
        has_rot = "rotation" in low_ops
        has_off = "offboarding" in low_ops
        checks["checklist_has_sections"] = all([has_pre, has_rot, has_off])
        checks["checklist_no_secrets"] = check_no_secret_leak(ops_text, otpauth_uri, seed)

    # Overall success requires all checks True
    # Define which checks are required (all keys in checks must pass)
    all_checks_pass = all(checks.values())

    reward = 1.0 if all_checks_pass else 0.0

    # Output JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()